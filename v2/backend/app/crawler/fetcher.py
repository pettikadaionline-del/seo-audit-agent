"""Polite HTTP fetcher: per-host rate limiting, manual redirect handling with an
SSRF check on every hop, response-size cap, timing capture."""

import asyncio
import ipaddress
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings
from app.core.security import UnsafeURLError, ip_is_public, assert_public_url


def _peer_is_public(resp: httpx.Response) -> bool:
    """Check the IP we actually connected to (defends against DNS rebinding between
    the pre-flight resolution in assert_public_url and the real connection)."""
    stream = resp.extensions.get("network_stream")
    addr = stream.get_extra_info("server_addr") if stream else None
    if not addr:
        return True  # transport doesn't expose it (e.g. via HTTP proxy); pre-flight check still applied
    try:
        return ip_is_public(ipaddress.ip_address(addr[0]))
    except ValueError:
        return False


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    redirect_chain: list[tuple[str, int]] = field(default_factory=list)
    ttfb_ms: float | None = None
    total_ms: float | None = None
    error: str | None = None
    truncated: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").lower()

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type

    @property
    def text(self) -> str:
        charset = "utf-8"
        ct = self.content_type
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=settings.request_timeout_seconds,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self.crawl_delay: dict[str, float] = {}
        # Behind an HTTP(S) proxy the TCP peer is the proxy, so the peer-IP check can't apply.
        self._proxied = any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"))

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def _throttle(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = max(self.settings.request_delay_seconds, self.crawl_delay.get(host, 0.0))
            wait = self._host_last.get(host, 0.0) + delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_last[host] = time.monotonic()

    async def fetch(self, url: str, method: str = "GET") -> FetchResult:
        chain: list[tuple[str, int]] = []
        current = url
        started = time.perf_counter()
        for _ in range(self.settings.max_redirects + 1):
            try:
                await assert_public_url(current, self.settings.allow_private_targets)
            except UnsafeURLError as exc:
                return FetchResult(url, current, None, redirect_chain=chain, error=f"blocked: {exc}")
            host = urlsplit(current).netloc
            await self._throttle(host)
            try:
                hop_start = time.perf_counter()
                async with self._client.stream(method, current) as resp:
                    ttfb = (time.perf_counter() - hop_start) * 1000
                    if not self.settings.allow_private_targets and not self._proxied and not _peer_is_public(resp):
                        return FetchResult(url, current, None, redirect_chain=chain, error="blocked: connected to a non-public address")
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    if resp.is_redirect and "location" in headers:
                        chain.append((current, resp.status_code))
                        current = urljoin(current, headers["location"])
                        continue
                    body = bytearray()
                    truncated = False
                    if method != "HEAD":
                        async for chunk in resp.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self.settings.max_response_bytes:
                                truncated = True
                                break
                    return FetchResult(
                        requested_url=url,
                        final_url=current,
                        status=resp.status_code,
                        headers=headers,
                        body=bytes(body),
                        redirect_chain=chain,
                        ttfb_ms=round(ttfb, 1),
                        total_ms=round((time.perf_counter() - started) * 1000, 1),
                        truncated=truncated,
                    )
            except httpx.TimeoutException:
                return FetchResult(url, current, None, redirect_chain=chain, error="timeout")
            except httpx.HTTPError as exc:
                return FetchResult(url, current, None, redirect_chain=chain, error=f"{type(exc).__name__}: {exc}"[:300])
        return FetchResult(url, current, None, redirect_chain=chain, error="too many redirects")

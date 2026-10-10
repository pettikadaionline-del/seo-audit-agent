"""Safe HTTP fetcher: manual redirects (each hop SSRF-checked), size caps, timeouts."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from app.config import Settings
from app.security.url_guard import UnsafeURLError, validate_url


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    elapsed_ms: float = 0.0
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def is_html(self) -> bool:
        return self.content_type in ("text/html", "application/xhtml+xml")

    def text(self) -> str:
        enc = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            enc = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(enc, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(settings.request_timeout_s),
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            },
            transport=transport,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def fetch(self, url: str, method: str = "GET", max_bytes: int | None = None) -> FetchResult:
        max_bytes = max_bytes or self.settings.max_response_bytes
        chain: list[str] = []
        current = url
        start = time.perf_counter()
        for _ in range(self.settings.max_redirects + 1):
            try:
                await validate_url(current, self.settings.allow_private_networks)
            except UnsafeURLError as exc:
                return FetchResult(url, current, 0, redirect_chain=chain, error=f"Blocked: {exc}")
            try:
                async with self.client.stream(method, current) as resp:
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    if resp.is_redirect and "location" in headers:
                        chain.append(current)
                        current = urljoin(current, headers["location"])
                        continue
                    body = bytearray()
                    truncated = False
                    if method != "HEAD":
                        async for chunk in resp.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > max_bytes:
                                truncated = True
                                break
                    return FetchResult(
                        url=url,
                        final_url=str(resp.url),
                        status_code=resp.status_code,
                        headers=headers,
                        body=bytes(body[:max_bytes]),
                        elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
                        redirect_chain=chain,
                        truncated=truncated,
                    )
            except httpx.TimeoutException:
                return FetchResult(url, current, 0, redirect_chain=chain, error="Timeout")
            except httpx.HTTPError as exc:
                return FetchResult(url, current, 0, redirect_chain=chain, error=f"{type(exc).__name__}: {exc}")
        return FetchResult(url, current, 0, redirect_chain=chain, error="Too many redirects")

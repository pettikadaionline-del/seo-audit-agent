"""Breadth-first, polite, same-site crawler."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from app.config import Settings
from app.crawler.fetcher import Fetcher
from app.crawler.parser import parse_html
from app.crawler.robots import Robots, load_sitemaps
from app.crawler.urls import is_crawlable_resource, normalize, same_site
from app.models import PageData, SiteContext

log = logging.getLogger(__name__)
ProgressCb = Callable[[int, str], Awaitable[None]]


class Crawler:
    def __init__(
        self,
        settings: Settings,
        start_url: str,
        max_pages: int,
        max_depth: int,
        respect_robots: bool = True,
        fetcher: Fetcher | None = None,
        progress: ProgressCb | None = None,
        deadline: float | None = None,
    ):
        self.settings = settings
        self.start_url = normalize(start_url) or start_url
        parts = urlsplit(self.start_url)
        self.origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        self.host = parts.hostname or ""
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.respect_robots = respect_robots
        self.fetcher = fetcher or Fetcher(settings)
        self._owns_fetcher = fetcher is None
        self.progress = progress
        self.deadline = deadline  # time.monotonic() value; stop fetching new pages after it
        self.timed_out = False
        self.pages: dict[str, PageData] = {}
        self.robots = Robots(self.origin, settings.user_agent)

    async def run(self) -> tuple[list[PageData], SiteContext]:
        try:
            site = await self._site_checks()
            pages = await self._crawl(site)
            return pages, site
        finally:
            if self._owns_fetcher:
                await self.fetcher.aclose()

    async def _site_checks(self) -> SiteContext:
        await self.robots.load(self.fetcher)
        site = SiteContext(
            start_url=self.start_url,
            origin=self.origin,
            https=self.start_url.startswith("https://"),
            robots_txt_found=self.robots.found,
            robots_txt=(self.robots.raw or "")[:5000] or None,
            robots_disallow_all=self.robots.found and self.robots.disallow_all_for_googlebot,
            sitemaps_declared=self.robots.sitemaps,
        )
        candidates = site.sitemaps_declared or [f"{self.origin}/sitemap.xml"]
        site.sitemap_urls, site.sitemap_errors = await load_sitemaps(self.fetcher, candidates, deadline=self.deadline)
        if not site.sitemaps_declared and not site.sitemap_urls:
            site.sitemap_errors = ["No sitemap declared in robots.txt and /sitemap.xml not found"]

        # http -> https and www consistency
        if site.https:
            res = await self.fetcher.fetch(self.start_url.replace("https://", "http://", 1), method="HEAD")
            site.http_redirects_to_https = bool(res.redirect_chain) and res.final_url.startswith("https://")
        alt_host = self.host[4:] if self.host.startswith("www.") else f"www.{self.host}"
        alt = self.origin.replace(self.host, alt_host, 1) + "/"
        res = await self.fetcher.fetch(alt, method="HEAD")
        if not res.error and res.status_code < 400:
            site.www_consistent = (urlsplit(res.final_url).hostname or "") == self.host
        llms = await self.fetcher.fetch(f"{self.origin}/llms.txt", max_bytes=256 * 1024)
        site.llms_txt_found = llms.status_code == 200 and "text/" in llms.content_type and not llms.is_html
        return site

    async def _crawl(self, site: SiteContext) -> list[PageData]:
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        seen: set[str] = set()

        def enqueue(url: str, depth: int) -> None:
            n = normalize(url)
            if not n or n in seen or len(seen) >= self.max_pages:
                return
            if not same_site(n, self.host) or not is_crawlable_resource(n):
                return
            seen.add(n)
            queue.put_nowait((n, depth))

        enqueue(self.start_url, 0)
        for u in site.sitemap_urls[: self.max_pages]:
            enqueue(u, 1)

        delay = max(self.settings.delay_between_requests_s, self.robots.crawl_delay() or 0)
        delay = min(delay, 5.0)
        sem = asyncio.Semaphore(self.settings.concurrency)

        async def worker() -> None:
            while True:
                url, depth = await queue.get()
                try:
                    if self._out_of_time():
                        self.timed_out = True
                        continue
                    async with sem:
                        page = await self._fetch_page(url, depth)
                        await asyncio.sleep(delay)
                    self.pages[url] = page
                    if self.progress:
                        await self.progress(len(self.pages), url)
                    if depth < self.max_depth and not page.error:
                        follow = not (page.meta_robots and "nofollow" in page.meta_robots)
                        for link in page.links:
                            if link.internal and follow and not link.nofollow:
                                enqueue(link.url, depth + 1)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(self.settings.concurrency)]
        await queue.join()
        for w in workers:
            w.cancel()
        site.crawl_truncated = len(seen) >= self.max_pages or self.timed_out
        return sorted(self.pages.values(), key=lambda p: (p.depth, p.url))

    def _out_of_time(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    async def _fetch_page(self, url: str, depth: int) -> PageData:
        if self.respect_robots and not self.robots.allowed(url):
            return PageData(url=url, final_url=url, status_code=0, depth=depth, blocked_by_robots=True, error="Blocked by robots.txt")
        res = await self.fetcher.fetch(url)
        page = PageData(
            url=url,
            final_url=normalize(res.final_url) or res.final_url,
            status_code=res.status_code,
            depth=depth,
            redirect_chain=res.redirect_chain,
            content_type=res.content_type,
            headers={k: v for k, v in res.headers.items() if k in KEEP_HEADERS},
            response_time_ms=res.elapsed_ms,
            html_bytes=len(res.body),
            error=res.error,
        )
        if res.is_html and res.status_code < 400 and res.body:
            try:
                parse_html(page, res.text(), self.host)
            except Exception as exc:  # parser must never kill the crawl
                log.exception("parse failed for %s", url)
                page.error = f"Parse error: {exc}"
        return page


KEEP_HEADERS = {
    "content-type", "content-encoding", "cache-control", "x-robots-tag", "strict-transport-security",
    "content-security-policy", "x-content-type-options", "x-frame-options", "server", "last-modified",
    "etag", "vary", "link",
}

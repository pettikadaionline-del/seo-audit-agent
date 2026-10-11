"""Breadth-first site crawler. Respects robots.txt (incl. crawl-delay), stays on
the target site, caps pages/depth, and records link-check status for internal
link targets so linking audits work on real responses."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.core.config import Settings
from app.crawler.fetcher import FetchResult, Fetcher
from app.crawler.parser import PageData, normalize_link, parse_html, same_site
from app.crawler.robots import RobotsInfo, parse_robots
from app.crawler.sitemap import SitemapInfo, discover_sitemaps

ProgressCb = Callable[[str, float, str], Awaitable[None]]

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip", ".mp4", ".mp3",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf", ".xml", ".json", ".avif", ".doc", ".docx", ".xls", ".xlsx",
)


@dataclass
class SiteMeta:
    start_url: str
    root: str
    https: bool
    http_redirects_to_https: bool | None = None
    homepage_status: int | None = None
    robots: RobotsInfo | None = None
    sitemap: SitemapInfo | None = None
    llms_txt: bool = False
    blocked_by_robots: list[str] = field(default_factory=list)
    skipped_over_limit: int = 0
    external_link_status: dict[str, int | None] = field(default_factory=dict)


@dataclass
class CrawlResult:
    meta: SiteMeta
    pages: list[PageData]


def _to_page(res: FetchResult, depth: int) -> PageData:
    h = res.headers
    return PageData(
        url=res.requested_url,
        final_url=res.final_url,
        status=res.status,
        error=res.error,
        depth=depth,
        redirect_chain=[list(x) for x in res.redirect_chain],
        content_type=res.content_type,
        ttfb_ms=res.ttfb_ms,
        total_ms=res.total_ms,
        html_bytes=len(res.body),
        compressed=h.get("content-encoding", "") in ("gzip", "br", "deflate", "zstd"),
        cache_control=h.get("cache-control"),
        x_robots_tag=h.get("x-robots-tag"),
        hsts="strict-transport-security" in h,
    )


async def crawl_site(
    start_url: str,
    settings: Settings,
    max_pages: int,
    max_depth: int,
    progress: ProgressCb | None = None,
    check_external_links: bool = True,
    progress_range: tuple[float, float] = (0.05, 0.6),
) -> CrawlResult:
    lo, hi = progress_range

    async def report(stage: str, frac: float, msg: str):
        if progress:
            await progress(stage, lo + (hi - lo) * frac, msg)

    parts = urlsplit(start_url)
    root = f"{parts.scheme}://{parts.netloc}"
    meta = SiteMeta(start_url=start_url, root=root, https=parts.scheme == "https")

    async with Fetcher(settings) as fetcher:
        await report("crawl", 0.0, "Fetching robots.txt")
        rres = await fetcher.fetch(f"{root}/robots.txt")
        meta.robots = parse_robots(f"{root}/robots.txt", rres.status, rres.text if rres.status else "", settings.user_agent)
        if meta.robots.crawl_delay:
            fetcher.crawl_delay[parts.netloc] = min(meta.robots.crawl_delay, 10.0)

        await report("crawl", 0.03, "Checking HTTPS redirect and llms.txt")
        if meta.https:
            http_res = await fetcher.fetch(start_url.replace("https://", "http://", 1), method="HEAD")
            if http_res.status is not None or http_res.redirect_chain:
                meta.http_redirects_to_https = http_res.final_url.startswith("https://")
        llms = await fetcher.fetch(f"{root}/llms.txt")
        meta.llms_txt = llms.status == 200 and "html" not in llms.content_type and len(llms.body) > 0

        await report("crawl", 0.05, "Reading XML sitemaps")
        candidates = (meta.robots.sitemaps if meta.robots else []) or [f"{root}/sitemap.xml"]
        meta.sitemap = await discover_sitemaps(fetcher, candidates)
        sitemap_set = set()
        for u in meta.sitemap.urls:
            n = normalize_link(root, u)
            if n:
                sitemap_set.add(n)

        # Priority = click depth, so link-discovered pages are crawled before sitemap-only
        # seeds. Sitemap seeds get depth -1 ("not reached via internal links") unless a
        # link to them is found later, which lets the linking audit spot orphan pages.
        queue: asyncio.PriorityQueue[tuple[int, int, str, int]] = asyncio.PriorityQueue()
        counter = 0
        seen: set[str] = {start_url}
        queue.put_nowait((0, counter, start_url, 0))
        for u in sorted(sitemap_set):
            if same_site(u, start_url) and u not in seen:
                seen.add(u)
                counter += 1
                queue.put_nowait((max_depth + 1, counter, u, -1))

        pages: dict[str, PageData] = {}
        lock = asyncio.Lock()
        depth_of: dict[str, int] = {start_url: 0}

        async def worker():
            nonlocal counter
            while True:
                try:
                    _, _, url, depth = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    async with lock:
                        if len(pages) >= max_pages:
                            meta.skipped_over_limit += 1
                            continue
                        pages[url] = PageData(url=url, final_url=url, status=None)  # reserve slot
                    if meta.robots and not meta.robots.allowed(settings.user_agent, url):
                        meta.blocked_by_robots.append(url)
                        async with lock:
                            pages.pop(url, None)
                        continue
                    res = await fetcher.fetch(url)
                    page = _to_page(res, depth_of.get(url, depth))
                    if page.depth < 0:
                        page.depth = -1
                    page.in_sitemap = url in sitemap_set or res.final_url in sitemap_set
                    if res.status == 200 and res.is_html and same_site(res.final_url, start_url):
                        parse_html(page, res.text)
                        for link in page.links:
                            if not link.internal:
                                continue
                            target = link.url
                            if urlsplit(target).path.lower().endswith(SKIP_EXTENSIONS):
                                continue
                            async with lock:
                                new_depth = page.depth + 1
                                if target in depth_of and depth_of[target] <= new_depth:
                                    continue
                                depth_of[target] = new_depth
                                if target not in seen and new_depth <= max_depth:
                                    seen.add(target)
                                    counter += 1
                                    queue.put_nowait((new_depth, counter, target, new_depth))
                    async with lock:
                        pages[url] = page
                    await report("crawl", 0.1 + 0.8 * min(1.0, len(pages) / max_pages), f"Crawled {len(pages)} pages: {url}")
                finally:
                    queue.task_done()

        # Workers exit when the queue is momentarily empty, so loop until truly drained.
        while not queue.empty():
            await asyncio.gather(*(worker() for _ in range(settings.crawl_concurrency)))

        # Correct depth for sitemap-seeded pages later found through links.
        for url, p in pages.items():
            p.depth = depth_of.get(url, -1)
            p.in_sitemap = p.in_sitemap or url in sitemap_set

        homepage = pages.get(start_url)
        meta.homepage_status = homepage.status if homepage else None

        if check_external_links:
            await report("crawl", 0.92, "Checking a sample of external links")
            externals: list[str] = []
            for p in pages.values():
                for link in p.links:
                    if not link.internal and link.url not in externals:
                        externals.append(link.url)
            sample = externals[:40]

            async def check(u: str):
                r = await fetcher.fetch(u, method="HEAD")
                if r.status in (405, 403, 501):  # HEAD unsupported -> retry GET
                    r = await fetcher.fetch(u)
                meta.external_link_status[u] = r.status

            sem = asyncio.Semaphore(settings.crawl_concurrency)

            async def guarded(u):
                async with sem:
                    await check(u)

            await asyncio.gather(*(guarded(u) for u in sample))

        await report("crawl", 1.0, f"Crawl complete: {len(pages)} pages")
        return CrawlResult(meta=meta, pages=[p for p in pages.values() if p.status is not None or p.error])

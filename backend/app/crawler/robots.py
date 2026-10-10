"""robots.txt and XML sitemap handling."""
from __future__ import annotations

import gzip
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from app.crawler.fetcher import Fetcher


class Robots:
    def __init__(self, origin: str, user_agent: str):
        self.origin = origin
        self.user_agent = user_agent
        self.parser = RobotFileParser()
        self.found = False
        self.raw: str | None = None

    async def load(self, fetcher: Fetcher) -> None:
        res = await fetcher.fetch(f"{self.origin}/robots.txt", max_bytes=512 * 1024)
        if res.status_code == 200 and not res.error:
            self.found = True
            self.raw = res.text()
            self.parser.parse(self.raw.splitlines())
        elif res.status_code in (401, 403):
            self.parser.disallow_all = True  # per RFC 9309 treat as full disallow
        else:
            self.parser.allow_all = True

    def allowed(self, url: str) -> bool:
        return self.parser.can_fetch(self.user_agent, url)

    @property
    def sitemaps(self) -> list[str]:
        return list(self.parser.site_maps() or [])

    @property
    def disallow_all_for_googlebot(self) -> bool:
        return not self.parser.can_fetch("Googlebot", f"{self.origin}/")

    def crawl_delay(self) -> float | None:
        d = self.parser.crawl_delay(self.user_agent)
        return float(d) if d else None


async def load_sitemaps(fetcher: Fetcher, sitemap_urls: list[str], limit: int = 5000) -> tuple[list[str], list[str]]:
    """Fetch sitemaps (incl. sitemap indexes, gzip). Returns (urls, errors)."""
    urls: list[str] = []
    errors: list[str] = []
    queue = list(dict.fromkeys(sitemap_urls))
    seen: set[str] = set()
    while queue and len(seen) < 25 and len(urls) < limit:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        res = await fetcher.fetch(sm, max_bytes=20 * 1024 * 1024)
        if res.error or res.status_code != 200:
            errors.append(f"{sm}: {res.error or 'HTTP ' + str(res.status_code)}")
            continue
        body = res.body
        if sm.endswith(".gz") or body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError:
                errors.append(f"{sm}: invalid gzip")
                continue
        soup = BeautifulSoup(body, "xml")
        if soup.find("sitemapindex"):
            queue.extend(loc.get_text(strip=True) for loc in soup.select("sitemap > loc"))
        elif soup.find("urlset"):
            urls.extend(loc.get_text(strip=True) for loc in soup.select("url > loc"))
        else:
            errors.append(f"{sm}: not a valid XML sitemap")
    return urls[:limit], errors

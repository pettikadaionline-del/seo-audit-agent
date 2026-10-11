import gzip
import io
from dataclasses import dataclass, field

from lxml import etree

from app.crawler.fetcher import Fetcher

MAX_DECOMPRESSED = 50 * 1024 * 1024


@dataclass
class SitemapInfo:
    found: list[str] = field(default_factory=list)  # sitemap URLs successfully parsed
    errors: list[dict] = field(default_factory=list)  # {url, error}
    urls: list[str] = field(default_factory=list)
    lastmod_count: int = 0


def _parse(body: bytes) -> tuple[str, list[str], int]:
    if body[:2] == b"\x1f\x8b":
        # Cap decompressed size (sitemap protocol limit is 50MB) to avoid gzip bombs.
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as gz:
            body = gz.read(MAX_DECOMPRESSED + 1)
        if len(body) > MAX_DECOMPRESSED:
            raise ValueError("Sitemap exceeds 50MB uncompressed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(body, parser=parser)
    tag = etree.QName(root).localname
    locs, lastmods = [], 0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        name = etree.QName(el).localname
        if name == "loc" and el.text:
            locs.append(el.text.strip())
        elif name == "lastmod" and el.text:
            lastmods += 1
    return tag, locs, lastmods


async def discover_sitemaps(fetcher: Fetcher, candidates: list[str], max_urls: int = 5000, max_files: int = 10) -> SitemapInfo:
    info = SitemapInfo()
    queue = list(dict.fromkeys(candidates))
    seen: set[str] = set()
    while queue and len(seen) < max_files and len(info.urls) < max_urls:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        res = await fetcher.fetch(sm)
        if res.status != 200:
            info.errors.append({"url": sm, "error": res.error or f"HTTP {res.status}"})
            continue
        try:
            tag, locs, lastmods = _parse(res.body)
        except Exception as exc:  # malformed XML is itself a finding
            info.errors.append({"url": sm, "error": f"Invalid XML: {exc}"[:200]})
            continue
        info.found.append(sm)
        info.lastmod_count += lastmods
        if tag == "sitemapindex":
            queue.extend(locs)
        else:
            info.urls.extend(locs[: max_urls - len(info.urls)])
    info.urls = list(dict.fromkeys(info.urls))
    return info

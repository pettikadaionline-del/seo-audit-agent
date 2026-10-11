"""Turn a fetched HTML document into structured, evidence-bearing page data."""

import hashlib
import json
import re
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

GENERIC_ANCHORS = {"click here", "here", "read more", "more", "learn more", "link", "this", "go", "continue", "details"}


class LinkData(BaseModel):
    url: str
    anchor: str
    internal: bool
    nofollow: bool


class ImageData(BaseModel):
    src: str
    alt: str | None
    has_dimensions: bool
    lazy: bool


class PageData(BaseModel):
    url: str
    final_url: str
    status: int | None
    error: str | None = None
    depth: int = 0
    redirect_chain: list[list] = Field(default_factory=list)
    content_type: str = ""
    ttfb_ms: float | None = None
    total_ms: float | None = None
    html_bytes: int = 0
    compressed: bool = False
    cache_control: str | None = None
    x_robots_tag: str | None = None
    hsts: bool = False
    in_sitemap: bool = False

    # head
    title: str | None = None
    meta_description: str | None = None
    meta_robots: str | None = None
    canonical: str | None = None
    lang: str | None = None
    viewport: bool = False
    og: dict[str, str] = Field(default_factory=dict)
    twitter: dict[str, str] = Field(default_factory=dict)
    hreflang: list[dict] = Field(default_factory=list)

    # body
    headings: list[list] = Field(default_factory=list)  # [level, text] in document order
    h1: list[str] = Field(default_factory=list)
    word_count: int = 0
    text_sample: str = ""
    content_hash: str | None = None
    shingles: list[int] = Field(default_factory=list)
    readability: float | None = None
    question_headings: int = 0
    links: list[LinkData] = Field(default_factory=list)
    images: list[ImageData] = Field(default_factory=list)
    json_ld: list[dict] = Field(default_factory=list)
    json_ld_errors: list[str] = Field(default_factory=list)
    microdata_types: list[str] = Field(default_factory=list)
    scripts_total: int = 0
    render_blocking_scripts: int = 0
    stylesheets: int = 0
    mixed_content: list[str] = Field(default_factory=list)
    has_author: bool = False
    has_date: bool = False

    @property
    def indexable(self) -> bool:
        directives = f"{self.meta_robots or ''},{self.x_robots_tag or ''}".lower()
        return self.status == 200 and "noindex" not in directives


def normalize_link(base: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
        return None
    try:
        absolute, _ = urldefrag(urljoin(base, href))
        parts = urlsplit(absolute)
        port = parts.port
    except ValueError:  # malformed href (bad port, invalid IPv6 literal)
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    netloc = parts.hostname.lower() + (f":{port}" if port else "")
    return f"{parts.scheme}://{netloc}{path}{query}"


def same_site(a: str, b: str) -> bool:
    ha, hb = urlsplit(a).hostname or "", urlsplit(b).hostname or ""
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    return strip(ha) == strip(hb)


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def flesch_reading_ease(text: str) -> float | None:
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z]+", text)
    if len(words) < 100 or not sentences:
        return None
    syll = sum(_syllables(w) for w in words)
    score = 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syll / len(words))
    return round(max(0.0, min(100.0, score)), 1)


def shingle_hashes(words: list[str], k: int = 5, keep: int = 200) -> list[int]:
    """Min-hash-style sample of word k-shingles for near-duplicate detection."""
    if len(words) < k:
        return []
    hashes = {
        int(hashlib.md5(" ".join(words[i : i + k]).encode()).hexdigest()[:12], 16)
        for i in range(len(words) - k + 1)
    }
    return sorted(hashes)[:keep]


def _flatten_jsonld(data) -> list[dict]:
    out = []
    if isinstance(data, list):
        for item in data:
            out.extend(_flatten_jsonld(item))
    elif isinstance(data, dict):
        if "@graph" in data:
            out.extend(_flatten_jsonld(data["@graph"]))
        if "@type" in data:
            out.append(data)
    return out


def parse_html(page: PageData, html: str) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    base = page.final_url
    base_tag = soup.find("base", href=True)
    if base_tag:
        base = urljoin(base, base_tag["href"])

    if soup.title and soup.title.string:
        page.title = soup.title.string.strip()
    html_tag = soup.find("html")
    page.lang = html_tag.get("lang") if html_tag else None

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        prop = (meta.get("property") or "").lower()
        content = (meta.get("content") or "").strip()
        if name == "description":
            page.meta_description = content
        elif name == "robots":
            page.meta_robots = content.lower()
        elif name == "viewport":
            page.viewport = True
        elif name in ("author", "article:author") or prop == "article:author":
            page.has_author = True
        elif prop.startswith("og:"):
            page.og[prop[3:]] = content
        elif name.startswith("twitter:"):
            page.twitter[name[8:]] = content
        if prop in ("article:published_time", "article:modified_time") or name in ("date", "last-modified"):
            page.has_date = True

    for link in soup.find_all("link", href=True):
        rel = [r.lower() for r in (link.get("rel") or [])]
        if "canonical" in rel:
            page.canonical = normalize_link(base, link["href"])
        if "alternate" in rel and link.get("hreflang"):
            page.hreflang.append({"lang": link["hreflang"], "href": normalize_link(base, link["href"])})
        if "stylesheet" in rel:
            page.stylesheets += 1
        if base.startswith("https://") and link["href"].startswith("http://") and "stylesheet" in rel:
            page.mixed_content.append(link["href"])

    for script in soup.find_all("script"):
        stype = (script.get("type") or "").lower()
        if stype == "application/ld+json":
            raw = script.string or script.get_text() or ""
            try:
                page.json_ld.extend(_flatten_jsonld(json.loads(raw)))
            except json.JSONDecodeError as exc:
                page.json_ld_errors.append(f"Invalid JSON-LD: {exc.msg} (line {exc.lineno})")
            continue
        if script.get("src"):
            page.scripts_total += 1
            if base.startswith("https://") and script["src"].startswith("http://"):
                page.mixed_content.append(script["src"])
            if script.find_parent("head") is not None and not script.has_attr("async") and not script.has_attr("defer") and stype != "module":
                page.render_blocking_scripts += 1

    page.microdata_types = sorted({el.get("itemtype", "").rsplit("/", 1)[-1] for el in soup.find_all(attrs={"itemtype": True})} - {""})

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if base.startswith("https://") and src.startswith("http://"):
            page.mixed_content.append(src)
        page.images.append(
            ImageData(
                src=urljoin(base, src) if src else "",
                alt=img.get("alt"),
                has_dimensions=bool(img.get("width") and img.get("height")),
                lazy=(img.get("loading") or "").lower() == "lazy",
            )
        )

    for a in soup.find_all("a", href=True):
        target = normalize_link(base, a["href"])
        if not target:
            continue
        rel = [r.lower() for r in (a.get("rel") or [])]
        anchor = " ".join(a.get_text(" ", strip=True).split())[:120]
        if not anchor:
            img = a.find("img")
            anchor = f"[img] {img.get('alt') or ''}".strip() if img else ""
        page.links.append(LinkData(url=target, anchor=anchor, internal=same_site(target, page.final_url), nofollow="nofollow" in rel))

    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        text = " ".join(h.get_text(" ", strip=True).split())[:200]
        lvl = int(h.name[1])
        page.headings.append([lvl, text])
        if lvl == 1:
            page.h1.append(text)
        if text.endswith("?") or re.match(r"^(how|what|why|when|where|who|which|can|does|is|are|should)\b", text, re.I):
            page.question_headings += 1

    if soup.find(attrs={"rel": "author"}) or soup.find(class_=re.compile(r"\bauthor\b", re.I)):
        page.has_author = True
    if soup.find("time"):
        page.has_date = True

    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    body = soup.body or soup
    for tag in body.find_all(["nav", "footer", "header"]):
        tag.decompose()
    text = " ".join(body.get_text(" ", strip=True).split())
    words = re.findall(r"\w+", text.lower())
    page.word_count = len(words)
    page.text_sample = text[:1500]
    page.content_hash = hashlib.sha1(" ".join(words).encode()).hexdigest() if words else None
    page.shingles = shingle_hashes(words)
    page.readability = flesch_reading_ease(text)
    return page

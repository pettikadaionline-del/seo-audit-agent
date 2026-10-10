"""HTML -> PageData extraction (BeautifulSoup + lxml)."""
from __future__ import annotations

import hashlib
import json
import re

from bs4 import BeautifulSoup

from app.crawler.urls import normalize, same_site
from app.models import ImageRef, LinkRef, PageData

WORD_RE = re.compile(r"\w+", re.UNICODE)
QUESTION_RE = re.compile(r"^(what|why|how|when|where|who|which|can|does|do|is|are|should)\b|\?$", re.I)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2},? 20\d{2})\b", re.I)


def parse_html(page: PageData, html: str, origin_host: str) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    base = page.final_url

    html_tag = soup.find("html")
    page.lang = (html_tag.get("lang") or None) if html_tag else None

    if soup.title and soup.title.string is not None:
        page.title = soup.title.get_text(strip=True)
    elif soup.title:
        page.title = ""

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").lower()
        prop = (meta.get("property") or "").lower()
        content = (meta.get("content") or "").strip()
        if name == "description":
            page.meta_description = content
        elif name == "robots":
            page.meta_robots = content.lower()
        elif name == "viewport":
            page.viewport = content
        elif name.startswith("twitter:"):
            page.twitter[name] = content
        elif name in ("author",) or prop == "article:author":
            page.has_author = page.has_author or bool(content)
        if prop.startswith("og:"):
            page.og[prop] = content
        if prop in ("article:published_time", "article:modified_time") or name in ("date", "last-modified"):
            page.has_date = True
        if meta.get("charset"):
            page.charset = meta.get("charset").lower()

    canon = soup.find("link", rel=lambda v: v and "canonical" in [r.lower() for r in (v if isinstance(v, list) else [v])])
    if canon and canon.get("href"):
        page.canonical = normalize(canon["href"], base)

    for alt in soup.find_all("link", rel="alternate", hreflang=True):
        page.hreflang.append({"lang": alt.get("hreflang", ""), "href": alt.get("href", "")})

    # Structured data
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
            page.json_ld.extend(data if isinstance(data, list) else [data])
        except json.JSONDecodeError as exc:
            page.json_ld_errors.append(f"Invalid JSON-LD: {exc.msg} (line {exc.lineno})")
    page.microdata_types = sorted({el.get("itemtype", "") for el in soup.find_all(attrs={"itemtype": True})})

    # Resources (before stripping scripts)
    head = soup.head
    for s in soup.find_all("script"):
        page.scripts_total += 1
        if s.get("src"):
            in_head = head is not None and s in head.find_all("script")
            if in_head and not s.has_attr("async") and not s.has_attr("defer") and s.get("type") != "module":
                page.scripts_blocking += 1
        elif (s.get("type") or "text/javascript") in ("text/javascript", "module", ""):
            page.inline_script_bytes += len(s.get_text() or "")
    page.stylesheets = len(soup.find_all("link", rel="stylesheet"))
    page.inline_style_bytes = sum(len(s.get_text() or "") for s in soup.find_all("style"))

    if page.final_url.startswith("https://"):
        for tag, attr in (("img", "src"), ("script", "src"), ("link", "href"), ("iframe", "src")):
            for el in soup.find_all(tag):
                v = el.get(attr) or ""
                if v.startswith("http://"):
                    page.mixed_content.append(v)

    # Images
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        page.images.append(
            ImageRef(
                src=normalize(src, base) or src,
                alt=img.get("alt"),
                loading=img.get("loading"),
                width=img.get("width"),
                height=img.get("height"),
            )
        )

    # Links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = normalize(href, base)
        if not absolute:
            continue
        rel = [r.lower() for r in (a.get("rel") or [])]
        anchor = a.get_text(" ", strip=True)[:200]
        if not anchor and (img := a.find("img")):
            anchor = (img.get("alt") or "").strip()
        page.links.append(
            LinkRef(
                url=absolute,
                anchor=anchor,
                nofollow="nofollow" in rel or "ugc" in rel or "sponsored" in rel,
                internal=same_site(absolute, origin_host),
            )
        )

    # Headings
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        text = h.get_text(" ", strip=True)
        level = int(h.name[1])
        page.headings.append((level, text[:200]))
        if level == 1:
            page.h1.append(text[:200])
        if QUESTION_RE.search(text):
            page.question_headings += 1

    page.lists_count = len(soup.find_all(["ul", "ol"]))
    page.tables_count = len(soup.find_all("table"))
    if soup.find(attrs={"rel": "author"}) or soup.find(class_=re.compile("author|byline", re.I)):
        page.has_author = True
    if soup.find("time"):
        page.has_date = True
    page.has_faq_pattern = bool(soup.find("details")) or page.question_headings >= 3

    # Visible text
    for el in soup(["script", "style", "noscript", "template", "svg"]):
        el.decompose()
    body = soup.body or soup
    main = body.find("main") or body.find("article") or body
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
    page.word_count = len(WORD_RE.findall(text))
    page.text_sample = text[:1500]
    if not page.has_date and DATE_RE.search(text[:3000]):
        page.has_date = True
    page.content_hash = hashlib.sha1(re.sub(r"\W+", "", text.lower()).encode()).hexdigest() if page.word_count > 20 else None
    return page

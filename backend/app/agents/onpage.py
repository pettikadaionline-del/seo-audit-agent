"""Agent B: on-page SEO (titles, meta descriptions, headings, images, social tags)."""
from __future__ import annotations

from collections import defaultdict

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

TITLE_MIN, TITLE_MAX = 30, 60
DESC_MIN, DESC_MAX = 70, 160


def _dupes(pages: list[PageData], key) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        v = key(p)
        if v:
            groups[v.strip().lower()].append(p.url)
    return {k: v for k, v in groups.items() if len(v) > 1}


class OnPageAgent(AuditAgent):
    category = Category.onpage
    name = "On-Page SEO"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = [p for p in html_pages(pages) if not is_noindex(p)]
        if not ok:
            return out

        # Titles
        missing = [p.url for p in ok if not p.title]
        short = [p.url for p in ok if p.title and len(p.title) < TITLE_MIN]
        long_ = [p.url for p in ok if p.title and len(p.title) > TITLE_MAX]
        if missing:
            out.append(self.issue("title.missing", Severity.critical, "Missing <title> tag",
                "The title is the strongest on-page ranking signal and the headline in search results.",
                "Write a unique, descriptive title (30-60 chars) leading with the primary keyword, ending with the brand.",
                missing, impact=9, effort=Effort.low))
        if short:
            out.append(self.issue("title.short", Severity.medium, "Title tags too short",
                f"Titles under {TITLE_MIN} characters waste SERP space and keyword opportunity.",
                "Expand titles with the primary keyword + a differentiator (e.g. location, benefit, brand).",
                short, impact=5, effort=Effort.low, samples={p.url: p.title for p in ok if p.url in short[:10]}))
        if long_:
            out.append(self.issue("title.long", Severity.low, "Title tags too long",
                f"Titles over {TITLE_MAX} characters are truncated in Google results.",
                "Trim to ~60 characters; keep the main keyword near the start.",
                long_, impact=3, effort=Effort.low))
        dup_titles = _dupes(ok, lambda p: p.title)
        if dup_titles:
            out.append(self.issue("title.duplicate", Severity.high, "Duplicate title tags",
                f"{len(dup_titles)} title(s) are shared by multiple pages, causing keyword cannibalisation.",
                "Give every page a unique title reflecting its specific intent.",
                [u for us in dup_titles.values() for u in us], impact=7, effort=Effort.medium,
                groups={k: v[:5] for k, v in list(dup_titles.items())[:10]}))

        # Meta descriptions
        missing = [p.url for p in ok if not p.meta_description]
        if missing:
            out.append(self.issue("meta_description.missing", Severity.medium, "Missing meta descriptions",
                "Google will auto-generate a snippet, often poorly. A good description lifts click-through rate.",
                "Write a 120-160 char description with the keyword, a benefit and a call to action.",
                missing, impact=5, effort=Effort.low))
        bad_len = [p.url for p in ok if p.meta_description and not DESC_MIN <= len(p.meta_description) <= DESC_MAX]
        if bad_len:
            out.append(self.issue("meta_description.length", Severity.low, "Meta description length outside 70-160 chars",
                "Descriptions that are too short underuse the snippet; too long get truncated.",
                "Aim for 120-160 characters.", bad_len, impact=3, effort=Effort.low))
        dup_desc = _dupes(ok, lambda p: p.meta_description)
        if dup_desc:
            out.append(self.issue("meta_description.duplicate", Severity.medium, "Duplicate meta descriptions",
                "Multiple pages share the same meta description.", "Write unique descriptions per page.",
                [u for us in dup_desc.values() for u in us], impact=4, effort=Effort.medium))

        # Headings
        no_h1 = [p.url for p in ok if not p.h1]
        multi_h1 = [p.url for p in ok if len(p.h1) > 1]
        if no_h1:
            out.append(self.issue("h1.missing", Severity.high, "Missing H1 heading",
                "The H1 tells users and search engines what the page is about.",
                "Add exactly one H1 containing the page's primary keyword.", no_h1, impact=6, effort=Effort.low))
        if multi_h1:
            out.append(self.issue("h1.multiple", Severity.low, "Multiple H1 headings",
                "Several H1s dilute the page's main topic signal.", "Keep one H1; demote the rest to H2/H3.",
                multi_h1, impact=2, effort=Effort.low))
        skipped = []
        for p in ok:
            levels = [lvl for lvl, _ in p.headings]
            if any(b - a > 1 for a, b in zip(levels, levels[1:])):
                skipped.append(p.url)
        if skipped:
            out.append(self.issue("headings.hierarchy", Severity.low, "Heading levels skipped",
                "Heading hierarchy jumps levels (e.g. H2 -> H4), weakening content structure for crawlers and screen readers.",
                "Use sequential heading levels.", skipped, impact=2, effort=Effort.low))
        same = [p.url for p in ok if p.title and p.h1 and p.title.strip().lower() == p.h1[0].strip().lower()]
        if len(same) > 3:
            out.append(self.issue("h1.equals_title", Severity.info, "H1 identical to title",
                "Identical H1 and title miss a chance to target keyword variants.",
                "Use the title for the SERP pitch and the H1 for on-page clarity with a variant phrase.",
                same, impact=1, effort=Effort.low))

        # Images
        img_no_alt: dict[str, int] = {}
        img_no_dims: dict[str, int] = {}
        total_imgs = 0
        for p in ok:
            total_imgs += len(p.images)
            n = sum(1 for i in p.images if i.alt is None or not i.alt.strip())
            if n:
                img_no_alt[p.url] = n
            d = sum(1 for i in p.images if not (i.width and i.height))
            if d:
                img_no_dims[p.url] = d
        if img_no_alt:
            out.append(self.issue("images.alt_missing", Severity.medium, "Images missing alt text",
                f"{sum(img_no_alt.values())} of {total_imgs} images lack alt text. Alt text drives image search traffic and accessibility.",
                "Add short, descriptive alt text (include product names and keywords naturally). Decorative images can use alt=\"\".",
                list(img_no_alt), impact=4, effort=Effort.medium, per_page=dict(list(img_no_alt.items())[:20])))
        if img_no_dims:
            out.append(self.issue("images.no_dimensions", Severity.low, "Images without width/height",
                "Missing dimensions cause layout shift (hurts CLS / Core Web Vitals).",
                "Set width and height attributes (or CSS aspect-ratio) on images.",
                list(img_no_dims), impact=3, effort=Effort.low))

        # Social
        no_og = [p.url for p in ok if not (p.og.get("og:title") and p.og.get("og:image"))]
        if no_og:
            out.append(self.issue("social.open_graph", Severity.low, "Incomplete Open Graph tags",
                "Missing og:title / og:image means poor previews on WhatsApp, Facebook, LinkedIn - key sharing channels.",
                "Add og:title, og:description, og:image (1200x630) and og:url to every page.",
                no_og, impact=3, effort=Effort.low))
        no_tw = [p.url for p in ok if not p.twitter.get("twitter:card")]
        if no_tw and len(no_tw) == len(ok):
            out.append(self.issue("social.twitter_card", Severity.info, "No Twitter/X card tags",
                "No twitter:card meta found.", "Add <meta name=\"twitter:card\" content=\"summary_large_image\">.",
                no_tw[:20], impact=1, effort=Effort.low))

        # URL hygiene
        ugly = [p.url for p in ok if len(p.url) > 115 or any(c.isupper() for c in p.url.split("://", 1)[1]) or "_" in p.url.split("?")[0]]
        if ugly:
            out.append(self.issue("url.structure", Severity.low, "Non-SEO-friendly URLs",
                "URLs that are very long, contain uppercase letters or underscores are harder to read and share.",
                "Use short, lowercase, hyphen-separated, keyword-bearing slugs. 301-redirect old URLs if you change them.",
                ugly, impact=2, effort=Effort.high))
        return out

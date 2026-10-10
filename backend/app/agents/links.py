"""Agent D: internal linking & site architecture."""
from __future__ import annotations

from collections import Counter

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.crawler.urls import normalize
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

GENERIC_ANCHORS = {"click here", "here", "read more", "more", "learn more", "link", "this", "go", "view", "details"}


class LinksAgent(AuditAgent):
    category = Category.links
    name = "Internal Linking"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = html_pages(pages)
        if not ok:
            return out
        crawled = {p.url for p in pages}

        inbound: Counter[str] = Counter()
        for p in ok:
            for target in {l.url for l in p.links if l.internal}:
                if target != p.url:
                    inbound[target] += 1

        # Orphans: in sitemap but no internal links found
        sitemap = {normalize(u) for u in site.sitemap_urls}
        orphans = [p.url for p in ok if p.url in sitemap and inbound[p.url] == 0 and p.depth > 0]
        if orphans:
            out.append(self.issue("orphans", Severity.high, "Orphan pages",
                "These pages are in the sitemap but no crawled page links to them. Orphans get little link equity and are crawled less.",
                "Link to them from relevant category, hub or related-product pages.", orphans, impact=6, effort=Effort.medium))

        weak = [p.url for p in ok if p.depth > 0 and inbound[p.url] == 1 and not is_noindex(p)]
        if len(weak) > 3:
            out.append(self.issue("weak_inbound", Severity.low, "Pages with only one internal link",
                "Pages receiving a single internal link get limited authority.",
                "Add contextual links from related pages and breadcrumbs.", weak, impact=3, effort=Effort.medium))

        deep = [p.url for p in ok if p.depth >= 4]
        if deep:
            out.append(self.issue("depth", Severity.medium, "Pages buried deep in the site (4+ clicks)",
                "Important pages should be reachable within 3 clicks of the homepage.",
                "Flatten navigation: add category hubs, footer links, breadcrumbs, 'popular products' modules.",
                deep, impact=5, effort=Effort.medium))

        dead_ends = [p.url for p in ok if not any(l.internal for l in p.links)]
        if dead_ends:
            out.append(self.issue("dead_ends", Severity.medium, "Pages with no internal outlinks",
                "Dead-end pages trap users and crawlers.", "Add navigation, related items and contextual links.",
                dead_ends, impact=4, effort=Effort.low))

        generic = {}
        empty = {}
        for p in ok:
            g = sum(1 for l in p.links if l.internal and l.anchor.strip().lower() in GENERIC_ANCHORS)
            e = sum(1 for l in p.links if l.internal and not l.anchor.strip())
            if g:
                generic[p.url] = g
            if e:
                empty[p.url] = e
        if generic:
            out.append(self.issue("anchor.generic", Severity.low, "Generic anchor text",
                "'Click here' / 'read more' anchors tell search engines nothing about the target page.",
                "Use descriptive, keyword-relevant anchor text.", list(generic), impact=3, effort=Effort.low,
                per_page=dict(list(generic.items())[:20])))
        if empty:
            out.append(self.issue("anchor.empty", Severity.low, "Links without anchor text",
                "Links with no text and no image alt give no context.", "Add text or alt text to linked images/icons (aria-label).",
                list(empty), impact=2, effort=Effort.low))

        nofollow_internal = sorted({p.url for p in ok for l in p.links if l.internal and l.nofollow})
        if nofollow_internal:
            out.append(self.issue("nofollow_internal", Severity.low, "Internal links marked nofollow",
                "nofollow on internal links wastes link equity.", "Remove rel=nofollow from internal links.",
                nofollow_internal, impact=3, effort=Effort.low))

        broken_targets = {p.url for p in pages if p.status_code >= 400}
        src_broken = sorted({p.url for p in ok for l in p.links if l.internal and l.url in broken_targets})
        if src_broken:
            out.append(self.issue("broken", Severity.high, "Pages linking to broken URLs",
                "These pages contain internal links to 4xx/5xx URLs.", "Update or remove the broken links.",
                src_broken, impact=6, effort=Effort.low))

        uncrawled = len({l.url for p in ok for l in p.links if l.internal} - crawled)
        top = [{"url": u, "inbound": c} for u, c in inbound.most_common(10)]
        self.stats = {"top_linked": top, "internal_links_not_crawled": uncrawled}
        return out

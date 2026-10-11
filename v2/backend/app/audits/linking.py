from collections import Counter, defaultdict

from app.audits.base import AuditContext, Category, Finding, Severity, finding
from app.crawler.parser import GENERIC_ANCHORS

C = Category.linking


def inbound_counts(ctx: AuditContext) -> Counter:
    counts: Counter = Counter()
    for p in ctx.html_pages:
        for target in {l.url for l in p.links if l.internal and l.url != p.url}:
            counts[target] += 1
    return counts


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    pmap = ctx.page_by_url

    broken_by_target: dict[str, list[str]] = defaultdict(list)
    redirect_links: list[tuple[str, dict]] = []
    nofollow_internal: list[tuple[str, dict]] = []
    generic: list[tuple[str, dict]] = []
    broken_ext: list[tuple[str, dict]] = []

    for p in ctx.html_pages:
        for link in p.links:
            if link.internal:
                target = pmap.get(link.url)
                if target and ((target.status and target.status >= 400) or (target.status is None and target.error and not target.error.startswith("blocked"))):
                    broken_by_target[link.url].append(p.url)
                elif target and target.redirect_chain and target.status == 200:
                    redirect_links.append((p.url, {"link": link.url, "redirects_to": target.final_url}))
                if link.nofollow:
                    nofollow_internal.append((p.url, {"link": link.url}))
            else:
                status = ctx.meta.external_link_status.get(link.url, "unchecked")
                if isinstance(status, int) and status >= 400 and status not in (401, 403, 429, 999):
                    broken_ext.append((p.url, {"link": link.url, "status": status}))
            if link.anchor.strip().lower() in GENERIC_ANCHORS:
                generic.append((p.url, {"link": link.url, "anchor": link.anchor}))

    if broken_by_target:
        items = [(src, {"broken_link": tgt, "status": pmap[tgt].status or pmap[tgt].error}) for tgt, srcs in broken_by_target.items() for src in srcs]
        out.append(finding("links.broken_internal", C, "Broken internal links", Severity.high,
                           f"{len(broken_by_target)} internal URL(s) linked from your pages return errors. They waste crawl budget and frustrate visitors.",
                           "Update each link to a working URL, or 301-redirect the broken URL to the most relevant live page.", items, effort=2))
    if broken_ext:
        out.append(finding("links.broken_external", C, "Broken outbound links", Severity.low,
                           "Links to external sites that now return errors (a sample of up to 40 external links was checked).",
                           "Replace or remove dead outbound links.", broken_ext, effort=1))
    if redirect_links:
        out.append(finding("links.internal_redirects", C, "Internal links pointing to redirects", Severity.low,
                           "Linking to URLs that redirect adds a hop for crawlers and users.",
                           "Update internal links to point directly at the final URL.", redirect_links, effort=1))
    if nofollow_internal:
        out.append(finding("links.nofollow_internal", C, "Internal links marked nofollow", Severity.low,
                           "rel=nofollow on internal links stops link equity flowing to your own pages.",
                           "Remove nofollow from internal links (use robots.txt or noindex to keep pages out of search instead).",
                           nofollow_internal, effort=1))
    if len(generic) >= 3:
        out.append(finding("links.generic_anchors", C, "Generic anchor text", Severity.low,
                           "Anchors like 'click here' or 'read more' tell search engines nothing about the target page.",
                           "Use descriptive anchors that name the destination (e.g. 'Tirunelveli halwa gift box' instead of 'shop now').",
                           generic, effort=1))

    inbound = inbound_counts(ctx)
    root = ctx.meta.start_url
    orphans, weak = [], []
    for p in ctx.indexable_pages:
        if p.url == root:
            continue
        n = inbound.get(p.url, 0) + (inbound.get(p.final_url, 0) if p.final_url != p.url else 0)
        if n == 0 and p.depth == -1:
            orphans.append((p.url, {"inbound_internal_links": 0, "found_via": "sitemap"}))
        elif n == 1:
            weak.append((p.url, {"inbound_internal_links": 1}))
    if orphans:
        out.append(finding("links.orphan_pages", C, "Orphan pages (in sitemap, not linked internally)", Severity.medium,
                           "These pages are in the sitemap but no crawled page links to them, so they receive no internal link equity. "
                           "Note: only pages within the crawl limit were checked for links.",
                           "Link to each page from a relevant category page, hub page or the navigation, or remove it from the sitemap if obsolete.",
                           orphans, effort=2, confidence="medium"))
    if weak and len(ctx.indexable_pages) >= 10:
        out.append(finding("links.weak_internal_linking", C, "Pages with only one internal link", Severity.low,
                           "Pages linked from a single place are harder to discover and signal low importance.",
                           "Add contextual links from related products, posts and category pages.", weak, effort=2, confidence="medium"))

    deep = [(p.url, {"click_depth": p.depth}) for p in ctx.indexable_pages if p.depth > 3]
    if deep:
        out.append(finding("links.deep_pages", C, "Pages more than 3 clicks from the homepage", Severity.medium,
                           "Deeply buried pages are crawled less often and tend to rank worse.",
                           "Flatten the structure: link important pages from the homepage, main navigation or hub pages.", deep, effort=3))

    no_out = [(p.url, {"internal_links": 0}) for p in ctx.indexable_pages if not any(l.internal for l in p.links)]
    if no_out:
        out.append(finding("links.dead_end", C, "Dead-end pages (no internal links)", Severity.medium,
                           "Pages with no internal links trap users and crawlers.",
                           "Add navigation and related-content links.", no_out, effort=1))
    return out

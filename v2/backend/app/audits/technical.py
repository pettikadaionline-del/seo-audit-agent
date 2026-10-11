from collections import defaultdict
from urllib.parse import urlsplit

from app.audits.base import AuditContext, Category, Finding, Severity, finding

C = Category.technical


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    meta = ctx.meta
    pages = ctx.pages

    # --- Site-level -----------------------------------------------------------
    if meta.homepage_status != 200:
        out.append(finding(
            "tech.homepage_unreachable", C, "Homepage does not return HTTP 200", Severity.critical,
            f"The start URL returned status {meta.homepage_status or 'no response'}.",
            "Make sure the homepage responds with 200 OK to crawlers; check server errors, firewalls and bot protection.",
            [(meta.start_url, {"status": meta.homepage_status})], site_level=True, effort=2,
        ))

    if not meta.https:
        out.append(finding(
            "tech.no_https", C, "Site is not served over HTTPS", Severity.critical,
            "The audited URL uses plain HTTP. HTTPS is a confirmed (lightweight) ranking signal and browsers mark HTTP pages as 'Not secure'.",
            "Install a TLS certificate (free via Let's Encrypt or your host/CDN) and 301-redirect all HTTP URLs to HTTPS.",
            [(meta.start_url, {"scheme": "http"})], site_level=True, effort=2,
        ))
    elif meta.http_redirects_to_https is False:
        out.append(finding(
            "tech.http_not_redirected", C, "HTTP version does not redirect to HTTPS", Severity.high,
            "Requesting the http:// version did not end on https://, so two versions of the site can be indexed.",
            "Add a server-wide 301 redirect from http:// to https://.",
            [(meta.start_url.replace("https://", "http://", 1), {"redirects_to_https": False})], site_level=True, effort=1,
        ))

    if meta.https and ctx.html_pages and not any(p.hsts for p in ctx.html_pages):
        out.append(finding(
            "tech.no_hsts", C, "No HSTS header", Severity.low,
            "No crawled page sent a Strict-Transport-Security header.",
            "Add `Strict-Transport-Security: max-age=31536000; includeSubDomains` once HTTPS works everywhere.",
            [(meta.start_url, {"hsts": False})], site_level=True, effort=1,
        ))

    robots = meta.robots
    if robots and not robots.exists:
        out.append(finding(
            "tech.no_robots_txt", C, "robots.txt is missing", Severity.medium,
            f"{robots.url} returned {robots.status or 'no response'}. Crawlers will assume everything is allowed, and you lose a place to declare sitemaps.",
            "Create a robots.txt that allows crawling of public pages and lists your sitemap, e.g. `User-agent: *` / `Allow: /` / `Sitemap: https://example.com/sitemap.xml`.",
            [(robots.url, {"status": robots.status})], site_level=True, effort=1,
        ))
    elif robots and not robots.allowed("Googlebot", meta.start_url):
        out.append(finding(
            "tech.robots_blocks_homepage", C, "robots.txt blocks Googlebot from the homepage", Severity.critical,
            "The robots.txt rules disallow Googlebot from crawling the start URL.",
            "Remove or narrow the Disallow rule that matches the homepage.",
            [(robots.url, {"googlebot_allowed": False})], site_level=True, effort=1,
        ))

    sm = meta.sitemap
    if sm is not None:
        if not sm.found:
            out.append(finding(
                "tech.no_sitemap", C, "No valid XML sitemap found", Severity.medium,
                "No sitemap was declared in robots.txt or found at /sitemap.xml" + (f"; errors: {sm.errors[:3]}" if sm.errors else "."),
                "Generate an XML sitemap of indexable, canonical URLs (most CMSs and site builders do this automatically), reference it in robots.txt and submit it in Google Search Console.",
                [(e["url"], {"error": e["error"]}) for e in sm.errors] or [(meta.root + "/sitemap.xml", {"found": False})],
                site_level=True, effort=1,
            ))
        elif sm.errors:
            out.append(finding(
                "tech.sitemap_errors", C, "Some sitemap files could not be read", Severity.medium,
                "One or more sitemap files referenced by the site returned errors or invalid XML.",
                "Fix or remove the broken sitemap references.",
                [(e["url"], {"error": e["error"]}) for e in sm.errors], site_level=True, effort=1,
            ))
        if sm.found:
            bad = [(p.url, {"status": p.status, "indexable": p.indexable}) for p in pages if p.in_sitemap and (p.status != 200 or not p.indexable or p.redirect_chain)]
            if bad:
                out.append(finding(
                    "tech.sitemap_non_indexable", C, "Sitemap lists non-indexable, redirected or broken URLs", Severity.medium,
                    "Sitemaps should only contain canonical URLs that return 200 and are indexable; otherwise search engines trust the sitemap less.",
                    "Remove redirected, noindex and error URLs from the sitemap (or fix the pages).",
                    bad, effort=2,
                ))

    if meta.blocked_by_robots:
        out.append(finding(
            "tech.blocked_by_robots", C, "Linked pages are blocked by robots.txt", Severity.info,
            "These internally linked URLs were not crawled because robots.txt disallows them. That may be intentional (cart, account pages).",
            "Confirm each blocked path is meant to be private. If a page should rank, remove its Disallow rule.",
            [(u, {"blocked": True}) for u in meta.blocked_by_robots], effort=1, confidence="medium",
        ))

    # --- Page-level -----------------------------------------------------------
    # 4xx URLs are reported once, from the side you fix: links.broken_internal (linked pages)
    # and tech.sitemap_non_indexable (sitemap entries).
    errors_5xx = [(p.url, {"status": p.status}) for p in pages if p.status and p.status >= 500]
    failed = [(p.url, {"error": p.error}) for p in pages if p.status is None and p.error and not p.error.startswith("blocked")]
    if errors_5xx:
        out.append(finding("tech.server_errors", C, "Pages returning 5xx server errors", Severity.critical,
                           "Server errors stop pages from being indexed and, if persistent, cause Google to drop them.",
                           "Check server/application logs for these URLs and fix the underlying errors.", errors_5xx, effort=3))
    if failed:
        out.append(finding("tech.fetch_failures", C, "Pages that could not be fetched", Severity.medium,
                           "Requests timed out or failed at the network level.",
                           "Check hosting stability, timeouts and any bot-protection rules that may block crawlers.", failed, effort=3, confidence="medium"))

    chains = [(p.url, {"hops": len(p.redirect_chain), "chain": [c[0] for c in p.redirect_chain] + [p.final_url]}) for p in pages if len(p.redirect_chain) >= 2]
    if chains:
        out.append(finding("tech.redirect_chains", C, "Redirect chains (2+ hops)", Severity.medium,
                           "Each extra redirect hop wastes crawl budget and adds latency.",
                           "Point redirects (and internal links) directly at the final destination URL.", chains, effort=2))

    noindex = [(p.url, {"meta_robots": p.meta_robots, "x_robots_tag": p.x_robots_tag}) for p in ctx.html_pages if not p.indexable]
    if noindex:
        out.append(finding("tech.noindex", C, "Pages excluded from indexing (noindex)", Severity.medium,
                           "These pages carry a noindex directive. Check none of them are pages you want to rank.",
                           "Remove `noindex` from pages that should appear in search; keep it only on thank-you, cart, account and filter pages.",
                           noindex, effort=1, confidence="medium"))

    canon_missing, canon_other, canon_broken = [], [], []
    page_map = ctx.page_by_url
    for p in ctx.html_pages:
        if not p.indexable:
            continue
        if not p.canonical:
            canon_missing.append((p.url, {"canonical": None}))
            continue
        if p.canonical != p.final_url:
            target = page_map.get(p.canonical)
            if target and (target.status != 200 or target.redirect_chain):
                canon_broken.append((p.url, {"canonical": p.canonical, "target_status": target.status}))
            elif urlsplit(p.canonical).hostname != urlsplit(p.final_url).hostname:
                canon_other.append((p.url, {"canonical": p.canonical, "note": "cross-domain"}))
    if canon_missing:
        out.append(finding("tech.canonical_missing", C, "Missing canonical tags", Severity.low,
                           "Without a self-referencing canonical, URL variants (tracking parameters, trailing slashes) can split ranking signals.",
                           'Add `<link rel="canonical" href="...">` pointing to the preferred URL on every indexable page.', canon_missing, effort=1))
    if canon_broken:
        out.append(finding("tech.canonical_broken", C, "Canonical points to a redirect or error page", Severity.high,
                           "Search engines may ignore a canonical that does not resolve to a 200 page.",
                           "Update canonicals to point at the final, live URL.", canon_broken, effort=1))
    if canon_other:
        out.append(finding("tech.canonical_cross_domain", C, "Canonical points to another domain", Severity.medium,
                           "A cross-domain canonical asks search engines to index the other domain instead of this page.",
                           "Confirm this is intentional (syndicated content). Otherwise make the canonical self-referencing.", canon_other, effort=1, confidence="medium"))

    by_hash: dict[str, list[str]] = defaultdict(list)
    for p in ctx.indexable_pages:
        if p.content_hash:
            by_hash[p.content_hash].append(p.url)
    dups = [(u, {"duplicate_group": i, "group_size": len(g)}) for i, g in enumerate(v for v in by_hash.values() if len(v) > 1) for u in g]
    if dups:
        out.append(finding("tech.duplicate_pages", C, "Exact duplicate pages without consolidation", Severity.high,
                           "Multiple indexable URLs serve identical body content, so they compete with each other.",
                           "Pick one URL per group; 301-redirect or canonicalise the rest to it.", dups, effort=2))

    no_viewport = [(p.url, {"viewport": False}) for p in ctx.html_pages if not p.viewport]
    if no_viewport:
        out.append(finding("tech.no_viewport", C, "Missing mobile viewport tag", Severity.high,
                           "Google indexes the mobile version of pages. Without a viewport meta tag, pages render as desktop pages on phones.",
                           'Add `<meta name="viewport" content="width=device-width, initial-scale=1">` to the page template.', no_viewport, effort=1))

    no_lang = [(p.url, {"lang": None}) for p in ctx.html_pages if not p.lang]
    if no_lang:
        out.append(finding("tech.no_lang", C, "Missing `lang` attribute on <html>", Severity.low,
                           "The lang attribute helps search engines and screen readers pick the right language.",
                           'Set `<html lang="en">` (or the correct language code) in the template.', no_lang, effort=1))

    mixed = [(p.url, {"insecure_resources": p.mixed_content[:5]}) for p in ctx.html_pages if p.mixed_content]
    if mixed:
        out.append(finding("tech.mixed_content", C, "Mixed content (HTTP resources on HTTPS pages)", Severity.medium,
                           "Browsers block or warn about insecure scripts, styles and images on HTTPS pages.",
                           "Change these resource URLs to https:// or protocol-relative paths.", mixed, effort=1))

    ugly = []
    for p in ctx.html_pages:
        path = urlsplit(p.url).path + ("?" + urlsplit(p.url).query if urlsplit(p.url).query else "")
        reasons = []
        if len(p.url) > 115:
            reasons.append("longer than 115 characters")
        if any(c.isupper() for c in urlsplit(p.url).path):
            reasons.append("contains uppercase letters")
        if "_" in urlsplit(p.url).path:
            reasons.append("uses underscores instead of hyphens")
        if urlsplit(p.url).query.count("&") >= 2:
            reasons.append("has 3+ query parameters")
        if reasons:
            ugly.append((p.url, {"path": path[:120], "issues": reasons}))
    if ugly:
        out.append(finding("tech.url_hygiene", C, "URL structure issues", Severity.low,
                           "Short, lowercase, hyphenated URLs are easier to share and less likely to create duplicates.",
                           "Use lowercase, hyphen-separated, descriptive slugs for new pages. Only change existing URLs with 301 redirects, and only if the gain is worth it.",
                           ugly, effort=3, confidence="medium"))

    hreflang_issues = []
    for p in ctx.html_pages:
        if not p.hreflang:
            continue
        langs = [h["lang"].lower() for h in p.hreflang]
        if p.final_url not in [h["href"] for h in p.hreflang]:
            hreflang_issues.append((p.url, {"issue": "no self-referencing hreflang", "langs": langs}))
        if "x-default" not in langs:
            hreflang_issues.append((p.url, {"issue": "no x-default", "langs": langs}))
    if hreflang_issues:
        out.append(finding("tech.hreflang", C, "hreflang implementation issues", Severity.medium,
                           "Each page in an hreflang set should reference itself and ideally include an x-default.",
                           "Add a self-referencing hreflang entry and an x-default entry to every localized page.",
                           hreflang_issues, effort=2))
    return out

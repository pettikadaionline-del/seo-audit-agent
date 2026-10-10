"""Agent A: technical SEO (crawlability, indexability, status codes, security)."""
from __future__ import annotations

from collections import defaultdict

from app.agents.base import AuditAgent, html_pages, is_noindex
from app.crawler.urls import normalize
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext


class TechnicalAgent(AuditAgent):
    category = Category.technical
    name = "Technical SEO"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = html_pages(pages)

        if not site.https:
            out.append(self.issue("https.missing", Severity.critical, "Site is not served over HTTPS",
                "The start URL uses plain HTTP. HTTPS is a ranking signal and browsers flag HTTP pages as 'Not secure'.",
                "Install a TLS certificate (free via Let's Encrypt / Cloudflare) and 301-redirect all HTTP URLs to HTTPS.",
                [site.start_url], impact=9, effort=Effort.medium))
        elif site.http_redirects_to_https is False:
            out.append(self.issue("https.no_redirect", Severity.high, "HTTP version does not redirect to HTTPS",
                "Requests to the http:// version are not redirected, creating duplicate, insecure copies of pages.",
                "Add a site-wide 301 redirect from http:// to https://.",
                [site.start_url.replace("https://", "http://", 1)], impact=7, effort=Effort.low))

        if site.www_consistent is False:
            out.append(self.issue("host.inconsistent", Severity.medium, "www and non-www versions both resolve",
                "The alternate hostname (www vs non-www) serves content instead of redirecting to the canonical host.",
                "301-redirect the alternate hostname to your preferred host and keep canonicals consistent.",
                [site.origin], impact=6, effort=Effort.low))

        if not site.robots_txt_found:
            out.append(self.issue("robots.missing", Severity.low, "robots.txt not found",
                "No robots.txt was found. Crawlers will assume everything is allowed and cannot discover your sitemap from it.",
                "Add /robots.txt with a 'Sitemap:' line pointing to your XML sitemap.",
                [f"{site.origin}/robots.txt"], impact=3, effort=Effort.low))
        elif site.robots_disallow_all:
            out.append(self.issue("robots.disallow_all", Severity.critical, "robots.txt blocks Googlebot from the homepage",
                "robots.txt disallows crawling of '/' for Googlebot. The site cannot be crawled or ranked.",
                "Remove the blanket 'Disallow: /' rule unless the site is intentionally private.",
                [f"{site.origin}/robots.txt"], impact=10, effort=Effort.low))

        if not site.sitemap_urls:
            out.append(self.issue("sitemap.missing", Severity.medium, "No valid XML sitemap found",
                "No XML sitemap could be loaded. Sitemaps help search engines discover and prioritise pages.",
                "Generate an XML sitemap (most CMSs do this automatically), submit it in Google Search Console and reference it in robots.txt.",
                [site.origin], impact=5, effort=Effort.low, errors=site.sitemap_errors))
        elif site.sitemap_errors:
            out.append(self.issue("sitemap.errors", Severity.low, "Some sitemaps failed to load",
                "One or more sitemap files referenced could not be fetched or parsed.",
                "Fix or remove broken sitemap references.", [], impact=3, effort=Effort.low, errors=site.sitemap_errors[:10]))
        if site.sitemaps_declared == [] and site.sitemap_urls and site.robots_txt_found:
            out.append(self.issue("sitemap.not_in_robots", Severity.low, "Sitemap not referenced in robots.txt",
                "A sitemap exists but robots.txt does not declare it.", "Add 'Sitemap: <url>' to robots.txt.",
                [f"{site.origin}/robots.txt"], impact=2, effort=Effort.low))

        # Status codes
        broken = [p for p in pages if p.status_code >= 400]
        server = [p.url for p in broken if p.status_code >= 500]
        client = [p.url for p in broken if 400 <= p.status_code < 500]
        failed = [p.url for p in pages if p.status_code == 0 and p.error and not p.blocked_by_robots]
        if server:
            out.append(self.issue("status.5xx", Severity.critical, "Pages returning server errors (5xx)",
                f"{len(server)} crawled URL(s) returned a 5xx status.", "Investigate server logs; 5xx errors cause de-indexing if persistent.",
                server, impact=9, effort=Effort.medium))
        if client:
            out.append(self.issue("status.4xx", Severity.high, "Broken internal URLs (4xx)",
                f"{len(client)} internally linked URL(s) return a 4xx status.",
                "Fix or remove links pointing to these URLs, or 301-redirect them to the most relevant live page.",
                client, impact=7, effort=Effort.low))
        if failed:
            out.append(self.issue("status.unreachable", Severity.high, "URLs that could not be fetched",
                "Requests timed out or failed at the network level.", "Check server capacity, firewall/WAF rules and DNS.",
                failed, impact=6, effort=Effort.medium, errors={p.url: p.error for p in pages if p.url in failed[:20]}))
        if site.sitemap_urls:
            sm = {normalize(u) for u in site.sitemap_urls}
            bad_in_sitemap = [p.url for p in pages if p.url in sm and (p.status_code >= 300 or is_noindex(p))]
            if bad_in_sitemap:
                out.append(self.issue("sitemap.dirty", Severity.medium, "Sitemap lists non-indexable URLs",
                    "The sitemap contains URLs that redirect, error or are noindex. This wastes crawl budget and sends mixed signals.",
                    "Only list canonical, 200-status, indexable URLs in the sitemap.", bad_in_sitemap, impact=5, effort=Effort.low))

        # Redirects
        chains = [p.url for p in pages if len(p.redirect_chain) >= 2]
        if chains:
            out.append(self.issue("redirect.chain", Severity.medium, "Redirect chains",
                "These URLs pass through 2+ redirects before resolving, wasting crawl budget and diluting link equity.",
                "Point links and redirects directly at the final destination URL.", chains, impact=4, effort=Effort.low))
        internal_redirect_targets = {p.url for p in pages if p.redirect_chain}
        linking = sorted({p.url for p in ok for l in p.links if l.internal and l.url in internal_redirect_targets})
        if linking:
            out.append(self.issue("redirect.internal_links", Severity.low, "Internal links pointing at redirects",
                "Pages link to URLs that redirect.", "Update internal links to point to final URLs.", linking,
                impact=3, effort=Effort.low))

        # Indexability
        noindex = [p.url for p in ok if is_noindex(p)]
        if noindex:
            sev = Severity.critical if site.start_url in noindex or (pages and pages[0].url in noindex) else Severity.medium
            out.append(self.issue("index.noindex", sev, "Pages marked noindex",
                f"{len(noindex)} page(s) carry a noindex directive (meta robots or X-Robots-Tag). Verify this is intentional.",
                "Remove noindex from pages that should rank.", noindex, impact=8 if sev == Severity.critical else 5, effort=Effort.low))
        blocked = [p.url for p in pages if p.blocked_by_robots]
        if blocked:
            out.append(self.issue("robots.blocked_pages", Severity.info, "Internally linked URLs blocked by robots.txt",
                "These URLs were discovered but disallowed by robots.txt and not crawled.",
                "Confirm these should be blocked. Blocked URLs can still be indexed (without content) if linked.",
                blocked, impact=2, effort=Effort.low))

        # Canonicals
        missing_canon = [p.url for p in ok if not p.canonical and not is_noindex(p)]
        if missing_canon:
            out.append(self.issue("canonical.missing", Severity.medium, "Missing canonical tags",
                "Pages without a rel=canonical are more exposed to duplicate-content issues from URL parameters.",
                "Add a self-referencing <link rel=\"canonical\"> to every indexable page.", missing_canon, impact=5, effort=Effort.low))
        by_url = {p.url: p for p in pages}
        canon_bad = []
        for p in ok:
            if p.canonical and p.canonical != p.final_url:
                tgt = by_url.get(p.canonical)
                if tgt and (tgt.status_code >= 300 or is_noindex(tgt)):
                    canon_bad.append(p.url)
        if canon_bad:
            out.append(self.issue("canonical.bad_target", Severity.high, "Canonical points to non-indexable URL",
                "Canonical tags reference URLs that redirect, error or are noindex.", "Point canonicals to a live, indexable 200 URL.",
                canon_bad, impact=7, effort=Effort.low))
        canon_http = [p.url for p in ok if site.https and p.canonical and p.canonical.startswith("http://")]
        if canon_http:
            out.append(self.issue("canonical.http", Severity.medium, "Canonical tags point to HTTP URLs",
                "HTTPS pages declare an http:// canonical.", "Update canonicals to the https:// version.", canon_http,
                impact=5, effort=Effort.low))

        # Mobile / HTML basics
        no_viewport = [p.url for p in ok if not p.viewport]
        if no_viewport:
            out.append(self.issue("mobile.viewport", Severity.high, "Missing mobile viewport meta tag",
                "Without <meta name=\"viewport\">, pages render at desktop width on phones. Google uses mobile-first indexing.",
                "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">.", no_viewport, impact=7, effort=Effort.low))
        no_lang = [p.url for p in ok if not p.lang]
        if no_lang:
            out.append(self.issue("html.lang", Severity.low, "Missing <html lang> attribute",
                "The page language is not declared, which hurts accessibility and language targeting.",
                "Set e.g. <html lang=\"en\"> (or en-IN, ta etc.).", no_lang, impact=2, effort=Effort.low))

        mixed = [p.url for p in ok if p.mixed_content]
        if mixed:
            out.append(self.issue("security.mixed_content", Severity.high, "Mixed content on HTTPS pages",
                "HTTPS pages load resources over HTTP; browsers block or warn on these.", "Serve all assets over HTTPS.",
                mixed, impact=6, effort=Effort.low, sample={p.url: p.mixed_content[:3] for p in ok if p.mixed_content}))
        if site.https and ok and not any("strict-transport-security" in p.headers for p in ok[:5]):
            out.append(self.issue("security.hsts", Severity.low, "No HSTS header",
                "Strict-Transport-Security is not set.", "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains'.",
                [ok[0].url], impact=2, effort=Effort.low))

        # hreflang validation
        bad_hreflang: dict[str, list[str]] = defaultdict(list)
        for p in ok:
            if not p.hreflang:
                continue
            langs = [h["lang"].lower() for h in p.hreflang]
            if "x-default" not in langs:
                bad_hreflang["no_x_default"].append(p.url)
            if not any(h["href"].rstrip("/") == p.final_url.rstrip("/") for h in p.hreflang):
                bad_hreflang["no_self"].append(p.url)
        if bad_hreflang:
            out.append(self.issue("hreflang.incomplete", Severity.medium, "Incomplete hreflang annotations",
                "hreflang sets are missing a self-reference and/or x-default.",
                "Each page should list itself plus all language alternates and an x-default. Important for export/multi-country targeting.",
                [u for v in bad_hreflang.values() for u in v], impact=5, effort=Effort.medium,
                breakdown={k: len(v) for k, v in bad_hreflang.items()}))
        return out

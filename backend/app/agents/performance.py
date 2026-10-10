"""Agent E: performance.

Two layers:
1. Crawl-derived signals for every page (server response time, HTML weight,
   render-blocking scripts, compression, caching, lazy-loading).
2. Optional lab Core Web Vitals from Google PageSpeed Insights for the
   homepage (needs SEO_PAGESPEED_API_KEY; fetched by the orchestrator).
"""
from __future__ import annotations

import statistics

from app.agents.base import AuditAgent, html_pages
from app.models import Category, Effort, Issue, PageData, Severity, SiteContext

SLOW_MS = 800
VERY_SLOW_MS = 1800
HEAVY_HTML = 500 * 1024


class PerformanceAgent(AuditAgent):
    category = Category.performance
    name = "Performance"

    def run(self, pages: list[PageData], site: SiteContext) -> list[Issue]:
        out: list[Issue] = []
        ok = html_pages(pages)
        if not ok:
            return out

        times = [p.response_time_ms for p in ok]
        median = statistics.median(times)
        very_slow = [p.url for p in ok if p.response_time_ms > VERY_SLOW_MS]
        slow = [p.url for p in ok if SLOW_MS < p.response_time_ms <= VERY_SLOW_MS]
        if very_slow:
            out.append(self.issue("server.very_slow", Severity.high, f"Very slow server response (>{VERY_SLOW_MS} ms)",
                "Slow HTML delivery delays every downstream metric (LCP, FCP). Measured from the crawler, includes network latency.",
                "Enable full-page caching / CDN (Cloudflare free tier works), upgrade hosting, reduce server-side work.",
                very_slow, impact=7, effort=Effort.medium, median_ms=median))
        if slow:
            out.append(self.issue("server.slow", Severity.medium, f"Slow server response ({SLOW_MS}-{VERY_SLOW_MS} ms)",
                "Response times above ~800 ms make 'good' LCP hard to achieve.",
                "Add caching and a CDN; check slow database queries and heavy plugins/apps.",
                slow, impact=5, effort=Effort.medium, median_ms=median))

        heavy = [p.url for p in ok if p.html_bytes > HEAVY_HTML]
        if heavy:
            out.append(self.issue("html.heavy", Severity.medium, "Large HTML documents (>500 KB)",
                "Large HTML increases download and parse time, especially on mobile networks.",
                "Remove inlined data blobs, unused markup and large inline scripts/styles.",
                heavy, impact=4, effort=Effort.medium, sizes_kb={p.url: round(p.html_bytes / 1024) for p in ok if p.url in heavy[:20]}))

        blocking = [p.url for p in ok if p.scripts_blocking >= 3]
        if blocking:
            out.append(self.issue("render_blocking", Severity.medium, "Render-blocking scripts in <head>",
                "3+ synchronous external scripts in <head> block first paint.",
                "Add defer/async to non-critical scripts; load third-party widgets after interaction.",
                blocking, impact=5, effort=Effort.medium))
        many_scripts = [p.url for p in ok if p.scripts_total > 40]
        if many_scripts:
            out.append(self.issue("scripts.many", Severity.low, "High number of scripts (>40)",
                "Lots of scripts (often from apps/plugins/trackers) bloat JS execution time and hurt INP.",
                "Audit apps/plugins and tag manager; remove unused ones.", many_scripts, impact=4, effort=Effort.medium))

        uncompressed = [p.url for p in ok if p.html_bytes > 10_000 and not p.headers.get("content-encoding")]
        if uncompressed:
            out.append(self.issue("compression", Severity.medium, "HTML served without compression",
                "No gzip/brotli Content-Encoding on HTML responses.", "Enable gzip or brotli on the server/CDN.",
                uncompressed, impact=5, effort=Effort.low))

        lazy_missing = []
        for p in ok:
            imgs = p.images[3:]  # first images are likely above the fold
            if len(imgs) >= 5 and sum(1 for i in imgs if (i.loading or "").lower() != "lazy") / len(imgs) > 0.7:
                lazy_missing.append(p.url)
        if lazy_missing:
            out.append(self.issue("images.lazy", Severity.low, "Below-the-fold images not lazy-loaded",
                "Most images below the fold load eagerly, competing with critical resources.",
                "Add loading=\"lazy\" to below-the-fold images (never to the LCP/hero image).",
                lazy_missing, impact=3, effort=Effort.low))
        legacy_imgs = []
        for p in ok:
            srcs = [i.src.lower().split("?")[0] for i in p.images]
            if srcs and sum(1 for s in srcs if s.endswith((".jpg", ".jpeg", ".png"))) / len(srcs) > 0.6 and len(srcs) >= 4:
                legacy_imgs.append(p.url)
        if legacy_imgs:
            out.append(self.issue("images.format", Severity.low, "Images not in next-gen formats",
                "Most images are JPEG/PNG. WebP/AVIF are typically 25-50% smaller.",
                "Serve WebP/AVIF (Shopify/Cloudflare can do this automatically).", legacy_imgs, impact=3, effort=Effort.low))

        no_cache = [p.url for p in ok if "cache-control" not in p.headers]
        if len(no_cache) == len(ok) and len(ok) > 1:
            out.append(self.issue("caching", Severity.low, "No Cache-Control headers on HTML",
                "No caching policy is declared for HTML responses.", "Set Cache-Control (and use a CDN) for cacheable pages.",
                no_cache[:20], impact=2, effort=Effort.low))

        out.extend(self._pagespeed(site))
        return out

    def _pagespeed(self, site: SiteContext) -> list[Issue]:
        ps = site.pagespeed
        if not ps or ps.get("error"):
            return []
        out = []
        score = ps.get("performance_score")
        metrics = ps.get("metrics", {})
        if score is not None and score < 50:
            sev, impact = Severity.high, 8
        elif score is not None and score < 90:
            sev, impact = Severity.medium, 5
        else:
            sev = None
        if score is not None and sev:
            out.append(self.issue("cwv.lab_score", sev, f"Mobile Lighthouse performance score {score}/100",
                "Lab data from Google PageSpeed Insights (mobile).",
                "Prioritise: reduce LCP (optimise hero image, server time), cut JS (INP/TBT), reserve space for media (CLS).",
                [site.start_url], impact=impact, effort=Effort.medium, metrics=metrics))
        lcp = metrics.get("lcp_ms")
        if lcp and lcp > 2500:
            out.append(self.issue("cwv.lcp", Severity.high if lcp > 4000 else Severity.medium,
                f"Largest Contentful Paint {lcp / 1000:.1f}s (target <2.5s)",
                "LCP measures how quickly the main content appears.",
                "Preload and compress the hero image, serve via CDN, avoid lazy-loading it, reduce render-blocking CSS/JS.",
                [site.start_url], impact=7, effort=Effort.medium))
        cls = metrics.get("cls")
        if cls is not None and cls > 0.1:
            out.append(self.issue("cwv.cls", Severity.medium, f"Cumulative Layout Shift {cls:.2f} (target <0.1)",
                "Elements move while loading.", "Set image/video dimensions, reserve ad/embed slots, avoid late-injected banners.",
                [site.start_url], impact=5, effort=Effort.low))
        return out

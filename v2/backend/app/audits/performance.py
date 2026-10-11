"""Performance audit.

Two evidence sources, never mixed:
- Crawler measurements (TTFB, HTML weight, compression, render-blocking tags). These are
  server-side measurements from the audit server, not what users experience.
- PageSpeed Insights: CrUX field data (real users, p75) and a Lighthouse lab run.
"""

from statistics import median

from app.audits.base import AuditContext, Category, Finding, Severity, finding

C = Category.performance

THRESHOLDS = {"LCP": (2500, 4000), "INP": (200, 500), "CLS": (0.1, 0.25)}


def run(ctx: AuditContext) -> list[Finding]:
    out: list[Finding] = []
    pages = ctx.html_pages
    if not pages:
        return out

    slow = [(p.url, {"ttfb_ms": p.ttfb_ms}) for p in pages if p.ttfb_ms and p.ttfb_ms > 800]
    if slow:
        med = median(p.ttfb_ms for p in pages if p.ttfb_ms)
        out.append(finding("perf.slow_ttfb", C, "Slow server response (TTFB > 800 ms)", Severity.high if med > 1500 else Severity.medium,
                           f"Measured by the audit crawler (median {round(med)} ms across pages). Includes network distance from the audit server, so treat as indicative. "
                           "Slow TTFB delays every other metric, including LCP.",
                           "Enable full-page caching or a CDN, upgrade hosting, and cut slow database queries/apps. Remove unused plugins/apps that add server-side work.",
                           slow, effort=3, confidence="medium"))

    heavy = [(p.url, {"html_kb": round(p.html_bytes / 1024)}) for p in pages if p.html_bytes > 300_000]
    if heavy:
        out.append(finding("perf.heavy_html", C, "Large HTML documents (> 300 KB)", Severity.medium,
                           "Big HTML usually means inlined JSON, SVGs or app snippets; it slows parsing on mid-range phones.",
                           "Remove inlined data and unused app snippets; lazy-load below-the-fold sections.", heavy, effort=3))

    uncompressed = [(p.url, {"content_encoding": None, "html_kb": round(p.html_bytes / 1024)}) for p in pages if not p.compressed and p.html_bytes > 10_000]
    if uncompressed:
        out.append(finding("perf.no_compression", C, "HTML served without compression", Severity.medium,
                           "No gzip/brotli Content-Encoding was returned. Compression typically cuts HTML transfer size by 70%+.",
                           "Enable gzip or brotli on the web server or CDN (often a single toggle).", uncompressed, effort=1))

    blocking = [(p.url, {"render_blocking_scripts": p.render_blocking_scripts}) for p in pages if p.render_blocking_scripts >= 3]
    if blocking:
        out.append(finding("perf.render_blocking", C, "Render-blocking scripts in <head>", Severity.medium,
                           "Synchronous scripts in the head block the first paint until they download and execute.",
                           "Add `defer` (or `async` for independent scripts) and move non-critical scripts to the end of the body.",
                           blocking, effort=2))

    many_scripts = [(p.url, {"external_scripts": p.scripts_total}) for p in pages if p.scripts_total > 25]
    if many_scripts:
        out.append(finding("perf.too_many_scripts", C, "Very high number of external scripts", Severity.medium,
                           "Each script costs network and main-thread time, which hurts INP on mobile.",
                           "Audit third-party tags/apps; remove unused ones and load the rest via a tag manager with triggers.",
                           many_scripts, effort=3))

    cls_risk = []
    lazy_missing = []
    for p in pages:
        imgs = [i for i in p.images if i.src]
        no_dims = [i.src for i in imgs if not i.has_dimensions]
        if len(no_dims) >= 3:
            cls_risk.append((p.url, {"images_without_dimensions": len(no_dims), "examples": no_dims[:3]}))
        if len(imgs) > 8 and not any(i.lazy for i in imgs):
            lazy_missing.append((p.url, {"images": len(imgs), "lazy_loaded": 0}))
    if cls_risk:
        out.append(finding("perf.image_dimensions", C, "Images without width/height (layout shift risk)", Severity.low,
                           "Images without explicit dimensions can shift the layout as they load, hurting CLS.",
                           "Set width and height attributes (or CSS aspect-ratio) on images.", cls_risk, effort=2))
    if lazy_missing:
        out.append(finding("perf.no_lazy_loading", C, "Image-heavy pages without lazy loading", Severity.low,
                           "Every image loads up front, competing with the hero image for bandwidth.",
                           'Add `loading="lazy"` to below-the-fold images. Never lazy-load the LCP/hero image.', lazy_missing, effort=1))

    no_cache = [(p.url, {"cache_control": p.cache_control}) for p in pages if p.cache_control and "no-store" in p.cache_control.lower()]
    if no_cache and len(no_cache) == len(pages):
        out.append(finding("perf.no_store", C, "All HTML served with Cache-Control: no-store", Severity.info,
                           "Pages cannot be cached by browsers or the back/forward cache, so repeat visits are slower.",
                           "Unless pages are personalised, allow short-lived caching (e.g. `max-age=0, must-revalidate`) so bfcache works.",
                           no_cache[:10], effort=2, confidence="medium"))

    # --- PageSpeed Insights (field + lab) --------------------------------------
    psi = ctx.performance or {}
    if psi.get("available"):
        field = psi.get("field_url") or psi.get("field_origin")
        scope = "this URL" if psi.get("field_url") else "the whole origin"
        if field:
            for name, (good, poor) in THRESHOLDS.items():
                m = field["metrics"].get(name)
                if not m or m["p75"] is None:
                    continue
                v = m["p75"]
                if v > good:
                    sev = Severity.high if v > poor else Severity.medium
                    out.append(finding(f"perf.field_{name.lower()}", C, f"Core Web Vital {name} fails for real users", sev,
                                       f"Chrome UX Report field data for {scope} (p75, last 28 days): {name} = {v}{m['unit']}. Google's 'good' threshold is ≤ {good}{'ms' if name != 'CLS' else ''}. "
                                       "This is real-user data, the same data used in Google's page experience signals.",
                                       {"LCP": "Optimise the hero image (preload it, serve WebP/AVIF, size correctly) and cut TTFB.",
                                        "INP": "Reduce JavaScript on the main thread: remove heavy third-party apps, split long tasks, defer non-critical scripts.",
                                        "CLS": "Reserve space for images, embeds, banners and web fonts; avoid inserting content above existing content."}[name],
                                       [(psi["url"], {"metric": name, "p75": v, "source": "CrUX field", "scope": scope})],
                                       site_level=True, effort=3))
        else:
            out.append(finding("perf.no_field_data", C, "No real-user (CrUX) data available", Severity.info,
                               "Google does not have enough Chrome traffic data for this site, so Core Web Vitals can only be estimated from lab tests.",
                               "Use the lab results below as a guide and monitor with Search Console once traffic grows.",
                               [(psi["url"], {"field_data": None})], site_level=True, effort=1))
        lab = psi.get("lab", {})
        score = lab.get("performance_score")
        if score is not None and score < 50:
            out.append(finding("perf.lab_score_low", C, f"Low Lighthouse mobile performance score ({score}/100)", Severity.medium,
                               "Single simulated lab run on a throttled mid-range phone. Lab scores vary run to run and are a debugging aid, not a ranking factor.",
                               "Work through the top Lighthouse opportunities: " + "; ".join(o["title"] for o in lab.get("opportunities", [])[:3]),
                               [(psi["url"], {"lab_score": score, "source": "Lighthouse lab"})], site_level=True, effort=3))
    return out

from app.audits import ai_search, linking, onpage, structured_data, technical
from app.audits.base import AuditContext, Severity
from app.audits.scoring import category_scores, overall_score, prioritise
from app.crawler.engine import SiteMeta
from app.crawler.parser import PageData, normalize_link, parse_html
from app.crawler.robots import parse_robots
from app.crawler.sitemap import SitemapInfo

HTML = """<!doctype html><html lang="en"><head>
<title>Oak Widget – Buy Online</title>
<meta name="description" content="Handmade widgets shipped worldwide.">
<meta name="viewport" content="width=device-width">
<meta property="og:title" content="Widget">
<link rel="canonical" href="/products/widget">
<script src="/blocking.js"></script><script src="/ok.js" defer></script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"450"}}</script>
<script type="application/ld+json">{bad json</script>
</head><body><h1>Widget</h1><h3>Skipped level</h3><h2>How long does a widget last?</h2>
<p>Text here.</p><a href="/about#team">About us</a><a href="https://other.com/x" rel="nofollow">click here</a>
<a href="mailto:a@b.com">mail</a><img src="/a.jpg"><img src="/b.jpg" alt="Widget box" width="10" height="10" loading="lazy">
</body></html>"""


def make_page(url="https://shop.example/products/widget", html=HTML, **kw) -> PageData:
    p = PageData(url=url, final_url=url, status=200, content_type="text/html", **kw)
    return parse_html(p, html)


def test_parse_html_extracts_signals():
    p = make_page()
    assert p.title == "Oak Widget – Buy Online"
    assert p.canonical == "https://shop.example/products/widget"
    assert p.viewport and p.lang == "en"
    assert p.h1 == ["Widget"]
    assert p.question_headings == 1
    assert p.render_blocking_scripts == 1 and p.scripts_total == 2
    assert len(p.json_ld) == 1 and p.json_ld[0]["@type"] == "Product"
    assert p.json_ld_errors and "Invalid JSON-LD" in p.json_ld_errors[0]
    internal = [l for l in p.links if l.internal]
    external = [l for l in p.links if not l.internal]
    assert internal[0].url == "https://shop.example/about"  # fragment stripped
    assert external[0].nofollow and external[0].anchor == "click here"
    assert len(p.links) == 2  # mailto ignored
    assert [i.alt for i in p.images] == [None, "Widget box"]


def test_normalize_link():
    assert normalize_link("https://A.com/x/", "../y#z") == "https://a.com/y"
    assert normalize_link("https://a.com/", "javascript:void(0)") is None


def ctx_for(pages, robots_txt="User-agent: *\nAllow: /\n", sitemap_found=True) -> AuditContext:
    meta = SiteMeta(start_url=pages[0].url, root="https://shop.example", https=True, http_redirects_to_https=True, homepage_status=200)
    meta.robots = parse_robots("https://shop.example/robots.txt", 200, robots_txt, "SEOAuditAgent")
    meta.sitemap = SitemapInfo(found=["https://shop.example/sitemap.xml"] if sitemap_found else [])
    return AuditContext(meta=meta, pages=pages)


def test_onpage_duplicate_titles_and_missing_h1():
    a = make_page("https://shop.example/", "<html><head><title>Same</title></head><body><p>x</p></body></html>")
    b = make_page("https://shop.example/b", "<html><head><title>Same</title></head><body><h1>B</h1></body></html>")
    ids = {f.check_id: f for f in onpage.run(ctx_for([a, b]))}
    assert set(ids["onpage.title_duplicate"].affected_urls) == {a.url, b.url}
    assert ids["onpage.h1_missing"].affected_urls == [a.url]
    assert "onpage.description_missing" in ids


def test_technical_flags_missing_sitemap_and_viewport():
    p = make_page("https://shop.example/", "<html><head><title>T</title></head><body>hi</body></html>")
    ids = {f.check_id for f in technical.run(ctx_for([p], sitemap_found=False))}
    assert {"tech.no_sitemap", "tech.no_viewport", "tech.no_lang", "tech.canonical_missing"} <= ids


def test_structured_data_required_props():
    p = make_page()
    fs = {f.check_id: f for f in structured_data.run(ctx_for([p]))}
    problems = fs["sd.missing_required"].evidence[0]["problems"]
    assert "Product.offers: missing priceCurrency" in problems
    assert "sd.invalid_json" in fs


def test_ai_search_detects_blocked_bots():
    p = make_page("https://shop.example/")
    robots = "User-agent: *\nAllow: /\n\nUser-agent: PerplexityBot\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /\n"
    fs = {f.check_id: f for f in ai_search.run(ctx_for([p], robots_txt=robots))}
    assert fs["ai.search_bots_blocked"].evidence[0]["blocked_user_agents"] == ["PerplexityBot"]
    assert fs["ai.search_bots_blocked"].severity == Severity.high
    assert "GPTBot" in fs["ai.training_bots_blocked"].evidence[0]["blocked_user_agents"]
    assert fs["ai.training_bots_blocked"].severity == Severity.info


def test_linking_broken_internal():
    home = make_page("https://shop.example/", '<html><body><a href="/gone">gone</a></body></html>')
    gone = PageData(url="https://shop.example/gone", final_url="https://shop.example/gone", status=404, depth=1)
    fs = {f.check_id: f for f in linking.run(ctx_for([home, gone]))}
    assert fs["links.broken_internal"].evidence[0] == {"url": home.url, "broken_link": gone.url, "status": 404}


def test_scoring_and_priority():
    p = make_page("https://shop.example/", "<html><body>x</body></html>")
    findings = technical.run(ctx_for([p], sitemap_found=False)) + onpage.run(ctx_for([p]))
    cats = category_scores(findings, 1, include_competitor=False)
    assert "competitor" not in cats
    assert abs(sum(c["weight"] for c in cats.values()) - 1) < 0.01
    assert all(0 <= c["score"] <= 100 for c in cats.values())
    assert 0 <= overall_score(cats) <= 100
    crit = next(f for f in findings if f.check_id == "tech.no_viewport")
    assert prioritise(crit, 1)["bucket"] in ("quick_win", "critical")
    assert cats["performance"]["score"] == 100  # no performance findings -> full marks


def test_normalize_link_tolerates_malformed_hrefs():
    assert normalize_link("https://a.com/", "http://a.com:abc/") is None
    assert normalize_link("https://a.com/", "http://[::1/") is None

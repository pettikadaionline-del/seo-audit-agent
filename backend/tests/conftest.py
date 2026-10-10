"""A fake shop website served through httpx.MockTransport (no network)."""
import httpx
import pytest

from app.config import Settings
from app.crawler.fetcher import Fetcher

BASE = "https://shop.example.com"
LOREM = " ".join(["Traditional handmade snacks prepared with fresh groundnut oil and stone-ground flour."] * 60)

HOME = f"""<!doctype html><html lang="en"><head><title>Example Shop</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Buy traditional South Indian snacks online with worldwide delivery. Freshly made, no preservatives, shipped in 48 hours.">
<link rel="canonical" href="{BASE}/">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Organization","name":"Example Shop","url":"{BASE}"}}</script>
</head><body><h1>Example Shop</h1><p>{LOREM}</p>
<a href="/products/murukku">Murukku</a> <a href="/products/halwa">click here</a>
<a href="/blog/history-of-halwa">History of halwa</a> <a href="/missing-page">Old offer</a>
<a href="/old-url">Legacy</a> <a href="https://other.example.org/">Partner</a>
<img src="/hero.jpg" alt="Hero"></body></html>"""

PRODUCT = """<!doctype html><html lang="en"><head><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body><h1>{title}</h1><p>Crunchy and fresh.</p><img src="/p.jpg"><a href="/">Home</a></body></html>"""

BLOG = f"""<!doctype html><html lang="en"><head><title>The History of Tirunelveli Halwa - Example Shop Blog</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Discover how Tirunelveli halwa became famous: the wheat milk, the copper vessels and the river water legend.">
<link rel="canonical" href="{BASE}/blog/history-of-halwa">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"Article"</script>
</head><body><main><h1>The History of Halwa</h1><h3>Origins</h3><p>{LOREM}</p></main><a href="/">Home</a></body></html>"""

ROUTES = {
    "/": (200, HOME, "text/html; charset=utf-8"),
    "/products/murukku": (200, PRODUCT.format(title="Murukku"), "text/html"),
    "/products/halwa": (200, PRODUCT.format(title="Murukku"), "text/html"),  # duplicate title on purpose
    "/blog/history-of-halwa": (200, BLOG, "text/html"),
    "/robots.txt": (200, f"User-agent: *\nDisallow: /cart\n\nUser-agent: PerplexityBot\nDisallow: /\n\nSitemap: {BASE}/sitemap.xml\n", "text/plain"),
    "/sitemap.xml": (200, f"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{BASE}/</loc></url><url><loc>{BASE}/products/murukku</loc></url><url><loc>{BASE}/orphan</loc></url></urlset>""", "application/xml"),
    "/orphan": (200, PRODUCT.format(title="Orphan page that nobody links to at all"), "text/html"),
}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host != "shop.example.com":
        return httpx.Response(404)
    if request.url.scheme == "http":
        return httpx.Response(301, headers={"location": str(request.url.copy_with(scheme="https"))})
    if path == "/old-url":
        return httpx.Response(301, headers={"location": "/old-url-2"})
    if path == "/old-url-2":
        return httpx.Response(301, headers={"location": "/products/murukku"})
    if path in ROUTES:
        status, body, ctype = ROUTES[path]
        return httpx.Response(status, text=body, headers={"content-type": ctype})
    return httpx.Response(404, text="<html><title>Not found</title></html>", headers={"content-type": "text/html"})


@pytest.fixture
def settings(tmp_path):
    return Settings(
        allow_private_networks=True,  # skip DNS; MockTransport never touches the network
        delay_between_requests_s=0,
        database_path=str(tmp_path / "test.db"),
        ai_enabled=False,
        pagespeed_api_key=None,
    )


@pytest.fixture
def fetcher_factory(settings):
    return lambda: Fetcher(settings, transport=httpx.MockTransport(handler))

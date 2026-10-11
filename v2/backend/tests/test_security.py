import pytest

from app.core.security import UnsafeURLError, assert_public_url, normalize_input_url


def test_normalize_adds_scheme_and_path():
    assert normalize_input_url("Example.COM") == "https://example.com/"
    assert normalize_input_url("http://example.com/a?b=1#frag") == "http://example.com/a?b=1"


@pytest.mark.parametrize("bad", ["ftp://example.com", "file:///etc/passwd", "javascript:alert(1)", "", "https://user:pw@example.com"])
def test_normalize_rejects(bad):
    with pytest.raises(UnsafeURLError):
        normalize_input_url(bad)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://metadata.google.internal/",
        "http://example.com:22/",
    ],
)
async def test_ssrf_blocked(url):
    with pytest.raises(UnsafeURLError):
        await assert_public_url(url, allow_private=False)


async def test_public_ip_literal_allowed():
    await assert_public_url("https://8.8.8.8/", allow_private=False)


async def test_fetcher_blocks_private_peer(fixture_site):
    """Even if pre-flight passes, a connection that lands on a private IP is refused."""
    from app.core.config import Settings
    from app.crawler import fetcher as fetcher_mod

    async def allow_all(url, allow_private=False):
        return None

    s = Settings(allow_private_targets=False, request_delay_seconds=0)
    orig = fetcher_mod.assert_public_url
    fetcher_mod.assert_public_url = allow_all
    try:
        async with fetcher_mod.Fetcher(s) as f:
            f._proxied = False
            res = await f.fetch(fixture_site)
    finally:
        fetcher_mod.assert_public_url = orig
    assert res.status is None and "non-public" in res.error

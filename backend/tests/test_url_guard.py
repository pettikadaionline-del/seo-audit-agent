import pytest

from app.security.url_guard import UnsafeURLError, check_url_syntax, validate_url


@pytest.mark.parametrize("url", [
    "ftp://example.com/",
    "file:///etc/passwd",
    "http://localhost/",
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://user:pass@example.com/",
    "http://example.com:22/",
    "http://metadata.google.internal/",
    "http://printer.local/",
    "http://intranet/",
    "http://100.64.0.1/",
    "http://0.0.0.0/",
])
def test_rejects_unsafe(url):
    with pytest.raises(UnsafeURLError):
        check_url_syntax(url)


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com:8080/x", "https://93.184.216.34/"])
def test_accepts_public(url):
    check_url_syntax(url)


async def test_dns_resolution_to_private_is_blocked(monkeypatch):
    import asyncio
    import socket

    async def fake_getaddrinfo(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError, match="non-public"):
        await validate_url("https://evil-rebind.example.com/")

"""URL normalisation helpers."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".pdf", ".zip", ".gz",
    ".mp4", ".mp3", ".avi", ".mov", ".css", ".js", ".woff", ".woff2", ".ttf", ".xml", ".txt",
)


def normalize(url: str, base: str | None = None) -> str | None:
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if parts.port and not ((parts.scheme == "http" and parts.port == 80) or (parts.scheme == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in TRACKING_PARAMS))
    return urlunsplit((parts.scheme, host, path, query, ""))


def same_site(url: str, origin_host: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    return strip(host) == strip(origin_host.lower())


def is_crawlable_resource(url: str) -> bool:
    return not urlsplit(url).path.lower().endswith(SKIP_EXTENSIONS)

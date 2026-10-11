"""SSRF protection: only public http(s) targets may be crawled.

Every URL (including every redirect hop) is resolved and each resolved IP is
checked, so a public hostname that resolves to an internal address is refused.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    pass


BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata"}


def normalize_input_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise UnsafeURLError("URL is empty")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http and https URLs are supported")
    if not parts.hostname:
        raise UnsafeURLError("URL has no hostname")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with credentials are not allowed")
    path = parts.path or "/"
    netloc = parts.hostname.lower()
    if port:
        netloc += f":{port}"
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme}://{netloc}{path}{query}"


def ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


async def assert_public_url(url: str, allow_private: bool = False) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Blocked scheme: {parts.scheme}")
    host = (parts.hostname or "").lower()
    if not host:
        raise UnsafeURLError("Missing hostname")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    if port and port not in (80, 443, 8080, 8443) and not allow_private:
        raise UnsafeURLError(f"Blocked port: {port}")
    if allow_private:
        return
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".internal"):
        raise UnsafeURLError(f"Blocked host: {host}")

    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not ip_is_public(literal):
            raise UnsafeURLError(f"Blocked non-public address: {host}")
        return

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip_is_public(ip):
            raise UnsafeURLError(f"Host {host} resolves to a non-public address")

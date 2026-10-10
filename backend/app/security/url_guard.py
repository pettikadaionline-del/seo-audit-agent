"""SSRF protection: only public http(s) targets are fetchable.

Every URL (including each redirect hop) must pass `validate_url` before a
request is made. DNS is resolved and *every* returned address is checked, so
a hostname that resolves to a private / loopback / link-local / metadata
address is rejected.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443, 8080, 8443}
BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


class UnsafeURLError(ValueError):
    pass


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
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


def check_url_syntax(url: str) -> tuple[str, int | None]:
    """Static checks that need no DNS. Returns (hostname, port)."""
    if len(url) > 2048:
        raise UnsafeURLError("URL too long")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Scheme not allowed: {parts.scheme or '(none)'}")
    if parts.username or parts.password:
        raise UnsafeURLError("Credentials in URL are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError(f"Port not allowed: {port}")
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"Host not allowed: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            raise UnsafeURLError("Single-label hostnames are not allowed")
    else:
        if not _ip_is_public(ip):
            raise UnsafeURLError(f"Non-public IP address: {host}")
    return host, port


async def validate_url(url: str, allow_private: bool = False) -> str:
    """Full validation incl. DNS resolution. Returns the URL unchanged."""
    host, port = check_url_syntax(url) if not allow_private else _lenient(url)
    if allow_private:
        return url
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not _ip_is_public(ip):
            raise UnsafeURLError(f"{host} resolves to non-public address {ip}")
    return url


def _lenient(url: str) -> tuple[str, int | None]:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
        raise UnsafeURLError("Only http(s) URLs with a host are allowed")
    return parts.hostname, parts.port

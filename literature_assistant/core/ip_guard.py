"""Neutral IP classifier shared between MCP registration-time and connect-time
SSRF guards.

Both ``mcp_runtime.security_policy.validate_streamable_http_url`` (the
registration-time guard) and ``mcp_runtime.safe_transport.SafeMCPAsyncTransport``
(the connect-time guard) must agree on what "unsafe for outbound" means.
This module is the single source of truth.

The classifier uses an explicit union of stdlib ``ipaddress`` properties:

    is_private | is_loopback | is_link_local | is_multicast
                | is_reserved | is_unspecified  | not is_global

The ``not is_global`` fallback is what catches RFC 6598 carrier-grade NAT
(``100.64.0.0/10``), which is neither ``is_private`` nor ``is_global`` per
the Python docs.

IPv6 wrappers (IPv4-mapped, 6to4, Teredo) are unwrapped before classification
so that ``::ffff:127.0.0.1`` cannot evade an IPv4-loopback check.

References:
- OWASP SSRF Prevention Cheat Sheet
- Python ``ipaddress`` module docs (IPv4Address / IPv6Address properties,
  ``ipv4_mapped`` / ``sixtofour`` / ``teredo``)
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _unwrap(addr: IPAddress) -> IPAddress:
    """Unwrap IPv6 tunneling wrappers to the embedded IPv4 address.

    Without this, an attacker could bypass a loopback check by sending
    ``::ffff:127.0.0.1`` (IPv4-mapped IPv6), ``2002:7f00:0001::`` (6to4),
    or a Teredo address embedding 127.0.0.1.
    """
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return addr.ipv4_mapped
        if addr.sixtofour is not None:
            return addr.sixtofour
        teredo = addr.teredo
        if teredo is not None:
            # teredo returns (server, client); the client IP is what would
            # actually receive traffic.
            return teredo[1]
    return addr


def classify_unsafe_ip(addr: IPAddress) -> tuple[bool, str | None]:
    """Return ``(is_unsafe, reason)`` for an IP address.

    ``reason`` is a short stable token usable in audit logs and error
    messages (e.g. ``"loopback"``, ``"ipv4_mapped:private"``). ``None`` when
    the address is safe for outbound traffic.
    """
    original = addr
    addr = _unwrap(addr)
    prefix = ""
    if addr is not original:
        if isinstance(original, ipaddress.IPv6Address):
            if original.ipv4_mapped is not None:
                prefix = "ipv4_mapped:"
            elif original.sixtofour is not None:
                prefix = "sixtofour:"
            elif original.teredo is not None:
                prefix = "teredo:"

    if addr.is_loopback:
        return True, prefix + "loopback"
    if addr.is_link_local:
        return True, prefix + "link_local"
    if addr.is_multicast:
        return True, prefix + "multicast"
    if addr.is_unspecified:
        return True, prefix + "unspecified"
    if addr.is_reserved:
        return True, prefix + "reserved"
    if addr.is_private:
        return True, prefix + "private"
    if not addr.is_global:
        # Catches RFC 6598 100.64.0.0/10 (CGN) and other "neither private
        # nor global" allocations the explicit union above misses.
        return True, prefix + "non_global"
    return False, None


def is_unsafe_ip(addr: IPAddress) -> bool:
    """Boolean wrapper around :func:`classify_unsafe_ip`."""
    return classify_unsafe_ip(addr)[0]


def parse_ip(value: str) -> IPAddress | None:
    """Parse a literal IP string. Returns ``None`` if invalid."""
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def resolve_host_to_ips(host: str, port: int) -> list[str]:
    """Return distinct resolved IP strings for ``host`` (both A and AAAA).

    Caller is responsible for raising on the empty list / socket errors;
    this returns whatever ``getaddrinfo`` produces, deduplicated.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else ""
        if ip_str and ip_str not in seen:
            seen.append(ip_str)
    return seen


def classify_resolved_ips(
    ip_strings: Iterable[str],
) -> list[tuple[str, bool, str | None]]:
    """Map each IP string to ``(ip, is_unsafe, reason)``.

    Invalid IP strings are flagged unsafe with reason ``"unparseable"`` —
    a resolver that returns garbage is itself a foot-gun.
    """
    out: list[tuple[str, bool, str | None]] = []
    for ip_str in ip_strings:
        addr = parse_ip(ip_str)
        if addr is None:
            out.append((ip_str, True, "unparseable"))
            continue
        unsafe, reason = classify_unsafe_ip(addr)
        out.append((ip_str, unsafe, reason))
    return out


__all__ = [
    "IPAddress",
    "classify_resolved_ips",
    "classify_unsafe_ip",
    "is_unsafe_ip",
    "parse_ip",
    "resolve_host_to_ips",
]

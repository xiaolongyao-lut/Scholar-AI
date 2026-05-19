"""Connect-time SSRF guard for MCP streamable HTTP clients.

The MCP SDK's ``streamablehttp_client`` accepts an ``httpx_client_factory``
hook. We use it to install an async transport that re-resolves the request
host's A/AAAA records on every request and rejects any address classified
unsafe by :mod:`ip_guard`. Combined with ``follow_redirects=False`` this
closes:

- **DNS rebinding at connect time** — registration-time DNS resolution may
  have returned a public IP, but the second resolution at httpx connect
  could return ``127.0.0.1`` / metadata IP. We re-validate on every send.
- **Redirect bypass** — the initial URL is safe but a 302 redirects to a
  metadata endpoint. We disable automatic redirect following entirely.

Residual TOCTOU (the time between our ``getaddrinfo`` and httpx's own
socket connect) is accepted per OWASP guidance — full IP pinning would
require a custom socket factory and is deferred.

References:
- OWASP SSRF Prevention Cheat Sheet
- HTTPX custom transports
- ``mcp.client.streamable_http.streamablehttp_client`` signature
"""

from __future__ import annotations

import os
from datetime import timedelta

import httpx

from ip_guard import classify_resolved_ips, resolve_host_to_ips, parse_ip, classify_unsafe_ip


class McpSsrfBlocked(httpx.TransportError):
    """Raised when SafeMCPAsyncTransport refuses to dispatch a request because
    the resolved host is in a non-public range.

    Subclasses ``httpx.TransportError`` so the MCP SDK's error envelope
    treats it as a transport-layer failure rather than an unexpected
    application exception.
    """


def _allow_private() -> bool:
    """Mirror the registration-time bypass switch.

    Connect-time must honor the same env var as
    ``mcp_runtime.security_policy._allow_private_streamable_http``;
    otherwise a private endpoint accepted at registration would be
    blocked at runtime and the user can't tell which guard fired.
    """
    return os.environ.get(
        "LITERATURE_MCP_HTTP_ALLOW_PRIVATE", ""
    ).strip().lower() in {"1", "true", "yes", "on"}


class SafeMCPAsyncTransport(httpx.AsyncBaseTransport):
    """Async httpx transport wrapping the default ``AsyncHTTPTransport``.

    On every ``handle_async_request`` we resolve ``request.url.host`` and
    classify each returned A/AAAA address. If any resolved IP is unsafe
    (private, loopback, link-local, multicast, reserved, unspecified, or
    a non-global allocation like ``100.64.0.0/10`` carrier NAT), the request
    is refused before any bytes go on the wire.

    Tests can inject ``inner`` to short-circuit the real network
    (``httpx.MockTransport`` is the intended substitute).
    """

    def __init__(
        self,
        *,
        inner: httpx.AsyncBaseTransport | None = None,
        verify: bool = True,
    ) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport(verify=verify)

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        host = (request.url.host or "").strip()
        if not host:
            raise McpSsrfBlocked("request URL missing host")

        if _allow_private():
            return await self._inner.handle_async_request(request)

        port = request.url.port or (443 if request.url.scheme == "https" else 80)

        literal = parse_ip(host)
        if literal is not None:
            unsafe, reason = classify_unsafe_ip(literal)
            if unsafe:
                raise McpSsrfBlocked(
                    f"connect-time guard refused IP literal {host!r}: {reason}"
                )
            return await self._inner.handle_async_request(request)

        try:
            ips = resolve_host_to_ips(host, port)
        except OSError as exc:
            raise McpSsrfBlocked(
                f"connect-time guard could not resolve host {host!r}: {exc}"
            ) from exc

        if not ips:
            raise McpSsrfBlocked(
                f"connect-time guard got no addresses for host {host!r}"
            )

        for ip_str, unsafe, reason in classify_resolved_ips(ips):
            if unsafe:
                raise McpSsrfBlocked(
                    f"connect-time guard refused host {host!r} which "
                    f"resolves to {ip_str} ({reason}); set "
                    f"LITERATURE_MCP_HTTP_ALLOW_PRIVATE=1 to bypass"
                )

        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def safe_mcp_httpx_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Drop-in replacement for ``mcp.shared._httpx_utils.create_mcp_http_client``.

    Signature mirrors what the MCP SDK passes when invoking
    ``httpx_client_factory(headers=..., timeout=..., auth=...)``.

    Returns an ``AsyncClient`` that:

    - Routes every request through :class:`SafeMCPAsyncTransport`
    - Has ``follow_redirects=False`` (OWASP DON'T list for SSRF defense;
      otherwise a 302 to a metadata IP would bypass our guard)
    """
    effective_timeout = timeout if timeout is not None else httpx.Timeout(
        timedelta(seconds=30).total_seconds(),
        read=timedelta(minutes=5).total_seconds(),
    )
    return httpx.AsyncClient(
        headers=headers,
        timeout=effective_timeout,
        auth=auth,
        follow_redirects=False,
        transport=SafeMCPAsyncTransport(),
    )


__all__ = [
    "McpSsrfBlocked",
    "SafeMCPAsyncTransport",
    "safe_mcp_httpx_client_factory",
]

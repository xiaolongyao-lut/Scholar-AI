"""Provider endpoint policy.

Single source of trust enforcement, used by both credential tests and the Model Dispatcher.

Pipeline:
    URL parse  ->  reject userinfo / query / fragment
    Scheme normalize  ->  remote requires HTTPS (loopback exception deferred)
    Host normalize (lowercase, no trailing dot)
    Trust-source decision:
        official_provider  -> require host on built-in allowlist
        env_configured_gateway  -> bypass official allowlist
        runtime_user_confirmed  -> bypass official allowlist
        runtime_untrusted_custom  -> reject by default
    DNS resolve A/AAAA via dnspython (fail-closed on DNS errors,
    fallback to socket.getaddrinfo as degraded path)
    Reject host whose IP set contains private / loopback / link-local /
    reserved / unspecified / multicast addresses (DNS-rebinding defense)

Public API:
    OfficialProviderHost    : enum of canonical hosts we ship support for
    PolicyDecision          : structured (allow / reject / skip) + reason
    validate_endpoint(...)  : run the full pipeline against a URL+trust_source

When called by the credential-test endpoint, the policy must run BEFORE any
Authorization header is constructed.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit


# ---------------------------------------------------------------------------
# Built-in official-provider allowlist.
# ---------------------------------------------------------------------------

OFFICIAL_PROVIDER_HOSTS: dict[str, set[str]] = {
    "OpenAI": {"api.openai.com"},
    "Anthropic": {"api.anthropic.com"},
    "DeepSeek": {"api.deepseek.com"},
    "DoubaoArk": {"ark.cn-beijing.volces.com"},
    "Gemini": {"generativelanguage.googleapis.com"},
    "OpenRouter": {"openrouter.ai"},
    "SiliconFlow": {"api.siliconflow.cn"},
    "DashScope": {"dashscope.aliyuncs.com"},
    "Groq": {"api.groq.com"},
    "Mistral": {"api.mistral.ai"},
}


def all_official_hosts() -> set[str]:
    out: set[str] = set()
    for hs in OFFICIAL_PROVIDER_HOSTS.values():
        out |= hs
    return out


# ---------------------------------------------------------------------------
# Trust source enum (mirrors models.credentials.CredentialTrustSource).
# Duplicated here as a string vocabulary so this module is import-safe even
# without pydantic models loaded.
# ---------------------------------------------------------------------------


class TrustSource(str, Enum):
    OFFICIAL_PROVIDER = "official_provider"
    ENV_CONFIGURED_GATEWAY = "env_configured_gateway"
    RUNTIME_USER_CONFIRMED = "runtime_user_confirmed"
    RUNTIME_UNTRUSTED_CUSTOM = "runtime_untrusted_custom"


# ---------------------------------------------------------------------------
# Decision result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    trust_source: str
    scheme: str = ""
    host: str = ""
    port: int | None = None
    path: str = ""
    resolved_ips: tuple[str, ...] = field(default_factory=tuple)
    rejected_ips: tuple[str, ...] = field(default_factory=tuple)
    skipped_network: bool = False

    def as_log_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "trust_source": self.trust_source,
            "scheme": self.scheme,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "resolved_ips": list(self.resolved_ips),
            "rejected_ips": list(self.rejected_ips),
            "skipped_network": self.skipped_network,
        }


def _allow(reason: str, trust_source: str, **kw) -> PolicyDecision:
    return PolicyDecision(allowed=True, reason=reason, trust_source=trust_source, **kw)


def _reject(reason: str, trust_source: str, **kw) -> PolicyDecision:
    return PolicyDecision(allowed=False, reason=reason, trust_source=trust_source, **kw)


def _skip(reason: str, trust_source: str, **kw) -> PolicyDecision:
    return PolicyDecision(
        allowed=False, reason=reason, trust_source=trust_source,
        skipped_network=True, **kw,
    )


# ---------------------------------------------------------------------------
# DNS resolution
# ---------------------------------------------------------------------------


class DNSResolutionError(RuntimeError):
    pass


def _resolve_via_dnspython(host: str) -> list[str]:
    try:
        import dns.resolver  # noqa: PLC0415
        import dns.exception  # noqa: PLC0415
    except ImportError as exc:
        raise DNSResolutionError(f"dnspython unavailable: {exc}") from exc

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0
    ips: list[str] = []
    last_exc: Exception | None = None
    for rdtype in ("A", "AAAA"):
        try:
            answers = resolver.resolve(host, rdtype, lifetime=5.0)
            for rdata in answers:
                ips.append(str(rdata))
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN as exc:
            raise DNSResolutionError(f"NXDOMAIN: {host}") from exc
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as exc:
            last_exc = exc
            continue
        except Exception as exc:  # noqa: BLE001 — fail closed on unexpected dnspython errors; resolver fallbacks decide the final result.
            last_exc = exc
            continue
    if not ips:
        if last_exc is not None:
            raise DNSResolutionError(
                f"dns resolve {host} failed: {last_exc.__class__.__name__}"
            ) from last_exc
        raise DNSResolutionError(f"no A/AAAA records for {host}")
    return ips


def _resolve_via_stdlib(host: str) -> list[str]:
    """Degraded fallback (per Q2 approval). Only when dnspython unavailable."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise DNSResolutionError(f"getaddrinfo failed: {exc}") from exc
    out: list[str] = []
    for family, _stype, _proto, _canon, sockaddr in infos:
        if family == socket.AF_INET:
            out.append(sockaddr[0])
        elif family == socket.AF_INET6:
            out.append(sockaddr[0])
    if not out:
        raise DNSResolutionError(f"no addresses for {host}")
    return out


def resolve_host(host: str) -> list[str]:
    """Best-effort A/AAAA resolution. Prefers dnspython; falls back to stdlib.

    Always raises DNSResolutionError on failure (fail-closed, per Q2).
    """
    try:
        return _resolve_via_dnspython(host)
    except DNSResolutionError:
        return _resolve_via_stdlib(host)


# ---------------------------------------------------------------------------
# IP classification
# ---------------------------------------------------------------------------


def classify_ip(ip_str: str) -> str | None:
    """Return a human-readable rejection reason if ip is unsafe, else None."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return f"invalid_ip:{ip_str}"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved:
        return "reserved"
    if ip.is_private:
        return "private"
    return None


# ---------------------------------------------------------------------------
# Main policy
# ---------------------------------------------------------------------------


def validate_endpoint(
    base_url: str,
    *,
    trust_source: str | TrustSource,
    skip_dns: bool = False,
    allow_loopback_http: bool = False,
) -> PolicyDecision:
    """Run the full endpoint validation pipeline.

    base_url      The credential's base_url (path-only; no query/fragment).
    trust_source  One of CredentialTrustSource values.
    skip_dns      Tests / dispatcher cache may pass True to defer DNS to the
                  network layer. Production callers should leave False.
    allow_loopback_http
                  Permit explicit local HTTP endpoints for self-hosted
                  providers. Only loopback hosts/IPs may use this exception.

    Returns a PolicyDecision describing allow / reject / skip with structured
    reason. Authorization header must NOT be built unless decision.allowed.
    """
    ts = trust_source.value if isinstance(trust_source, TrustSource) else trust_source
    if ts not in {t.value for t in TrustSource}:
        return _reject("unknown_trust_source", ts or "unknown")

    if not base_url or not isinstance(base_url, str):
        return _reject("empty_base_url", ts)

    parsed = urlsplit(base_url.strip())

    if parsed.scheme.lower() not in {"http", "https"}:
        return _reject(f"scheme_not_http(s):{parsed.scheme}", ts)

    if parsed.username or parsed.password:
        return _reject("userinfo_in_url", ts)

    if parsed.query or parsed.fragment:
        return _reject("query_or_fragment_in_url", ts)

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return _reject("missing_host", ts)

    port = parsed.port

    # Scheme policy: remote MUST be HTTPS. http:// is allowed only for an
    # explicit loopback provider such as local Ollama or LM Studio.
    if parsed.scheme.lower() == "http":
        loopback_host = False
        try:
            loopback_host = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback_host = host == "localhost"
        if not allow_loopback_http or not loopback_host:
            return _reject("http_scheme_not_allowed_for_remote", ts,
                           scheme=parsed.scheme.lower(), host=host, port=port,
                           path=parsed.path)

    # Trust-source gate: untrusted custom is skip_network by default.
    if ts == TrustSource.RUNTIME_UNTRUSTED_CUSTOM.value:
        return _skip("untrusted_custom_requires_explicit_trust", ts,
                     scheme=parsed.scheme.lower(), host=host, port=port,
                     path=parsed.path)

    # Official-provider trust requires host on allowlist.
    if ts == TrustSource.OFFICIAL_PROVIDER.value:
        if host not in all_official_hosts():
            return _reject("official_provider_host_mismatch", ts,
                           scheme=parsed.scheme.lower(), host=host, port=port,
                           path=parsed.path)

    # env_configured_gateway and runtime_user_confirmed bypass the host allowlist
    # but must still pass SSRF validation. User confirmation is not a network
    # safety override.

    if skip_dns:
        return _allow("skip_dns_passthrough", ts,
                      scheme=parsed.scheme.lower(), host=host, port=port,
                      path=parsed.path)

    # DNS resolve + IP classify (fail-closed per Q2 approval).
    try:
        ips = resolve_host(host)
    except DNSResolutionError as exc:
        return _reject(f"dns_resolution_failed:{exc}", ts,
                       scheme=parsed.scheme.lower(), host=host, port=port,
                       path=parsed.path)

    rejected: list[str] = []
    for ip in ips:
        why = classify_ip(ip)
        if (
            why == "loopback"
            and allow_loopback_http
            and parsed.scheme.lower() == "http"
        ):
            continue
        if why is not None:
            rejected.append(f"{ip}({why})")
    if rejected:
        return _reject("dns_resolved_to_unsafe_ip", ts,
                       scheme=parsed.scheme.lower(), host=host, port=port,
                       path=parsed.path,
                       resolved_ips=tuple(ips),
                       rejected_ips=tuple(rejected))

    return _allow("ok", ts,
                  scheme=parsed.scheme.lower(), host=host, port=port,
                  path=parsed.path,
                  resolved_ips=tuple(ips))


__all__ = [
    "DNSResolutionError",
    "OFFICIAL_PROVIDER_HOSTS",
    "PolicyDecision",
    "TrustSource",
    "all_official_hosts",
    "classify_ip",
    "resolve_host",
    "validate_endpoint",
]

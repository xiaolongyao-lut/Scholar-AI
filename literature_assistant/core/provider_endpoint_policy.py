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

VPN / proxy fake-IP exception (added 2026-06-12):
    When a corporate VPN or proxy is configured in "fake-IP" mode, official
    provider domains can resolve to RFC 2544 benchmark range (198.18.0.0/15)
    instead of real public IPs. The strict SSRF gate rejects this as
    ``dns_resolved_to_unsafe_ip``. To recover, set:
        LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS=1
    optionally
        LITASSIST_PROXY_FAKE_IP_CIDRS=198.18.0.0/15  (default)
    Then official-host + https + all-IPs-in-fake-CIDR is allowed with reason
    ``official_provider_fake_ip_proxy_allowed``. custom / runtime_untrusted /
    http / partial-fake-IP / private-network IPs are STILL rejected.

Trusted custom provider hosts (added 2026-06-13):
    Some self-managed gateways / CDN-fronted custom proxies are reached via
    fake-IP DNS proxies (Clash / Mihomo / corporate VPN), so even though the
    user *intends* to trust the hostname, all A records point inside the
    fake-IP CIDR (198.18.0.0/15 etc.) which the strict SSRF gate rejects.
    Rule 7 only covers official-provider hosts. To recover for known custom
    hosts, set:
        LITASSIST_TRUSTED_CUSTOM_PROVIDER_HOSTS=ai.example.com,gw.example.net
    Comma-separated, case-insensitive. The exception applies only when:
      - host (lowercased) is in the env-configured set
      - scheme is https
      - trust_source ∈ {env_configured_gateway, runtime_user_confirmed}
      - every resolved IP falls within LITASSIST_PROXY_FAKE_IP_CIDRS
    Loopback / RFC 1918 / link-local IPs are STILL rejected as long as they
    fall OUTSIDE the configured fake-IP CIDRs (this is a host-scoped, CIDR-
    scoped allowlist — not a blanket IP override). Reason on allow:
    ``trusted_custom_provider_host_allowed``.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit


logger = logging.getLogger("provider_endpoint_policy")


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
    "MinerU": {"mineru.net"},
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


# ---------------------------------------------------------------------------
# VPN / proxy fake-IP exception (rule 7 of endpoint policy V2 — 2026-06-12)
# ---------------------------------------------------------------------------

# Trust-sources eligible for fake-IP compatibility. runtime_untrusted_custom
# is intentionally absent.
_FAKE_IP_ELIGIBLE_TRUST_SOURCES: frozenset[str] = frozenset({
    TrustSource.OFFICIAL_PROVIDER.value,
    TrustSource.ENV_CONFIGURED_GATEWAY.value,
    TrustSource.RUNTIME_USER_CONFIRMED.value,
})

_DEFAULT_FAKE_IP_CIDRS = "198.18.0.0/15"


def _proxy_fake_ip_enabled() -> bool:
    """``LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS`` truthy?"""
    raw = os.environ.get(
        "LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "",
    ).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _proxy_fake_ip_cidrs() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse env-configured fake-IP CIDR list. Bad entries are dropped with a warning."""
    raw = os.environ.get("LITASSIST_PROXY_FAKE_IP_CIDRS", "").strip()
    if not raw:
        raw = _DEFAULT_FAKE_IP_CIDRS
    out: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(ipaddress.ip_network(piece, strict=False))
        except (ValueError, TypeError):
            logger.warning("LITASSIST_PROXY_FAKE_IP_CIDRS: invalid CIDR %r, skipping", piece)
    return tuple(out)


def _ip_in_fake_cidrs(
    ip_str: str,
    cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    """True iff ip_str parses and falls within ANY configured fake-IP CIDR."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for net in cidrs:
        # Match address family — IPv4 addr against IPv4 net only, and vice versa.
        if isinstance(ip, ipaddress.IPv4Address) and isinstance(net, ipaddress.IPv4Network):
            if ip in net:
                return True
        elif isinstance(ip, ipaddress.IPv6Address) and isinstance(net, ipaddress.IPv6Network):
            if ip in net:
                return True
    return False


def _all_ips_are_fake_ip_for_official_provider(
    *,
    host: str,
    scheme: str,
    trust_source: str,
    ips: list[str],
) -> bool:
    """Return True iff this resolution qualifies for the fake-IP exception.

    All conditions must hold (rule 7):
      - env LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS truthy
      - scheme is https
      - host is on the built-in official-provider allowlist
      - trust_source ∈ {official_provider, env_configured_gateway, runtime_user_confirmed}
      - ips non-empty AND every IP falls within a configured fake-IP CIDR

    If a host resolves to BOTH a fake-IP AND a real private/loopback IP
    (rule 7 last bullet), this returns False so the standard SSRF gate
    rejects the call.
    """
    if not _proxy_fake_ip_enabled():
        return False
    if scheme != "https":
        return False
    if host not in all_official_hosts():
        return False
    if trust_source not in _FAKE_IP_ELIGIBLE_TRUST_SOURCES:
        return False
    if not ips:
        return False
    cidrs = _proxy_fake_ip_cidrs()
    if not cidrs:
        return False
    return all(_ip_in_fake_cidrs(ip, cidrs) for ip in ips)


# ---------------------------------------------------------------------------
# Trusted custom provider hosts (rule 8 of endpoint policy V2 — 2026-06-13)
# ---------------------------------------------------------------------------

# Same eligible trust-sources as rule 7 except OFFICIAL_PROVIDER (an official
# host already has its own dedicated allowlist). RUNTIME_UNTRUSTED_CUSTOM is
# intentionally excluded — user must have actively confirmed or env-configured.
_TRUSTED_CUSTOM_ELIGIBLE_TRUST_SOURCES: frozenset[str] = frozenset({
    TrustSource.ENV_CONFIGURED_GATEWAY.value,
    TrustSource.RUNTIME_USER_CONFIRMED.value,
})


def _trusted_custom_provider_hosts() -> frozenset[str]:
    """Parse ``LITASSIST_TRUSTED_CUSTOM_PROVIDER_HOSTS`` (case-insensitive)."""
    raw = os.environ.get("LITASSIST_TRUSTED_CUSTOM_PROVIDER_HOSTS", "").strip()
    if not raw:
        return frozenset()
    out: set[str] = set()
    for piece in raw.split(","):
        host = piece.strip().lower().rstrip(".")
        if host:
            out.add(host)
    return frozenset(out)


def _host_is_trusted_custom_provider(
    *,
    host: str,
    scheme: str,
    trust_source: str,
    ips: list[str],
) -> bool:
    """Return True iff this host qualifies for the trusted-custom-provider exception.

    All conditions must hold (rule 8):
      - host (lowercased) ∈ env-configured trusted-custom set
      - scheme is https (custom hosts MUST use TLS; no http exception here)
      - trust_source ∈ {env_configured_gateway, runtime_user_confirmed}
      - every resolved IP falls within LITASSIST_PROXY_FAKE_IP_CIDRS
        (default 198.18.0.0/15). This keeps the override host-scoped without
        opening a SSRF hole into RFC 1918 / loopback / metadata IPs — the
        operator has to explicitly list both the host AND the CIDR.
    """
    if scheme != "https":
        return False
    if trust_source not in _TRUSTED_CUSTOM_ELIGIBLE_TRUST_SOURCES:
        return False
    trusted = _trusted_custom_provider_hosts()
    if not trusted or host not in trusted:
        return False
    if not ips:
        return False
    cidrs = _proxy_fake_ip_cidrs()
    if not cidrs:
        return False
    return all(_ip_in_fake_cidrs(ip, cidrs) for ip in ips)


def classify_ip(ip_str: str) -> str | None:
    """Return a human-readable rejection reason if ip is unsafe, else None.

    与 ip_guard.classify_unsafe_ip 保持一致(同款不安全集合 + RFC 6598 CGN
    100.64.0.0/10 经 ``not is_global`` 覆盖),避免 dispatcher / 凭据测试链路
    被 CGN DNS 应答绕过 SSRF 防御。
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return f"invalid_ip:{ip_str}"
    try:
        from ip_guard import classify_unsafe_ip
    except ImportError:
        classify_unsafe_ip = None  # type: ignore[assignment]
    if classify_unsafe_ip is not None:
        unsafe, reason = classify_unsafe_ip(ip)
        if unsafe:
            return reason or "unsafe_ip"
        return None
    # Fallback if ip_guard unreachable (frozen edge case): inline same checks.
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
    if not ip.is_global:
        return "non_global"
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

    # VPN / proxy fake-IP exception (rule 7 of endpoint policy V2).
    # Must run BEFORE the strict per-IP classify, because the standard gate
    # would reject 198.18.x.x as "non_global". This exception is narrow:
    # official-host HTTPS + all IPs in configured fake CIDR + env opt-in.
    if _all_ips_are_fake_ip_for_official_provider(
        host=host, scheme=parsed.scheme.lower(),
        trust_source=ts, ips=ips,
    ):
        # Note: log host + IPs only — never the Authorization header / key.
        logger.info(
            "official_provider_fake_ip_proxy_allowed host=%s scheme=%s ips=%s",
            host, parsed.scheme.lower(), ips,
        )
        return _allow("official_provider_fake_ip_proxy_allowed", ts,
                      scheme=parsed.scheme.lower(), host=host, port=port,
                      path=parsed.path,
                      resolved_ips=tuple(ips))

    rejected: list[str] = []
    loopback_only = True  # all IPs are loopback under allow_loopback_http
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
            loopback_only = False
        else:
            # non-loopback safe IP (public) → not a pure loopback decision
            loopback_only = False
    if rejected:
        # Rule 8: trusted custom provider hosts (env-configured).
        # Lets a user-declared host (e.g. fake-IP DNS proxy fronting a custom
        # gateway) through when all resolved IPs sit inside the configured
        # LITASSIST_PROXY_FAKE_IP_CIDRS. Both host AND CIDR must be opted in.
        if _host_is_trusted_custom_provider(
            host=host, scheme=parsed.scheme.lower(),
            trust_source=ts, ips=ips,
        ):
            logger.info(
                "trusted_custom_provider_host_allowed host=%s scheme=%s ips=%s",
                host, parsed.scheme.lower(), ips,
            )
            return _allow("trusted_custom_provider_host_allowed", ts,
                          scheme=parsed.scheme.lower(), host=host, port=port,
                          path=parsed.path,
                          resolved_ips=tuple(ips))
        return _reject("dns_resolved_to_unsafe_ip", ts,
                       scheme=parsed.scheme.lower(), host=host, port=port,
                       path=parsed.path,
                       resolved_ips=tuple(ips),
                       rejected_ips=tuple(rejected))

    # Loopback HTTP exception: distinct reason so callers / telemetry
    # can identify local-API decisions (rule 6 of endpoint policy V2).
    if loopback_only and allow_loopback_http and parsed.scheme.lower() == "http":
        return _allow("loopback_http_allowed", ts,
                      scheme=parsed.scheme.lower(), host=host, port=port,
                      path=parsed.path,
                      resolved_ips=tuple(ips))

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

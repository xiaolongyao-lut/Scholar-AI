"""SSRF + trust source tests for provider_endpoint_policy (Slice A2.2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from provider_endpoint_policy import (
    DNSResolutionError,
    PolicyDecision,
    TrustSource,
    all_official_hosts,
    classify_ip,
    validate_endpoint,
)


# ---------------------------------------------------------------------------
# Trust-source decisions
# ---------------------------------------------------------------------------


def test_official_provider_host_match_allows_with_dns(monkeypatch):
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed
    assert d.host == "api.openai.com"


def test_official_provider_host_mismatch_rejected():
    d = validate_endpoint(
        "https://attacker.example.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
        skip_dns=True,
    )
    assert not d.allowed
    assert "host_mismatch" in d.reason


def test_env_configured_gateway_bypasses_official_allowlist(monkeypatch):
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    d = validate_endpoint(
        "https://windhub.cc/v1",
        trust_source=TrustSource.ENV_CONFIGURED_GATEWAY,
    )
    assert d.allowed, f"env gateway should bypass official allowlist; got {d}"


def test_runtime_user_confirmed_bypasses_official_allowlist(monkeypatch):
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["104.18.6.192"],
    )
    d = validate_endpoint(
        "https://api.zhenhaoji.qzz.io/v1",
        trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
    )
    assert d.allowed


@pytest.mark.parametrize(
    "resolved_ip, expected_reason",
    [
        ("127.0.0.1", "loopback"),
        ("10.0.0.7", "private"),
        ("169.254.169.254", "link_local"),
    ],
)
def test_runtime_user_confirmed_still_rejects_unsafe_resolved_ips(
    monkeypatch,
    resolved_ip: str,
    expected_reason: str,
) -> None:
    """User confirmation bypasses only the host allowlist, not SSRF IP checks."""

    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: [resolved_ip],
    )

    d = validate_endpoint(
        "https://user-confirmed.example/v1",
        trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
    )

    assert not d.allowed
    assert "unsafe_ip" in d.reason
    assert any(expected_reason in item for item in d.rejected_ips)


def test_loopback_http_requires_explicit_local_allowance(monkeypatch) -> None:
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["127.0.0.1"],
    )

    rejected = validate_endpoint(
        "http://localhost:11434/v1",
        trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
    )
    allowed = validate_endpoint(
        "http://localhost:11434/v1",
        trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
        allow_loopback_http=True,
    )

    assert not rejected.allowed
    assert "http_scheme_not_allowed_for_remote" in rejected.reason
    assert allowed.allowed
    # Contract upgrade 2026-06-12: loopback path emits distinct reason
    # so telemetry can identify local-API decisions (V2 rule 6).
    assert allowed.reason == "loopback_http_allowed"
    assert allowed.resolved_ips == ("127.0.0.1",)


def test_runtime_untrusted_custom_returns_skipped_network():
    d = validate_endpoint(
        "https://anyrouter.top/v1",
        trust_source=TrustSource.RUNTIME_UNTRUSTED_CUSTOM,
    )
    assert not d.allowed
    assert d.skipped_network is True
    assert "untrusted" in d.reason


# ---------------------------------------------------------------------------
# SSRF reject patterns (plan v2 §14.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url, fragment", [
    ("http://api.openai.com/v1", "http_scheme"),
    ("ftp://api.openai.com/v1", "scheme_not_http"),
    ("https://user:pass@api.openai.com/v1", "userinfo"),
    ("https://api.openai.com/v1?api-version=preview", "query_or_fragment"),
    ("https://api.openai.com/v1#anchor", "query_or_fragment"),
])
def test_url_shape_rejects(url, fragment):
    d = validate_endpoint(url, trust_source=TrustSource.OFFICIAL_PROVIDER, skip_dns=True)
    assert not d.allowed
    assert fragment in d.reason


@pytest.mark.parametrize("ip, why", [
    ("127.0.0.1", "loopback"),
    ("::1", "loopback"),
    ("169.254.169.254", "link_local"),
    ("10.0.0.1", "private"),
    ("172.16.0.1", "private"),
    ("192.168.1.1", "private"),
    ("0.0.0.0", "unspecified"),
    ("224.0.0.1", "multicast"),
])
def test_classify_ip_rejects_unsafe(ip, why):
    assert classify_ip(ip) == why


def test_classify_ip_allows_public():
    assert classify_ip("8.8.8.8") is None
    assert classify_ip("104.18.6.192") is None


def test_dns_resolves_to_loopback_rejected_dns_rebinding(monkeypatch):
    """DNS rebinding defense: provider host on allowlist but DNS returns 127.0.0.1."""
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["127.0.0.1"],
    )
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
    )
    assert not d.allowed
    assert "unsafe_ip" in d.reason
    assert any("loopback" in r for r in d.rejected_ips)


def test_dns_resolves_to_private_ip_rejected(monkeypatch):
    monkeypatch.setattr(
        "provider_endpoint_policy.resolve_host",
        lambda host: ["192.168.0.5"],
    )
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
    )
    assert not d.allowed
    assert "unsafe_ip" in d.reason


def test_dns_failure_fails_closed(monkeypatch):
    """Per Q2 approval: DNS errors => reject, not allow."""
    def raise_(host):
        raise DNSResolutionError("simulated NXDOMAIN")
    monkeypatch.setattr("provider_endpoint_policy.resolve_host", raise_)
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
    )
    assert not d.allowed
    assert "dns_resolution_failed" in d.reason


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_unknown_trust_source_rejected():
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source="totally_made_up",
        skip_dns=True,
    )
    assert not d.allowed
    assert "unknown_trust_source" in d.reason


def test_empty_url_rejected():
    d = validate_endpoint("", trust_source=TrustSource.OFFICIAL_PROVIDER)
    assert not d.allowed
    assert "empty" in d.reason


def test_official_hosts_contain_known_providers():
    hosts = all_official_hosts()
    assert "api.openai.com" in hosts
    assert "api.anthropic.com" in hosts
    assert "ark.cn-beijing.volces.com" in hosts


def test_decision_log_dict_does_not_carry_secrets():
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
        skip_dns=True,
    )
    log = d.as_log_dict()
    assert "api_key" not in log
    assert "Authorization" not in str(log)


def test_skip_dns_passthrough_for_dispatcher_cache():
    d = validate_endpoint(
        "https://api.openai.com/v1",
        trust_source=TrustSource.OFFICIAL_PROVIDER,
        skip_dns=True,
    )
    assert d.allowed
    assert "skip_dns" in d.reason

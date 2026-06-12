# -*- coding: utf-8 -*-
"""Tests for VPN/proxy fake-IP exception in provider_endpoint_policy (V2 rule 7).

Covers GPT-supplied test matrix (12 cases) for endpoint policy V2:
  - default-closed: fake-IP rejected without env flag
  - official-host HTTPS + fake-IP + env on → allowed
  - custom-host + fake-IP → rejected
  - official-host + private/loopback/link-local/CGN → rejected
  - official-host + partial fake-IP (mixed real private) → rejected
  - http official-host + fake-IP → rejected (loopback exception ≠ this exception)
  - http loopback + allow_loopback_http → allowed
  - http 192.168 even with allow_loopback_http → rejected

Mocks ``resolve_host`` to control DNS results deterministically without network.
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _reload_policy():
    """Force reload so env reads happen on each test."""
    from literature_assistant.core import provider_endpoint_policy
    importlib.reload(provider_endpoint_policy)
    return provider_endpoint_policy


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with default-closed fake-IP env."""
    monkeypatch.delenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", raising=False)
    monkeypatch.delenv("LITASSIST_PROXY_FAKE_IP_CIDRS", raising=False)


def _patch_dns(monkeypatch: pytest.MonkeyPatch, module, ips: list[str]) -> None:
    """Mock resolve_host to return the given IPs."""
    monkeypatch.setattr(module, "resolve_host", lambda host: list(ips))


# --------------------------------------------------------------------- #
# 默认关闭(rule 7 env opt-in)
# --------------------------------------------------------------------- #


def test_default_closed_dashscope_fake_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """env unset → DashScope 解析到 198.18 仍被 dns_resolved_to_unsafe_ip 拒。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


# --------------------------------------------------------------------- #
# 开启 fake-IP — 官方 host 放行
# --------------------------------------------------------------------- #


def test_open_dashscope_fake_ip_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """env on + DashScope https + 全 IP 在 198.18/15 → allow + reason fake-IP。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is True, d.reason
    assert d.reason == "official_provider_fake_ip_proxy_allowed"


def test_open_siliconflow_fake_ip_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """SiliconFlow → 198.18.0.85 在范围 → allow。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.85"])
    d = policy.validate_endpoint(
        "https://api.siliconflow.cn/v1/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is True
    assert d.reason == "official_provider_fake_ip_proxy_allowed"


def test_open_openai_fake_ip_allowed_under_env_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """env_configured_gateway 也是 fake-IP 兼容的合法 trust_source。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.1.1"])
    d = policy.validate_endpoint(
        "https://api.openai.com/v1/chat/completions",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
    )
    assert d.allowed is True
    assert d.reason == "official_provider_fake_ip_proxy_allowed"


# --------------------------------------------------------------------- #
# 开启 fake-IP — 但不符合所有条件,仍拒
# --------------------------------------------------------------------- #


def test_open_custom_host_fake_ip_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """evil.example.com → 198.18.0.84 不在官方 allowlist,仍拒。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    # OFFICIAL_PROVIDER trust source 但 host 不在 allowlist → 早在 host
    # allowlist 检查时被拒(`official_provider_host_mismatch`)。
    d = policy.validate_endpoint(
        "https://evil.example.com/api",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is False
    assert d.reason == "official_provider_host_mismatch"


def test_open_custom_host_with_env_gateway_fake_ip_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """env_configured_gateway 跳过 allowlist 检查,但 fake-IP 兼容仍要求官方 host →
    fake-IP 短路不触发 → 走标准 unsafe-IP 拒(non_global)。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    d = policy.validate_endpoint(
        "https://evil.example.com/api",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


def test_open_official_host_private_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方 host → 10.0.0.1(私网)拒。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["10.0.0.1"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


def test_open_official_host_loopback_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方 host → 127.0.0.1 拒(loopback 不在 198.18/15)。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


def test_open_official_host_link_local_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方 host → 169.254.169.254(AWS metadata)拒。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["169.254.169.254"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


def test_open_official_host_cgn_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方 host → 100.64.0.1(RFC 6598 CGN)拒。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["100.64.0.1"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


def test_open_official_host_partial_fake_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方 host 同时解析到 198.18.0.84 + 10.0.0.1 → 拒(rule 7 last bullet)。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84", "10.0.0.1"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    # _all_ips_are_fake_ip_for_official_provider → False (10.0.0.1 不在 fake CIDR)
    # → 走标准 SSRF 拒
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


# --------------------------------------------------------------------- #
# Scheme 边界
# --------------------------------------------------------------------- #


def test_http_official_host_fake_ip_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://dashscope... 即使 fake-IP env on 也拒(rule 7 要求 https)。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    d = policy.validate_endpoint(
        "http://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    # 先在 scheme 检查处被拒(line 296 之后)— http + 非 loopback
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


# --------------------------------------------------------------------- #
# Loopback HTTP(原有行为,本切片不应破坏)
# --------------------------------------------------------------------- #


def test_loopback_http_with_allow_flag_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://127.0.0.1:7997 + allow_loopback_http=True → allowed(rule 6,原行为)。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "http://127.0.0.1:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is True


def test_loopback_http_localhost_with_allow_flag_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://localhost:7997 + allow_loopback_http=True → allowed。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "http://localhost:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is True


def test_http_192_168_rejected_even_with_loopback_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://192.168.1.10 即使 allow_loopback_http=True 也拒。
    loopback 不等于私网,IP 检查时会落到 'private' 分类。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["192.168.1.10"])
    d = policy.validate_endpoint(
        "http://192.168.1.10:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    # 先在 scheme 检查时被拒(host 不是 loopback)。
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


# --------------------------------------------------------------------- #
# Trust source 边界
# --------------------------------------------------------------------- #


def test_untrusted_custom_cannot_use_fake_ip_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """runtime_untrusted_custom + 官方 host + fake-IP env on 仍 skip(早于 fake-IP 检查)。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.RUNTIME_UNTRUSTED_CUSTOM,
    )
    # 早在 trust-source 检查时 skip,fake-IP 检查根本没机会跑
    assert d.allowed is False  # skip is not allow
    assert "untrusted" in d.reason


# --------------------------------------------------------------------- #
# CIDR 自定义
# --------------------------------------------------------------------- #


def test_custom_cidr_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 改 CIDR 到 100.64.0.0/10 + 官方 host 解析到该范围 → allow。
    注意 100.64 在标准 SSRF 检查里是 non_global,这里 fake-IP 短路赢。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    monkeypatch.setenv("LITASSIST_PROXY_FAKE_IP_CIDRS", "100.64.0.0/10")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["100.64.0.1"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is True
    assert d.reason == "official_provider_fake_ip_proxy_allowed"


def test_custom_cidr_invalid_entry_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """坏 CIDR 被静默 skip(WARN 日志),不影响正常 CIDR。"""
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    monkeypatch.setenv("LITASSIST_PROXY_FAKE_IP_CIDRS", "bad-cidr,198.18.0.0/15,also-bad")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    d = policy.validate_endpoint(
        "https://dashscope.aliyuncs.com/api/v1/services/rerank",
        trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
    )
    assert d.allowed is True


# --------------------------------------------------------------------- #
# 安全:日志不打 key
# --------------------------------------------------------------------- #


def test_fake_ip_allow_log_has_no_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """fake-IP 放行日志不应包含 'sk-' 串或 'authorization' 字样。"""
    import logging
    monkeypatch.setenv("LITASSIST_ALLOW_PROXY_FAKE_IP_FOR_OFFICIAL_PROVIDERS", "1")
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["198.18.0.84"])
    with caplog.at_level(logging.INFO, logger="provider_endpoint_policy"):
        policy.validate_endpoint(
            "https://dashscope.aliyuncs.com/api/v1/services/rerank",
            trust_source=policy.TrustSource.OFFICIAL_PROVIDER,
        )
    for record in caplog.records:
        text = record.getMessage().lower()
        assert "sk-" not in text, f"key leaked in log: {record.getMessage()!r}"
        assert "authorization" not in text, f"authorization in log: {record.getMessage()!r}"
        assert "bearer" not in text, f"bearer in log: {record.getMessage()!r}"

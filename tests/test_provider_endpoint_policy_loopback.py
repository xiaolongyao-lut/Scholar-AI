# -*- coding: utf-8 -*-
"""Loopback HTTP exception tests — endpoint policy V2 rule 6 lockdown.

GPT review 2026-06-12:
- 显式 reason ``loopback_http_allowed``,便于 telemetry / 调用方识别本地 API 决策
- 私网 192.168 / 10.x / 172.16 等即使 ``allow_loopback_http=True`` 也拒
- IPv6 loopback ::1 完整支持
- local_rerank_server 只能 bind 127.0.0.1 / localhost / ::1
"""
from __future__ import annotations

import importlib
import sys

import pytest


def _reload_policy():
    from literature_assistant.core import provider_endpoint_policy
    importlib.reload(provider_endpoint_policy)
    return provider_endpoint_policy


def _patch_dns(monkeypatch: pytest.MonkeyPatch, module, ips: list[str]) -> None:
    monkeypatch.setattr(module, "resolve_host", lambda host: list(ips))


# --------------------------------------------------------------------- #
# rule 6:loopback HTTP 允许的 happy path + 显式 reason
# --------------------------------------------------------------------- #


def test_loopback_127_emits_loopback_http_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "http://127.0.0.1:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is True
    assert d.reason == "loopback_http_allowed"


def test_loopback_localhost_emits_loopback_http_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "http://localhost:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is True
    assert d.reason == "loopback_http_allowed"


def test_loopback_ipv6_emits_loopback_http_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """IPv6 字面 ::1 应被识别为 loopback host(走 ipaddress.ip_address path)。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["::1"])
    d = policy.validate_endpoint(
        "http://[::1]:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is True
    assert d.reason == "loopback_http_allowed"


# --------------------------------------------------------------------- #
# rule 6 反例:私网 / 链路本地 / fake-IP 即使 allow_loopback_http=True 也拒
# --------------------------------------------------------------------- #


def test_http_private_192_168_rejected_even_with_loopback_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://192.168.1.10 + allow_loopback_http=True → 在 scheme 检查阶段被拒,
    因为 192.168 不是 loopback host。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["192.168.1.10"])
    d = policy.validate_endpoint(
        "http://192.168.1.10:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


def test_http_private_10_x_rejected_even_with_loopback_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["10.0.0.5"])
    d = policy.validate_endpoint(
        "http://10.0.0.5:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


def test_http_private_172_16_rejected_even_with_loopback_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["172.16.5.10"])
    d = policy.validate_endpoint(
        "http://172.16.5.10:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


def test_http_link_local_169_254_rejected_even_with_loopback_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """169.254.169.254 (cloud metadata) 必须拒。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["169.254.169.254"])
    d = policy.validate_endpoint(
        "http://169.254.169.254/latest/meta-data",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


def test_https_loopback_does_not_emit_loopback_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """https://127.0.0.1 — 不走 loopback exception(那条只对 http);
    走标准 IP classify,127 被分类为 loopback 然后被 classify_ip 拒。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "https://127.0.0.1:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    assert d.allowed is False
    assert d.reason == "dns_resolved_to_unsafe_ip"


def test_loopback_without_allow_flag_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """http://127.0.0.1 但 allow_loopback_http=False → scheme 检查拒。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1"])
    d = policy.validate_endpoint(
        "http://127.0.0.1:7997/rerank",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=False,
    )
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


def test_loopback_mixed_with_real_public_ip_does_not_get_loopback_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """host 解析到 127.0.0.1 + 8.8.8.8(公网)→ 不应被算 loopback_only,
    走标准 ok reason(IP classify 通过)。这是为了避免 DNS rebinding 攻击
    通过混 IP 利用 loopback 例外。"""
    policy = _reload_policy()
    _patch_dns(monkeypatch, policy, ["127.0.0.1", "8.8.8.8"])
    d = policy.validate_endpoint(
        "http://example.com/api",
        trust_source=policy.TrustSource.ENV_CONFIGURED_GATEWAY,
        allow_loopback_http=True,
    )
    # 在 scheme 检查处早被拒(example.com 不是 loopback host 字面)
    assert d.allowed is False
    assert d.reason == "http_scheme_not_allowed_for_remote"


# --------------------------------------------------------------------- #
# local_rerank_server bind 限制
# --------------------------------------------------------------------- #


def test_server_bind_localhost_alias_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--host localhost` 不被拒(localhost 是 loopback 别名)。"""
    pytest.importorskip("fastapi")
    monkeypatch.delenv("LOCAL_RERANK_ALLOW_NON_LOOPBACK", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["local_rerank_server.py", "--host", "localhost", "--port", "0"])
    # 模拟 uvicorn.run 不真起来(由 main 返回前调,monkey patch 短路)
    from literature_assistant.core import local_rerank_server
    monkeypatch.setattr(local_rerank_server, "_build_app", lambda: object())
    # uvicorn.run 也短路
    import uvicorn  # noqa: F401
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    from literature_assistant.core.local_rerank_server import main
    rc = main()
    assert rc == 0


def test_server_bind_ipv6_loopback_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--host ::1` 不被拒。"""
    pytest.importorskip("fastapi")
    monkeypatch.delenv("LOCAL_RERANK_ALLOW_NON_LOOPBACK", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["local_rerank_server.py", "--host", "::1", "--port", "0"])
    from literature_assistant.core import local_rerank_server
    monkeypatch.setattr(local_rerank_server, "_build_app", lambda: object())
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    from literature_assistant.core.local_rerank_server import main
    rc = main()
    assert rc == 0


def test_server_refuse_0_0_0_0_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--host 0.0.0.0` 默认拒。"""
    pytest.importorskip("fastapi")
    monkeypatch.delenv("LOCAL_RERANK_ALLOW_NON_LOOPBACK", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["local_rerank_server.py", "--host", "0.0.0.0", "--port", "7997"])
    from literature_assistant.core.local_rerank_server import main
    rc = main()
    assert rc == 2


def test_server_refuse_public_ip_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--host 192.168.1.10` 即使是私网也拒。"""
    pytest.importorskip("fastapi")
    monkeypatch.delenv("LOCAL_RERANK_ALLOW_NON_LOOPBACK", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["local_rerank_server.py", "--host", "192.168.1.10", "--port", "7997"])
    from literature_assistant.core.local_rerank_server import main
    rc = main()
    assert rc == 2


def test_server_explicit_env_flag_allows_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOCAL_RERANK_ALLOW_NON_LOOPBACK=1 → 允许 0.0.0.0。"""
    pytest.importorskip("fastapi")
    monkeypatch.setenv("LOCAL_RERANK_ALLOW_NON_LOOPBACK", "1")
    monkeypatch.setattr(sys, "argv",
                        ["local_rerank_server.py", "--host", "0.0.0.0", "--port", "0"])
    from literature_assistant.core import local_rerank_server
    monkeypatch.setattr(local_rerank_server, "_build_app", lambda: object())
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: None)
    from literature_assistant.core.local_rerank_server import main
    rc = main()
    assert rc == 0

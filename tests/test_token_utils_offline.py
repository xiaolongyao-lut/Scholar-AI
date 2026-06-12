# -*- coding: utf-8 -*-
"""Unit tests for token_utils offline override(#55).

验证 LITASSIST_TOKEN_UTILS_OFFLINE 环境变量正确触发 char-ratio fallback,
避免离线/防火墙环境下 HuggingFace HTTP retry hang。

不依赖网络 — 通过 monkeypatch + 模块重 import 验证行为。
"""

from __future__ import annotations

import importlib
import os

import pytest


def _reload_token_utils():
    """Force-reload token_utils module so env var change takes effect."""
    from literature_assistant.core import token_utils

    importlib.reload(token_utils)
    return token_utils


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with a clean offline env var."""
    monkeypatch.delenv("LITASSIST_TOKEN_UTILS_OFFLINE", raising=False)


def test_offline_env_var_truthy_skips_tokenizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """LITASSIST_TOKEN_UTILS_OFFLINE=1 → _get_tokenizer 返回 None,不连网。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "1")
    token_utils = _reload_token_utils()

    # 直接调 _get_tokenizer:offline=true 时 transformers 不应被 import,
    # 短路返回 None
    tok = token_utils._get_tokenizer()
    assert tok is None
    assert token_utils._tokenizer_loaded is True


def test_offline_env_var_true_string_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """支持 'true' 字符串(case-insensitive)。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "TRUE")
    token_utils = _reload_token_utils()
    assert token_utils._is_offline_forced() is True
    assert token_utils._get_tokenizer() is None


def test_offline_env_var_yes_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """支持 'yes' 字符串。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "yes")
    token_utils = _reload_token_utils()
    assert token_utils._is_offline_forced() is True


def test_offline_env_var_zero_does_not_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """'0' / 'false' / 'no' / 不设 → 维持原行为(尝试加载)。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "0")
    token_utils = _reload_token_utils()
    assert token_utils._is_offline_forced() is False


def test_offline_env_var_unset_does_not_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """env var 未设 → _is_offline_forced False(原行为)。"""
    monkeypatch.delenv("LITASSIST_TOKEN_UTILS_OFFLINE", raising=False)
    token_utils = _reload_token_utils()
    assert token_utils._is_offline_forced() is False


def test_count_tokens_uses_char_ratio_fallback_when_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """offline=1 时 count_tokens 走 0.75 char-ratio fallback,不连网。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "1")
    token_utils = _reload_token_utils()

    # 16 char → max(1, int(16 * 0.75)) = 12
    assert token_utils.count_tokens("a" * 16) == 12
    # 短 text 不低于 1
    assert token_utils.count_tokens("a") == 1
    # empty 仍返回 0
    assert token_utils.count_tokens("") == 0


def test_truncate_to_tokens_uses_char_ratio_fallback_when_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """offline=1 时 truncate_to_tokens 用 safe_chars=int(max_tokens/0.75)截断。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "1")
    token_utils = _reload_token_utils()

    text = "x" * 100
    # max_tokens=10 → safe_chars = int(10 / 0.75) = 13
    truncated = token_utils.truncate_to_tokens(text, 10)
    assert len(truncated) == 13

    # max_tokens=0 → 空
    assert token_utils.truncate_to_tokens(text, 0) == ""
    # empty input → 空
    assert token_utils.truncate_to_tokens("", 10) == ""


def test_split_by_tokens_offline_chunks_by_char_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """offline=1 时 split_by_tokens 走 char-window 切分,不连网。"""
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "1")
    token_utils = _reload_token_utils()

    # 100 char,max_tokens=10 → safe_chars=13 → 100/13 ≈ 8 块
    text = "x" * 100
    pieces = token_utils.split_by_tokens(text, 10)
    assert len(pieces) >= 7
    assert all(len(p) <= 13 for p in pieces)
    # 拼回应等于原文(无丢失)
    assert "".join(pieces) == text


def test_offline_skip_does_not_import_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    """offline=1 时不应 import transformers — 通过破坏 transformers 模块验证。

    如果 _get_tokenizer 走了 transformers 路径,break 会抛 ImportError 让测试 fail。
    """
    import sys

    # 模拟 transformers 不可用:如果代码尝试 import,会 KeyError
    monkeypatch.setenv("LITASSIST_TOKEN_UTILS_OFFLINE", "1")

    # 故意在 sys.modules 放一个 raise 的占位 — 真 import 会触发
    class BrokenTransformers:
        def __getattr__(self, name: str):
            raise ImportError(f"transformers should not be imported in offline mode (got {name})")

    monkeypatch.setitem(sys.modules, "transformers", BrokenTransformers())  # type: ignore[arg-type]

    token_utils = _reload_token_utils()
    # offline=1 → 直接 None,不 touch transformers
    assert token_utils._get_tokenizer() is None

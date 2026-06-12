# -*- coding: utf-8 -*-
"""Unit tests for key_pool GPT review rule 3 — DISABLED_ARCHIVE skip + provider-specific priority.

Rules locked:
  (a) DISABLED_ARCHIVE block 块内所有 KEY=value 都 skip,即使 #-prefix 被去掉
  (b) provider-specific (SILICONFLOW_*) keys 优先 generic (RERANK_*)
  (c) connectivity probe 不打 raw key (检查 reranker_client/runtime_env 日志)

Each test writes a synthetic .env and parses it,verifying pool content + order.
"""
from __future__ import annotations

import importlib
import logging
import sys

import pytest


def _reload_key_pool():
    from literature_assistant.core import key_pool
    importlib.reload(key_pool)
    return key_pool


# --------------------------------------------------------------------- #
# rule 3(a): DISABLED_ARCHIVE block skip
# --------------------------------------------------------------------- #


def test_disabled_archive_block_skip_commented_keys(tmp_path) -> None:
    """已注释的 archive 块 keys 不进 active pool (legacy 行为锁)。"""
    env = tmp_path / ".env"
    env.write_text(
        "##rerank##\n"
        "## [STATUS:DISABLED_ARCHIVE_2026-04-30] archived block\n"
        "# RERANK_API_KEY=sk-archived-bad-key-do-not-use-aaaaaaaaaaa\n"
        "# RERANK_BASE_URL=https://archived.example.com/v1\n"
        "# RERANK_MODEL=archived-model\n"
        "##rerank##\n"
        "SILICONFLOW_RERANK_API_KEY=sk-active-good-key-bbbbbbbbbbbbb\n"
        "SILICONFLOW_RERANK_BASE_URL=https://api.siliconflow.cn/v1\n"
        "RERANK_MODEL=BAAI/bge-reranker-v2-m3\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    assert len(rerank) == 1
    assert rerank[0].api_key.startswith("sk-active-good-key")
    # archived key 不应出现
    for c in rerank:
        assert "archived" not in c.api_key


def test_disabled_archive_block_skip_uncommented_keys(tmp_path) -> None:
    """**核心防御** — 即使有人不小心把 archived 块的 # 去掉,key 仍不进 pool。
    这是 belt-and-suspenders:防 archive 块被意外激活。"""
    env = tmp_path / ".env"
    env.write_text(
        "##rerank##\n"
        "## [STATUS:DISABLED_ARCHIVE_2026-04-30] still archived\n"
        "RERANK_API_KEY=sk-uncommented-but-archived-cccccccccccc\n"
        "RERANK_BASE_URL=https://archived.example.com/v1\n"
        "RERANK_MODEL=archived-model\n"
        "##rerank##\n"
        "SILICONFLOW_RERANK_API_KEY=sk-active-good-dddddddddddddddd\n"
        "SILICONFLOW_RERANK_BASE_URL=https://api.siliconflow.cn/v1\n"
        "RERANK_MODEL=BAAI/bge-reranker-v2-m3\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    # 即使 # 被去掉,uncommented 的 archived key 仍 skip
    assert len(rerank) == 1
    assert "uncommented" not in rerank[0].api_key
    assert rerank[0].api_key.startswith("sk-active-good")


def test_archive_block_exits_on_next_category_header(tmp_path) -> None:
    """archive 块以下一个 ## category ## header 结束。"""
    env = tmp_path / ".env"
    env.write_text(
        "## [STATUS:DISABLED_ARCHIVE_2026-04-30] block 1\n"
        "RERANK_API_KEY=sk-skip1-eeeeeeeeeeeeeeeeeeeeeeee\n"
        "##rerank##\n"
        "SILICONFLOW_RERANK_API_KEY=sk-active2-ffffffffffffffffff\n"
        "SILICONFLOW_RERANK_BASE_URL=https://api.siliconflow.cn/v1\n"
        "RERANK_MODEL=BAAI/bge-reranker-v2-m3\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    assert len(rerank) == 1
    assert "skip1" not in rerank[0].api_key


def test_archive_block_exits_on_provider_header(tmp_path) -> None:
    """archive 块以下一个 provider header(##阿里云##)结束。"""
    env = tmp_path / ".env"
    env.write_text(
        "## [STATUS:DISABLED_ARCHIVE_2026-04-30] archived\n"
        "RERANK_API_KEY=sk-skip-gggggggggggggggggggggg\n"
        "## 阿里云官方 ##\n"
        "##rerank##\n"
        "DASHSCOPE_RERANK_API_KEY=sk-active-hhhhhhhhhhhhhhh\n"
        "DASHSCOPE_RERANK_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank\n"
        "RERANK_MODEL=gte-rerank-v2\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    assert len(rerank) == 1
    assert "skip" not in rerank[0].api_key


# --------------------------------------------------------------------- #
# rule 3(b): provider-specific 优先 generic
# --------------------------------------------------------------------- #


def test_provider_specific_key_sorts_before_generic(tmp_path) -> None:
    """RERANK_API_KEY (generic, line 1) + SILICONFLOW_RERANK_API_KEY (specific, line 5)
    → SILICONFLOW 排在 RERANK 前面,虽然 line_no 大。"""
    env = tmp_path / ".env"
    env.write_text(
        "##rerank##\n"
        "RERANK_API_KEY=sk-generic-aaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "RERANK_BASE_URL=https://generic.example.com/v1\n"
        "RERANK_MODEL=generic-model\n"
        "##rerank##\n"
        "SILICONFLOW_RERANK_API_KEY=sk-specific-bbbbbbbbbbbbbb\n"
        "SILICONFLOW_RERANK_BASE_URL=https://api.siliconflow.cn/v1\n"
        "RERANK_MODEL=BAAI/bge-reranker-v2-m3\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    assert len(rerank) == 2
    # specific 排第一
    assert rerank[0].is_provider_specific_key is True
    assert rerank[0].key_var_name == "SILICONFLOW_RERANK_API_KEY"
    assert "specific" in rerank[0].api_key
    # generic 排第二
    assert rerank[1].is_provider_specific_key is False
    assert rerank[1].key_var_name == "RERANK_API_KEY"
    assert "generic" in rerank[1].api_key


def test_generic_only_preserves_line_order(tmp_path) -> None:
    """全 generic 时仍保持 .env 行顺序(legacy 行为不变)。"""
    env = tmp_path / ".env"
    env.write_text(
        "##rerank##\n"
        "RERANK_API_KEY=sk-first-iiiiiiiiiiiiiiiiiiiiii\n"
        "RERANK_BASE_URL=https://first.example.com/v1\n"
        "RERANK_MODEL=first-model\n"
        "##rerank##\n"
        "RERANK_API_KEY=sk-second-jjjjjjjjjjjjjjjjjjjjjj\n"
        "RERANK_BASE_URL=https://second.example.com/v1\n"
        "RERANK_MODEL=second-model\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    assert len(rerank) == 2
    assert "first" in rerank[0].api_key
    assert "second" in rerank[1].api_key


def test_multiple_specific_keeps_line_order_within_group(tmp_path) -> None:
    """多个 provider-specific 之间仍按 .env 行序(group 内 stable sort)。"""
    env = tmp_path / ".env"
    env.write_text(
        "##rerank##\n"
        "RERANK_API_KEY=sk-generic-kkkkkkkkkkkkkkkkkkkkkk\n"
        "RERANK_BASE_URL=https://generic.example.com/v1\n"
        "RERANK_MODEL=generic-m\n"
        "##rerank##\n"
        "DASHSCOPE_RERANK_API_KEY=sk-dashscope-lllllllllllllll\n"
        "DASHSCOPE_RERANK_BASE_URL=https://dashscope.example.com/v1\n"
        "RERANK_MODEL=gte-rerank-v2\n"
        "##rerank##\n"
        "SILICONFLOW_RERANK_API_KEY=sk-siliconflow-mmmmmmmmmmm\n"
        "SILICONFLOW_RERANK_BASE_URL=https://api.siliconflow.cn/v1\n"
        "RERANK_MODEL=BAAI/bge-reranker-v2-m3\n",
        encoding="utf-8",
    )
    key_pool = _reload_key_pool()
    pools = key_pool.parse_env_pools(str(env))
    rerank = pools.get("rerank") or []
    assert len(rerank) == 3
    # dashscope (line earlier) 先于 siliconflow (line later) — group 内保持 line 序
    assert "dashscope" in rerank[0].api_key
    assert "siliconflow" in rerank[1].api_key
    # generic 殿后
    assert "generic" in rerank[2].api_key


# --------------------------------------------------------------------- #
# Credential.is_provider_specific_key 边界
# --------------------------------------------------------------------- #


def test_is_provider_specific_key_recognizes_all_specific_forms() -> None:
    """已知 provider-specific env var name 都返回 True。"""
    key_pool = _reload_key_pool()
    for name in (
        "SILICONFLOW_RERANK_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "SILICONFLOW_EMBEDDING_API_KEY",
        "SILICONFLOW_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "JINA_API_KEY",
        "ARK_API_KEY",
        "VOLCANO_API_KEY",
    ):
        c = key_pool.Credential(
            category="rerank", provider="x", api_key="k", base_url="u",
            model="m", line_no=1, key_var_name=name,
        )
        assert c.is_provider_specific_key is True, f"{name} should be specific"


def test_is_provider_specific_key_recognizes_generic_forms() -> None:
    """已知 generic env var name 都返回 False。"""
    key_pool = _reload_key_pool()
    for name in ("RERANK_API_KEY", "EMBEDDING_API_KEY", "API_KEY", "KEY", ""):
        c = key_pool.Credential(
            category="rerank", provider="x", api_key="k", base_url="u",
            model="m", line_no=1, key_var_name=name,
        )
        assert c.is_provider_specific_key is False, f"{name} should be generic"


# --------------------------------------------------------------------- #
# rule 3(c): connectivity probe masked key (regression for log layer)
# --------------------------------------------------------------------- #


def test_probe_log_uses_masked_key_format() -> None:
    """reranker_client._probe_rerank_key 日志格式应含 ***suffix 不含原 key。
    这是合规性测试,grep 源代码确认。"""
    from pathlib import Path
    src = Path("literature_assistant/core/reranker_client.py").read_text(encoding="utf-8")
    # 必须有 masked log 模式
    assert "key_suffix=***%s" in src or "key_suffix=***" in src
    # 验证没有 raw key 在 logger 调用里
    import re
    # 找所有 logger.xxx 调用,查参数列表里是否含 api_key / candidate_key 原文
    matches = re.findall(r"logger\.(?:info|warning|error|debug)\([^)]+?\)", src)
    for m in matches:
        # 允许 key_len, key_suffix, masked 形式
        # 不允许 'key', %s, candidate_key 直传(它们是 raw key 名)
        if "api_key" in m and "key_suffix" not in m and "key_len" not in m:
            pytest.fail(f"raw api_key in logger call: {m[:200]}")


def test_probe_log_embedding_uses_masked_key_format() -> None:
    """runtime_env._probe_embedding_key 同款。"""
    from pathlib import Path
    src = Path("literature_assistant/core/runtime_env.py").read_text(encoding="utf-8")
    assert "key_suffix=***" in src

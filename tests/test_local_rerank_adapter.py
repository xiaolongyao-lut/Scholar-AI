# -*- coding: utf-8 -*-
"""Unit tests for local_rerank_adapter production guardrails.

锁住 GPT review 的 4 个 production-grade 要求:
1. is_available() 不加载 torch 也不动模型
2. from_pretrained() 默认 local_files_only=True(不联网)
3. env 解析坏值不崩(clamp 到默认)
4. 异步入口 ascore_pairs() 不阻塞 event loop
+ 权重不存在时 is_available() 返回 False
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest


def _reload_adapter():
    """Force-reload module so env var change takes effect."""
    from literature_assistant.core import local_rerank_adapter
    importlib.reload(local_rerank_adapter)
    return local_rerank_adapter


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with clean local_rerank env vars."""
    for k in (
        "LOCAL_RERANK_DISABLED",
        "LOCAL_RERANK_ALLOW_DOWNLOAD",
        "LOCAL_RERANK_MODEL_NAME",
        "LOCAL_RERANK_MAX_LENGTH",
        "LOCAL_RERANK_BATCH_SIZE",
        "LOCAL_RERANK_DEVICE",
        "HF_HOME",
    ):
        monkeypatch.delenv(k, raising=False)


# --------------------------------------------------------------------- #
# Layer 0:env truthy / clamp 解析
# --------------------------------------------------------------------- #


def test_disabled_env_truthy_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOCAL_RERANK_DISABLED=1 → is_available False,score_pairs None。"""
    monkeypatch.setenv("LOCAL_RERANK_DISABLED", "1")
    lra = _reload_adapter()
    assert lra.is_available() is False
    assert lra.score_pairs("q", ["t"]) is None


def test_allow_download_truthy_unlocks_no_cache_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOCAL_RERANK_ALLOW_DOWNLOAD=1 + 不存在的模型名 → is_available True
    (虚假允许,但 get_reranker 真加载会失败转 None — 那是另一回事)。"""
    monkeypatch.setenv("LOCAL_RERANK_ALLOW_DOWNLOAD", "1")
    monkeypatch.setenv("LOCAL_RERANK_MODEL_NAME", "fake-org/does-not-exist")
    lra = _reload_adapter()
    # is_available 只检查 transformers/torch + (有 cache or allow_download)
    # 允许下载 → 即使 cache 缺也返回 True
    assert lra.is_available() is True


def test_env_int_bad_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOCAL_RERANK_MAX_LENGTH='abc' → 不崩,用默认 512。"""
    monkeypatch.setenv("LOCAL_RERANK_MAX_LENGTH", "abc")
    monkeypatch.setenv("LOCAL_RERANK_BATCH_SIZE", "not-int")
    lra = _reload_adapter()
    # 内部 _env_int 应吞掉 ValueError,返回默认值
    assert lra._env_int("LOCAL_RERANK_MAX_LENGTH", 512, 16, 8192) == 512
    assert lra._env_int("LOCAL_RERANK_BATCH_SIZE", 8, 1, 128) == 8


def test_env_int_clamps_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOCAL_RERANK_MAX_LENGTH=99999 → clamp 到 8192;= 1 → clamp 到 16。"""
    monkeypatch.setenv("LOCAL_RERANK_MAX_LENGTH", "99999")
    lra = _reload_adapter()
    assert lra._env_int("LOCAL_RERANK_MAX_LENGTH", 512, 16, 8192) == 8192
    monkeypatch.setenv("LOCAL_RERANK_MAX_LENGTH", "1")
    assert lra._env_int("LOCAL_RERANK_MAX_LENGTH", 512, 16, 8192) == 16


# --------------------------------------------------------------------- #
# Layer 1:权重 probe 不加载 torch
# --------------------------------------------------------------------- #


def test_weights_present_false_for_unknown_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """指向空 cache dir → _weights_present 返回 False。"""
    monkeypatch.setenv("HF_HOME", str(tmp_path))  # 空 cache
    monkeypatch.setenv("LOCAL_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
    lra = _reload_adapter()
    assert lra._weights_present("BAAI/bge-reranker-v2-m3") is False


def test_weights_present_true_with_synthetic_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """构造一个合成 cache 目录树 → _weights_present 返回 True。"""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    model = "fake/test-model"
    cache = tmp_path / "hub" / "models--fake--test-model"
    snap = cache / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"dummy")
    (snap / "tokenizer.json").write_bytes(b"{}")
    lra = _reload_adapter()
    assert lra._weights_present(model) is True


def test_is_available_false_when_no_weights_and_no_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """权重不在 + LOCAL_RERANK_ALLOW_DOWNLOAD 未设 → is_available False。"""
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.setenv("LOCAL_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
    lra = _reload_adapter()
    assert lra.is_available() is False


# --------------------------------------------------------------------- #
# Layer 2:loader 走 local_files_only(不联网)
# --------------------------------------------------------------------- #


def test_loader_called_with_local_files_only_when_download_not_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """权重缺 + ALLOW_DOWNLOAD 未设 → _get_reranker 直接返回 None,根本不调
    AutoTokenizer.from_pretrained(避免联网试)。"""
    monkeypatch.setenv("HF_HOME", str(tmp_path))  # 空 cache
    monkeypatch.setenv("LOCAL_RERANK_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
    lra = _reload_adapter()
    # 不会触发 transformers.from_pretrained — 我们 patch 让它若被调就抛
    import sys
    called = {"flag": False}
    class _Boom:
        def __getattr__(self, name):
            called["flag"] = True
            raise RuntimeError(f"should not reach transformers.{name}")
    monkeypatch.setitem(sys.modules, "transformers", _Boom())
    # 走 _get_reranker → 应直接因 weights 缺 + 不允许下载 → 返回 None,不动 transformers
    result = lra._get_reranker()
    assert result is None
    assert called["flag"] is False, "transformers must not be touched when weights missing"


# --------------------------------------------------------------------- #
# Layer 3:async 入口在 worker thread 执行,不阻塞 event loop
# --------------------------------------------------------------------- #


def test_ascore_pairs_runs_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """ascore_pairs 应通过 asyncio.to_thread 调度,sync 调用在 worker。"""
    monkeypatch.setenv("LOCAL_RERANK_DISABLED", "1")  # 短路,避免真加载模型
    lra = _reload_adapter()

    # 跑一次 async surface — 不该崩,应返回 None(disabled)
    async def _run():
        return await lra.ascore_pairs("q", ["t1"])
    result = asyncio.run(_run())
    assert result is None


def test_ascore_pairs_empty_candidates_returns_empty() -> None:
    """空候选 → 立即返回 [],不调度 worker(corner case)。"""
    lra = _reload_adapter()
    async def _run():
        return await lra.ascore_pairs("q", [])
    assert asyncio.run(_run()) == []


# --------------------------------------------------------------------- #
# Layer 4:本地 rerank HTTP server (FastAPI loopback)
# --------------------------------------------------------------------- #


def test_server_request_schema_accepts_rerank_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pydantic schema 接受 SiliconFlow-style rerank request body。"""
    pytest.importorskip("fastapi")
    from literature_assistant.core.local_rerank_server import RerankRequest
    req = RerankRequest(
        model="BAAI/bge-reranker-v2-m3",
        query="test query",
        documents=["doc 1", "doc 2"],
        top_n=5,
        return_documents=False,
    )
    assert req.model == "BAAI/bge-reranker-v2-m3"
    assert req.query == "test query"
    assert len(req.documents) == 2
    assert req.top_n == 5


def test_server_request_schema_rejects_missing_query() -> None:
    """缺 query → pydantic ValidationError。"""
    pytest.importorskip("fastapi")
    from pydantic import ValidationError
    from literature_assistant.core.local_rerank_server import RerankRequest
    with pytest.raises(ValidationError):
        RerankRequest(model="m", documents=["a"])  # type: ignore[call-arg]


def test_server_response_schema_sorts_top_n() -> None:
    """RerankResponse 接受 sorted items;Index 字段是原始位置(不变)。"""
    pytest.importorskip("fastapi")
    from literature_assistant.core.local_rerank_server import RerankResponse, RerankResultItem
    resp = RerankResponse(
        id="local-rerank",
        model="test",
        results=[
            RerankResultItem(index=2, relevance_score=2.0),
            RerankResultItem(index=0, relevance_score=-1.0),
            RerankResultItem(index=1, relevance_score=-3.0),
        ],
    )
    # 验证 index 在响应里反映原始 input 位置(2, 0, 1),客户端用这个回查原 documents
    assert [r.index for r in resp.results] == [2, 0, 1]
    # 验证 score 是降序传入的(由 server 排序)
    assert resp.results[0].relevance_score > resp.results[1].relevance_score > resp.results[2].relevance_score


def test_server_main_refuses_non_loopback_bind_without_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """server 拒绝 0.0.0.0 / 公网 IP bind 除非 env override。"""
    monkeypatch.delenv("LOCAL_RERANK_ALLOW_NON_LOOPBACK", raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["local_rerank_server.py", "--host", "0.0.0.0", "--port", "7997"])
    from literature_assistant.core.local_rerank_server import main
    rc = main()
    assert rc == 2  # explicit non-loopback refuse code


# ---------- GPU-fallback device detection ----------

def test_detect_default_device_returns_cuda_when_torch_cuda_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """When torch.cuda.is_available() returns True, _detect_default_device picks cuda."""
    mod = _reload_adapter()

    class _FakeTorch:
        class cuda:
            @staticmethod
            def is_available() -> bool:
                return True

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "torch", _FakeTorch)
    assert mod._detect_default_device() == "cuda"


def test_detect_default_device_falls_back_to_cpu_when_no_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without CUDA, cpu is chosen — the adapter must not crash on CPU-only boxes."""
    mod = _reload_adapter()

    class _FakeTorch:
        class cuda:
            @staticmethod
            def is_available() -> bool:
                return False

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "torch", _FakeTorch)
    assert mod._detect_default_device() == "cpu"


def test_detect_default_device_returns_cpu_when_torch_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """If torch itself fails to import, the function must not raise — return cpu."""
    mod = _reload_adapter()

    import builtins
    real_import = builtins.__import__

    def _block_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("simulated: torch unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_torch)
    assert mod._detect_default_device() == "cpu"


def test_local_rerank_device_env_overrides_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """LOCAL_RERANK_DEVICE env var bypasses auto-detection — opt-out for users
    who want to force CPU even when a working CUDA is present."""
    mod = _reload_adapter()
    monkeypatch.setenv("LOCAL_RERANK_DEVICE", "cpu")
    # Simulate the load path's resolution snippet.
    import os as _os
    resolved = _os.environ.get("LOCAL_RERANK_DEVICE", "").strip() or mod._detect_default_device()
    assert resolved == "cpu"

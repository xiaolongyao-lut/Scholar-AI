from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.eval.run_pinned_rerank_manifest import dry_run_manifest


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_manifest(tmp_path: Path) -> dict[str, Any]:
    queries = tmp_path / "queries.jsonl"
    qrels = tmp_path / "qrels.jsonl"
    queries.write_text('{"query_id":"q1","query_text":"laser"}\n', encoding="utf-8")
    qrels.write_text('{"query_id":"q1","chunk_id":"c1"}\n', encoding="utf-8")

    return {
        "inputs": {
            "queries_path": str(queries),
            "qrels_path": str(qrels),
            "queries_nonempty_lines": 1,
        },
        "outputs": {
            "metrics_path": str(tmp_path / "out" / "metrics.json"),
            "progress_path": str(tmp_path / "out" / "progress.jsonl"),
            "per_query_output": str(tmp_path / "out" / "per_query.jsonl"),
            "rerank_trace_output": str(tmp_path / "out" / "rerank_trace.jsonl"),
            "resume_guard_path": str(tmp_path / "out" / "resume_config.json"),
            "run_log_path": str(tmp_path / "out" / "run.log"),
        },
        "retrieval_config": {
            "use_rerank": True,
            "top_k": 5,
            "rerank_top_n": 40,
            "query_concurrency": 16,
        },
        "runtime_env_overrides": {
            "DASHSCOPE_RERANK_BASE_URL": (
                "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
            ),
            "DASHSCOPE_RERANK_MODEL": "qwen3-rerank",
            "RAG_RUNTIME_RERANK_ENABLED": "1",
        },
        "reranker": {
            "model": "qwen3-rerank",
        },
    }


def test_dry_run_manifest_accepts_guarded_rerank_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, _base_manifest(tmp_path))

    report = dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)

    assert report["status"] == "ok"
    assert report["queries_nonempty_lines"] == 1
    assert report["qrels_nonempty_lines"] == 1
    assert report["retrieval_config"]["use_rerank"] is True
    assert report["runtime_rerank_opt_in"] is True
    assert report["pinned_reranker"]["model"] == "qwen3-rerank"
    assert report["stale_outputs"] == []


def test_dry_run_manifest_rejects_missing_runtime_opt_in(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["runtime_env_overrides"].pop("RAG_RUNTIME_RERANK_ENABLED")
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="RAG_RUNTIME_RERANK_ENABLED=1"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_duplicate_outputs(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["outputs"]["run_log_path"] = manifest["outputs"]["metrics_path"]
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="output paths must be unique"):
        dry_run_manifest(manifest_path)

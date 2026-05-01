from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.eval.run_pinned_rerank_manifest import dry_run_manifest, run_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_MANIFEST = (
    REPO_ROOT / "workspace_tests" / "evaluation_manifests" / "rerank_canary_dry_run_sample.json"
)


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
            "qrels_nonempty_lines": 1,
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
        "safety": {
            "requires_paired_no_rerank_control": False,
        },
    }


def _paired_control_manifest(tmp_path: Path) -> dict[str, Any]:
    manifest = _base_manifest(tmp_path)
    manifest["paired_control"] = {
        "inputs": dict(manifest["inputs"]),
        "outputs": {
            "metrics_path": str(tmp_path / "control" / "metrics.json"),
            "progress_path": str(tmp_path / "control" / "progress.jsonl"),
            "per_query_output": str(tmp_path / "control" / "per_query.jsonl"),
            "rerank_trace_output": str(tmp_path / "control" / "rerank_trace.jsonl"),
            "resume_guard_path": str(tmp_path / "control" / "resume_config.json"),
            "run_log_path": str(tmp_path / "control" / "run.log"),
        },
        "retrieval_config": {
            "use_rerank": False,
            "top_k": 5,
            "recall_top_n": 100,
            "query_concurrency": 16,
        },
        "runtime_env_overrides": {
            "RAG_RUNTIME_RERANK_ENABLED": "0",
        },
    }
    return manifest


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


def test_dry_run_manifest_rejects_string_false_rerank_flag(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["retrieval_config"]["use_rerank"] = "false"
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="use_rerank=true"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_duplicate_outputs(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["outputs"]["run_log_path"] = manifest["outputs"]["metrics_path"]
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="output paths must be unique"):
        dry_run_manifest(manifest_path)


def test_run_manifest_reuses_preflight_before_mutating_outputs(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["outputs"]["run_log_path"] = manifest["outputs"]["metrics_path"]
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="output paths must be unique"):
        run_manifest(manifest_path)

    assert not (tmp_path / "out").exists()


def test_dry_run_manifest_accepts_paired_no_rerank_control(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, _paired_control_manifest(tmp_path))

    report = dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)

    assert report["status"] == "ok"
    assert report["paired_control"]["status"] == "ok"
    assert report["paired_control"]["retrieval_config"]["use_rerank"] is False
    assert report["paired_control"]["queries_path"] == report["queries_path"]
    assert report["paired_control"]["qrels_path"] == report["qrels_path"]
    assert report["paired_control"]["stale_outputs"] == []


def test_dry_run_manifest_enforces_required_paired_control(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["safety"]["requires_paired_no_rerank_control"] = True
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="requires paired_control"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_paired_control_with_rerank_enabled(tmp_path: Path) -> None:
    manifest = _paired_control_manifest(tmp_path)
    manifest["paired_control"]["retrieval_config"]["use_rerank"] = True
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="Control retrieval_config.use_rerank must be false"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_requires_explicit_paired_control_rerank_flag(tmp_path: Path) -> None:
    manifest = _paired_control_manifest(tmp_path)
    manifest["paired_control"]["retrieval_config"].pop("use_rerank")
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="must be set explicitly"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_paired_control_query_mismatch(tmp_path: Path) -> None:
    manifest = _paired_control_manifest(tmp_path)
    other_queries = tmp_path / "other_queries.jsonl"
    other_queries.write_text('{"query_id":"q2","query_text":"arc"}\n', encoding="utf-8")
    manifest["paired_control"]["inputs"]["queries_path"] = str(other_queries)
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="Control queries_path must match"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_paired_control_output_overlap(tmp_path: Path) -> None:
    manifest = _paired_control_manifest(tmp_path)
    manifest["paired_control"]["outputs"]["metrics_path"] = manifest["outputs"]["metrics_path"]
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="must not overlap rerank outputs"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_paired_control_config_drift(tmp_path: Path) -> None:
    manifest = _paired_control_manifest(tmp_path)
    manifest["paired_control"]["retrieval_config"]["top_k"] = 3
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="Control retrieval_config.top_k must match"):
        dry_run_manifest(manifest_path, require_runtime_rerank_opt_in=True)


def test_dry_run_manifest_rejects_query_count_mismatch(tmp_path: Path) -> None:
    manifest = _base_manifest(tmp_path)
    manifest["inputs"]["queries_nonempty_lines"] = 2
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="queries_nonempty_lines mismatch"):
        dry_run_manifest(manifest_path)


def test_repository_sample_manifest_stays_dry_run_safe() -> None:
    sample_text = SAMPLE_MANIFEST.read_text(encoding="utf-8")

    assert "sk-" not in sample_text
    assert "api_key" not in sample_text.lower()

    report = dry_run_manifest(SAMPLE_MANIFEST, require_runtime_rerank_opt_in=True)

    assert report["status"] == "ok"
    assert report["queries_nonempty_lines"] == 30
    assert report["qrels_nonempty_lines"] == 40
    assert report["runtime_rerank_opt_in"] is True
    assert report["paired_control"]["retrieval_config"]["use_rerank"] is False
    metrics_path = Path(str(report["output_paths"]["metrics_path"]))
    assert metrics_path.parts[:3] == ("workspace_artifacts", "generated", "eval")

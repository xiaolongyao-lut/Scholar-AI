from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from chunk_vector_store import EMBEDDING_DIM, _build_manifest
from chunk_size_guard import filter_embedding_safe_chunks
from tools.eval.wiki_cache_corpus_preflight import (
    CacheCorpusPreflightError,
    build_cache_corpus_preflight,
    evaluate_manifest,
    load_chunks_from_chunk_store,
    summarize_chunks,
    write_preflight_payload,
)
from tools.eval.wiki_canary_corpus_source_locator import (
    build_canary_corpus_source_locator,
    inspect_runtime_chunk_store_root,
)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _sample_chunks() -> list[dict[str, Any]]:
    return [
        {"chunk_id": "c1", "material_id": "m1", "content": "[ctx] laser welding stability"},
        {"chunk_id": "c2", "material_id": "m2", "content": "[ctx] melt pool dynamics"},
    ]


def test_evaluate_manifest_passes_when_hash_count_shape_and_context_match(tmp_path: Path) -> None:
    chunks = _sample_chunks()
    embeddings = np.ones((2, EMBEDDING_DIM), dtype=np.float32)
    manifest_path = _write_json(tmp_path / "cache.manifest.json", _build_manifest(chunks, embeddings, model="m"))

    result = evaluate_manifest(manifest_path, summarize_chunks(chunks))

    assert result["status"] == "PASS"
    assert result["failure_reasons"] == []
    assert result["checks"]["chunks_hash_match"] is True
    assert result["checks"]["contextual_match"] is True


def test_evaluate_manifest_fails_for_stale_chunk_hash(tmp_path: Path) -> None:
    chunks = _sample_chunks()
    manifest_payload = _build_manifest(chunks, np.ones((2, EMBEDDING_DIM), dtype=np.float32), model="m")
    manifest_payload["chunks_hash"] = "stale"
    manifest_path = _write_json(tmp_path / "cache.manifest.json", manifest_payload)

    result = evaluate_manifest(manifest_path, summarize_chunks(chunks))

    assert result["status"] == "FAIL"
    assert "chunks_hash_match" in result["failure_reasons"]


def test_load_chunks_from_chunk_store_reads_v2_manifest_materials(tmp_path: Path) -> None:
    project_dir = tmp_path / "chunk_store" / "project"
    _write_jsonl(project_dir / "a.jsonl", [{"chunk_id": "b", "content": "B"}])
    _write_jsonl(project_dir / "b.jsonl", [{"chunk_id": "a", "content": "A"}])
    _write_json(
        project_dir / "manifest.json",
        {
            "version": 2,
            "materials": {
                "mat-b": {"relative_path": "a.jsonl", "total_chunks": 1},
                "mat-a": {"relative_path": "b.jsonl", "total_chunks": 1},
            },
        },
    )

    chunks = load_chunks_from_chunk_store(project_dir)

    assert [chunk["chunk_id"] for chunk in chunks] == ["a", "b"]


def test_load_chunks_from_chunk_store_rejects_escape_path(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "../outside.jsonl"}}},
    )

    with pytest.raises(CacheCorpusPreflightError, match="escapes"):
        load_chunks_from_chunk_store(project_dir)


def test_build_cache_corpus_preflight_reports_no_manifest(tmp_path: Path) -> None:
    corpus = _write_json(tmp_path / "corpus.json", {"chunks": _sample_chunks()})

    payload = build_cache_corpus_preflight(corpus_json=corpus, cache_dirs=[tmp_path / "empty"])

    assert payload["status"] == "NO_MANIFEST"
    assert payload["manifest_count"] == 0
    assert payload["mode"] == "read_only_no_embedding_calls"


def test_build_cache_corpus_preflight_scans_multiple_cache_dirs(tmp_path: Path) -> None:
    chunks = _sample_chunks()
    corpus = _write_json(tmp_path / "corpus.json", {"chunks": chunks})
    cache_a = tmp_path / "cache-a"
    cache_b = tmp_path / "cache-b"
    _write_json(cache_a / "a.manifest.json", _build_manifest(chunks, np.ones((2, EMBEDDING_DIM), dtype=np.float32)))
    stale_manifest = _build_manifest(chunks, np.ones((2, EMBEDDING_DIM), dtype=np.float32))
    stale_manifest["chunk_count"] = 1
    _write_json(cache_b / "b.manifest.json", stale_manifest)

    payload = build_cache_corpus_preflight(corpus_json=corpus, cache_dirs=[cache_a, cache_b])

    assert payload["manifest_count"] == 2
    assert payload["pass_count"] == 1
    assert payload["fail_count"] == 1
    assert payload["status"] == "FAIL"


def test_build_cache_corpus_preflight_fails_stale_manifest(tmp_path: Path) -> None:
    chunks = _sample_chunks()
    corpus = _write_json(tmp_path / "corpus.json", {"chunks": chunks})
    manifest_payload = _build_manifest(chunks, np.ones((2, EMBEDDING_DIM), dtype=np.float32), model="m")
    manifest_payload["chunk_count"] = 1
    manifest_payload["embedding_shape"] = [1, EMBEDDING_DIM]
    manifest_path = _write_json(tmp_path / "cache.manifest.json", manifest_payload)

    payload = build_cache_corpus_preflight(corpus_json=corpus, manifest_paths=[manifest_path])

    assert payload["status"] == "FAIL"
    assert payload["fail_count"] == 1
    assert "chunk_count_match" in payload["manifest_evaluations"][0]["failure_reasons"]


def test_write_preflight_payload_sorts_keys(tmp_path: Path) -> None:
    output = write_preflight_payload({"b": 2, "a": 1}, tmp_path / "out.json")

    assert output.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_inspect_runtime_chunk_store_root_aggregates_v2_projects_without_dedupe(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    for project_id, content in [("proj-b", "B"), ("proj-a", "A")]:
        project_dir = root / project_id
        _write_jsonl(project_dir / "mat.jsonl", [{"chunk_id": "same", "content": content}])
        _write_json(
            project_dir / "manifest.json",
            {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 1}}},
        )

    report = inspect_runtime_chunk_store_root(root)

    assert report["v2_project_count"] == 2
    assert report["runtime_summary"]["chunk_count"] == 2
    assert [project["project_id"] for project in report["v2_projects"]] == ["proj-a", "proj-b"]


def test_inspect_runtime_chunk_store_root_skips_legacy_when_matching_v2_project_exists(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    project_dir = root / "proj"
    _write_jsonl(project_dir / "mat.jsonl", [{"chunk_id": "v2", "content": "A"}])
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 1}}},
    )
    _write_json(root / "proj_chunks.json", {"mat": [{"chunk_id": "legacy", "content": "B"}]})

    report = inspect_runtime_chunk_store_root(root)

    assert report["runtime_summary"]["chunk_count"] == 1
    assert report["legacy_json_count"] == 0
    assert report["skipped_legacy_count"] == 1
    assert report["skipped_legacy_files"][0]["reason"] == "v2_project_preferred"


def test_build_canary_corpus_source_locator_matches_runtime_root_manifest(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    project_dir = root / "proj"
    chunks = [{"chunk_id": "c1", "content": "[ctx] laser"}, {"chunk_id": "c2", "content": "[ctx] weld"}]
    _write_jsonl(project_dir / "mat.jsonl", chunks)
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 2}}},
    )
    manifest_path = _write_json(
        tmp_path / "cache" / "corpus_embeddings_contextual.manifest.json",
        _build_manifest(chunks, np.ones((2, EMBEDDING_DIM), dtype=np.float32), model="m"),
    )

    payload = build_canary_corpus_source_locator(chunk_store_roots=[root], manifest_paths=[manifest_path])

    assert payload["status"] == "PASS"
    assert payload["matching_root_count"] == 1
    assert payload["root_reports"][0]["pass_count"] == 1
    assert payload["root_reports"][0]["matching_manifests"] == [str(manifest_path.resolve()).replace("\\", "/")]


def test_build_canary_corpus_source_locator_reports_no_match_for_stale_manifest(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    project_dir = root / "proj"
    chunks = [{"chunk_id": "c1", "content": "[ctx] laser"}]
    _write_jsonl(project_dir / "mat.jsonl", chunks)
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 1}}},
    )
    stale_manifest = _build_manifest(chunks, np.ones((1, EMBEDDING_DIM), dtype=np.float32), model="m")
    stale_manifest["chunks_hash"] = "stale"
    manifest_path = _write_json(tmp_path / "cache" / "corpus_embeddings_contextual.manifest.json", stale_manifest)

    payload = build_canary_corpus_source_locator(chunk_store_roots=[root], manifest_paths=[manifest_path])

    assert payload["status"] == "NO_MATCH"
    assert payload["root_reports"][0]["fail_count"] == 1
    assert "chunks_hash_match" in payload["root_reports"][0]["manifest_evaluations"][0]["failure_reasons"]


def test_build_canary_corpus_source_locator_reports_single_group_repair_candidate(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    keep_dir = root / "keep"
    extra_dir = root / "extra"
    keep_chunks = [{"chunk_id": "c1", "content": "[ctx] laser"}]
    extra_chunks = [{"chunk_id": "extra", "content": "[ctx] stale"}]
    _write_jsonl(keep_dir / "mat.jsonl", keep_chunks)
    _write_json(
        keep_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 1}}},
    )
    _write_jsonl(extra_dir / "mat.jsonl", extra_chunks)
    _write_json(
        extra_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 1}}},
    )
    manifest_path = _write_json(
        tmp_path / "cache" / "corpus_embeddings_contextual.manifest.json",
        _build_manifest(keep_chunks, np.ones((1, EMBEDDING_DIM), dtype=np.float32), model="m"),
    )

    payload = build_canary_corpus_source_locator(chunk_store_roots=[root], manifest_paths=[manifest_path])

    assert payload["status"] == "REPAIR_CANDIDATE"
    diagnostics = payload["root_reports"][0]["single_group_exclusion_diagnostics"]
    assert diagnostics["exact_single_group_exclusion_matches"][0]["excluded_group"]["group_id"] == "extra"
    assert diagnostics["exact_single_group_exclusion_matches"][0]["matching_manifests"] == [
        str(manifest_path.resolve()).replace("\\", "/")
    ]


def test_build_canary_corpus_source_locator_dedupes_same_resolved_root(tmp_path: Path) -> None:
    root = tmp_path / "chunk_store"
    project_dir = root / "proj"
    chunks = [{"chunk_id": "c1", "content": "[ctx] laser"}]
    _write_jsonl(project_dir / "mat.jsonl", chunks)
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 1}}},
    )

    payload = build_canary_corpus_source_locator(chunk_store_roots=[root, root], manifest_paths=[])

    assert len(payload["root_reports"]) == 1
    assert payload["root_aliases"] == [
        {
            "requested_root": str(root.resolve()).replace("\\", "/"),
            "resolved_root": str(root.resolve()).replace("\\", "/"),
            "canonical_report_root": str(root.resolve()).replace("\\", "/"),
        }
    ]


def test_filter_embedding_safe_chunks_drops_only_hard_guard_rejections(monkeypatch) -> None:
    monkeypatch.setenv("CHUNK_HARD_MAX_CHARS", "10")
    monkeypatch.setenv("CHUNK_HARD_MAX_TOKENS", "9999")
    chunks = [
        {"chunk_id": "ok", "material_id": "m1", "content": "short"},
        {"chunk_id": "big", "material_id": "m2", "content": "x" * 11},
    ]

    report = filter_embedding_safe_chunks(chunks)

    assert report["kept_count"] == 1
    assert report["filtered_count"] == 1
    assert report["chunks"][0]["chunk_id"] == "ok"
    assert report["filtered_chunks"][0]["chunk_id"] == "big"
    assert report["filtered_chunks"][0]["reasons"] == ["char_count_exceeds_hard_max"]


def test_locator_accepts_manifest_for_effective_dense_corpus(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHUNK_HARD_MAX_CHARS", "10")
    monkeypatch.setenv("CHUNK_HARD_MAX_TOKENS", "9999")
    root = tmp_path / "chunk_store"
    project_dir = root / "proj"
    kept_chunks = [{"chunk_id": "keep", "content": "[ctx] ok"}]
    hard_rejected_chunks = [{"chunk_id": "too-long", "content": "[ctx] " + ("x" * 20)}]
    _write_jsonl(project_dir / "mat.jsonl", kept_chunks + hard_rejected_chunks)
    _write_json(
        project_dir / "manifest.json",
        {"version": 2, "materials": {"mat": {"relative_path": "mat.jsonl", "total_chunks": 2}}},
    )
    manifest_path = _write_json(
        tmp_path / "cache" / "corpus_embeddings_contextual.manifest.json",
        _build_manifest(kept_chunks, np.ones((1, EMBEDDING_DIM), dtype=np.float32), model="m"),
    )

    payload = build_canary_corpus_source_locator(chunk_store_roots=[root], manifest_paths=[manifest_path])

    root_report = payload["root_reports"][0]
    dense_report = root_report["dense_embedding_filter"]
    assert payload["status"] == "PASS"
    assert root_report["pass_count"] == 0
    assert dense_report["pass_count"] == 1
    assert dense_report["summary"]["chunk_count"] == 1
    assert dense_report["filtered_chunks_preview"][0]["chunk_id"] == "too-long"

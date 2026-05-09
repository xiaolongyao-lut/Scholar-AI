from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.eval.wiki_lmwr470_chunk_param_review import (
    ReviewInputError,
    build_lmwr470_review,
    extract_current_chunk_constants,
    metrics_are_identical,
    write_review_payload,
)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _metric_payload(value: float) -> dict[str, float]:
    return {
        "recall_at_1": value,
        "recall_at_3": value,
        "recall_at_5": value,
        "recall_at_10": value,
        "mrr": value,
    }


def test_extract_current_chunk_constants_uses_ast_without_import(tmp_path: Path) -> None:
    router = tmp_path / "resources_router.py"
    router.write_text(
        "\n".join(
            [
                "raise RuntimeError('must not import this file')",
                "CHUNK_SIZE = 800",
                "CHUNK_OVERLAP = 150",
                "MAX_CHUNKS_PER_MATERIAL = 5",
            ]
        ),
        encoding="utf-8",
    )

    assert extract_current_chunk_constants(router) == {
        "CHUNK_SIZE": 800,
        "CHUNK_OVERLAP": 150,
        "MAX_CHUNKS_PER_MATERIAL": 5,
    }


def test_metrics_are_identical_allows_rounding_tolerance() -> None:
    left = _metric_payload(0.5)
    right = {**_metric_payload(0.5), "mrr": 0.50005}

    assert metrics_are_identical(left, right, tolerance=0.0001)
    assert not metrics_are_identical(left, {**right, "mrr": 0.51}, tolerance=0.0001)


def test_lmwr470_review_keeps_current_defaults_when_param_causality_not_proven(tmp_path: Path) -> None:
    router = tmp_path / "resources_router.py"
    router.write_text(
        "CHUNK_SIZE = 800\nCHUNK_OVERLAP = 150\nMAX_CHUNKS_PER_MATERIAL = 5\n",
        encoding="utf-8",
    )
    analysis = _write_json(
        tmp_path / "canary30-chunk-params-analysis-20260503.json",
        {
            "aligned_baseline_comparison": {
                "baseline_metrics": {
                    "recall_at_1": 0.6667,
                    "recall_at_3": 0.6667,
                    "recall_at_5": 0.6667,
                    "recall_at_10": 0.6667,
                    "mrr": 0.6667,
                }
            }
        },
    )
    causality = _write_json(
        tmp_path / "canary30-causality-confirmation-20260503.json",
        {
            "evaluation_runs": {
                "regression_run_200_8": {
                    "parameters": {"chunk_overlap": 200, "max_chunks_per_material": 8},
                    "metrics": {
                        "recall_at_1": 0.1667,
                        "recall_at_3": 0.4333,
                        "recall_at_5": 0.5,
                        "recall_at_10": 0.6333,
                        "mrr": 0.3181,
                    },
                },
                "revert_run_150_5": {
                    "parameters": {"chunk_overlap": 150, "max_chunks_per_material": 5},
                    "metrics": {
                        "recall_at_1": 0.1667,
                        "recall_at_3": 0.4333,
                        "recall_at_5": 0.5,
                        "recall_at_10": 0.6333,
                        "mrr": 0.3181,
                    },
                },
            }
        },
    )
    cache_rebuild = _write_json(
        tmp_path / "canary30-cache-rebuild-20260503.json",
        {
            "cache_manifest_analysis": {
                "old_cache_state": {
                    "model_1": {
                        "model": "Qwen/Qwen3-Embedding-8B",
                        "chunk_count": 11445,
                        "chunks_hash": "abc",
                        "embedding_shape": [11445, 1024],
                        "is_contextual": True,
                    }
                }
            },
            "cache_invalidation_evidence": {
                "finding": "Qwen embedding cache: 11445 chunks vs current corpus 11457"
            },
        },
    )
    final_eval = _write_json(
        tmp_path / "canary30-final-20260503.json",
        {"cache_invalidation_evidence": {"finding": "current corpus 11457 chunks"}},
    )
    backup = tmp_path / "backup"
    backup.mkdir()

    payload = build_lmwr470_review(
        resources_router_path=router,
        chunk_params_analysis_path=analysis,
        causality_path=causality,
        cache_rebuild_path=cache_rebuild,
        final_evaluation_path=final_eval,
        backup_path=backup,
        review_date="2026-05-05",
    )

    assert payload["decision"]["promote_200_8"] is False
    assert payload["decision"]["keep_current_defaults"] is True
    assert payload["decision"]["parameter_causality"] == "not_proven"
    assert payload["comparisons"]["regression_200_8_minus_revert_150_5"]["rank_metrics_identical"] is True
    assert payload["cache_evidence"]["has_stale_cache_evidence"] is True
    assert payload["requires_cache_rebuild_verification"] is True


def test_review_writer_is_deterministic_json(tmp_path: Path) -> None:
    output = tmp_path / "review.json"
    write_review_payload({"b": 2, "a": 1}, output)

    assert output.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": 2\n}\n'


def test_extract_current_chunk_constants_rejects_missing_values(tmp_path: Path) -> None:
    router = tmp_path / "resources_router.py"
    router.write_text("CHUNK_SIZE = 800\n", encoding="utf-8")

    with pytest.raises(ReviewInputError, match="missing chunk constants"):
        extract_current_chunk_constants(router)

# -*- coding: utf-8 -*-
"""Text-only TOLF pilot harness tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from eval_tolf_text_pilot import make_text_only_embeddings, run_text_only_tolf_pilot


def test_text_only_embeddings_are_deterministic_and_normalized() -> None:
    texts = [
        "laser welding hardness microstructure 280 HV",
        "grain refinement and wear rate decreased by 35 percent",
    ]

    first = make_text_only_embeddings(texts, dim=32)
    second = make_text_only_embeddings(texts, dim=32)

    assert first.shape == (2, 32)
    assert np.allclose(first, second)
    assert np.all(np.linalg.norm(first, axis=1) > 0.0)
    assert np.all(np.linalg.norm(first, axis=1) <= 1.0001)


def test_text_only_pilot_returns_stable_ablation_schema() -> None:
    chunks = [
        {
            "id": "c-result",
            "content": "This study reports laser welding hardness increased to 280 HV and wear rate decreased by 35%.",
            "point_type": "result",
        },
        {
            "id": "c-method",
            "content": "The experiment used laser power 1200 W and scan speed 8 mm/s for weld preparation.",
            "point_type": "method",
        },
        {
            "id": "c-background",
            "content": "Laser welding is widely used in manufacturing and has been studied for many years.",
            "point_type": "background",
        },
    ]

    report = run_text_only_tolf_pilot(
        goal="laser welding hardness and microstructure evidence",
        chunks=chunks,
        embedding_dim=48,
        ablations=("fixed", "maq"),
    )

    assert report["schema_version"] == "tolf-text-pilot/v1"
    assert report["goal"] == "laser welding hardness and microstructure evidence"
    assert report["input"]["chunk_count"] == 3
    assert set(report["ablations"]) == {"fixed", "maq"}

    for ablation_name, payload in report["ablations"].items():
        assert payload["ablation"] == ablation_name
        assert payload["fish_count"] >= 1
        assert payload["fish"]
        first_fish = payload["fish"][0]
        assert {
            "chunk_id",
            "activation_score",
            "evidence_score",
            "aspect_weights",
            "point_type",
            "in_convex_hull",
            "content",
        }.issubset(first_fish)


def test_text_only_pilot_rejects_unknown_ablation() -> None:
    chunks = [{"id": "c1", "content": "hardness was 280 HV", "point_type": "result"}]

    try:
        run_text_only_tolf_pilot("hardness", chunks, ablations=("unknown",))
    except ValueError as exc:
        assert "Unknown TOLF text pilot ablation" in str(exc)
    else:
        raise AssertionError("unknown ablation should raise ValueError")


def test_text_only_pilot_can_disable_evidence_gate_for_ablation() -> None:
    chunks = [
        {
            "id": "c-result",
            "content": "This study reports hardness increased to 280 HV.",
            "point_type": "result",
        },
        {
            "id": "c-meta",
            "content": "Department address and affiliation metadata.",
            "point_type": "meta",
        },
    ]

    report = run_text_only_tolf_pilot(
        "hardness evidence",
        chunks,
        embedding_dim=32,
        ablations=("fixed", "fixed_no_evidence"),
    )

    fixed_ids = {item["chunk_id"] for item in report["ablations"]["fixed"]["fish"]}
    no_evidence_ids = {
        item["chunk_id"] for item in report["ablations"]["fixed_no_evidence"]["fish"]
    }

    assert "c-meta" not in fixed_ids
    assert "c-meta" in no_evidence_ids
    assert report["ablations"]["fixed_no_evidence"]["ablation_axes"]["evidence_gate"] == "disabled"


def test_text_only_pilot_supports_cosine_mask_ablation() -> None:
    chunks = [
        {
            "id": "c-result",
            "content": "Laser welding hardness increased to 280 HV with improved microstructure and wear resistance.",
            "point_type": "result",
        },
        {
            "id": "c-method",
            "content": "The process used scan speed 8 mm/s and shielding gas control during laser welding.",
            "point_type": "method",
        },
        {
            "id": "c-noise",
            "content": "Botanical survey of urban trees and rainfall observations in autumn parks.",
            "point_type": "background",
        },
    ]

    report = run_text_only_tolf_pilot(
        goal="laser welding hardness evidence",
        chunks=chunks,
        embedding_dim=48,
        ablations=("fixed_cosine_mask",),
    )

    payload = report["ablations"]["fixed_cosine_mask"]
    assert payload["ablation_axes"]["mask"] == "cosine_topk"
    assert payload["representative_rerank"] == {
        "enabled": False,
        "stage": "post_evidence_gate",
    }
    assert payload["mask_summary"]["kept_count"] == 2
    assert "c-noise" in payload["mask_summary"]["masked_chunk_ids"]


def test_text_only_pilot_supports_relation_type_mask_ablation() -> None:
    chunks = [
        {
            "id": "c-result",
            "content": "Hardness increased to 280 HV after process optimization.",
            "point_type": "result",
        },
        {
            "id": "c-mechanism",
            "content": "The mechanism is explained by refined grains and suppressed pore growth.",
            "point_type": "mechanism",
        },
        {
            "id": "c-background",
            "content": "Background review of historical welding studies and theory.",
            "point_type": "background",
        },
    ]

    report = run_text_only_tolf_pilot(
        goal="mechanism explanation for hardness improvement",
        chunks=chunks,
        embedding_dim=48,
        ablations=("maq_relation_mask",),
    )

    payload = report["ablations"]["maq_relation_mask"]
    assert payload["ablation_axes"]["weighting"] == "maq"
    assert payload["ablation_axes"]["mask"] == "relation_type_goal_heuristic"
    assert payload["mask_summary"]["allowed_point_types"] == ["mechanism", "result", "discussion"]
    assert "c-background" in payload["mask_summary"]["masked_chunk_ids"]

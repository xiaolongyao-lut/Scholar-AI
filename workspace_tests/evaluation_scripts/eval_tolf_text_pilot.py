# -*- coding: utf-8 -*-
"""Text-only TOLF pilot harness.

This module provides a small, local-only evaluation surface for TOLF
experiments. It intentionally avoids embedding APIs and multimodal runtime
integration: text is embedded with deterministic hashing so the first pilot can
validate schema, ablation wiring, and evidence-gate behavior at zero external
cost.

Input shape used by ``run_text_only_tolf_pilot``::

    {
      "goal": "research target",
      "chunks": [
        {"id": "c1", "content": "...", "point_type": "result"}
      ]
    }

Output shape is a JSON-serializable ``tolf-text-pilot/v1`` report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from layers.tolf_engine import FishResult, TOLFConfig, TOLFEngine

_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+", re.UNICODE)
_SUPPORTED_ABLATIONS = {
    "fixed",
    "fixed_no_evidence",
    "maq",
    "maq_no_evidence",
    "fixed_cosine_mask",
    "maq_cosine_mask",
    "fixed_relation_mask",
    "maq_relation_mask",
}
_DEFAULT_ABLATIONS = ("fixed", "fixed_no_evidence", "maq", "maq_no_evidence")


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _token_bucket(token: str, dim: int) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % dim


def make_text_only_embeddings(texts: Sequence[str], *, dim: int = 128) -> np.ndarray:
    """Create deterministic local text embeddings with hashed token counts.

    The vectors are L2-normalized and stable across Python processes. This is a
    pilot/evaluation adapter, not a production embedding replacement.
    """
    if dim <= 0:
        raise ValueError("embedding dim must be positive")

    matrix = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        for token in _tokenize(str(text)):
            matrix[row, _token_bucket(token, dim)] += 1.0

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    nonzero = norms[:, 0] > 0.0
    matrix[nonzero] = matrix[nonzero] / norms[nonzero]
    return matrix


def normalize_text_chunks(chunks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize pilot chunks to the minimal TOLF engine contract."""
    normalized: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        content = str(chunk.get("content") or chunk.get("text") or "")
        normalized.append(
            {
                "id": str(chunk.get("id") or chunk.get("chunk_id") or f"chunk_{index}"),
                "content": content,
                "point_type": str(chunk.get("point_type") or "discussion"),
            }
        )
    return normalized


def _fish_to_payload(result: FishResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["activation_score"] = round(float(result.activation_score), 6)
    payload["evidence_score"] = round(float(result.evidence_score), 6)
    payload["aspect_weights"] = {
        key: round(float(value), 6) for key, value in result.aspect_weights.items()
    }
    return payload


def _make_config(*, evidence_enabled: bool = True) -> TOLFConfig:
    return TOLFConfig(
        activation_threshold=0.1,
        evidence_threshold=0.2 if evidence_enabled else 0.0,
        umap_n_components=3,
        umap_n_neighbors=2,
    )


def _parse_ablation(ablation: str) -> tuple[str, bool, str]:
    evidence_enabled = not ablation.endswith("_no_evidence")
    uses_maq = ablation.startswith("maq")
    if "cosine_mask" in ablation:
        mask_kind = "cosine_topk"
    elif "relation_mask" in ablation:
        mask_kind = "relation_type_goal_heuristic"
    elif uses_maq:
        mask_kind = "maq_convex_hull"
    else:
        mask_kind = "none"
    return ("maq" if uses_maq else "fixed"), evidence_enabled, mask_kind


def _goal_relation_focus(goal: str) -> str:
    goal_lower = str(goal).lower()
    if any(token in goal_lower for token in ("method", "parameter", "protocol", "process", "工艺", "参数", "实验")):
        return "method"
    if any(token in goal_lower for token in ("mechanism", "cause", "why", "机理", "原因", "因果", "解释")):
        return "mechanism"
    if any(token in goal_lower for token in ("background", "review", "theory", "背景", "综述", "理论")):
        return "background"
    return "result"


def _allowed_point_types(goal: str) -> tuple[str, ...]:
    focus = _goal_relation_focus(goal)
    if focus == "method":
        return ("method", "discussion", "result")
    if focus == "mechanism":
        return ("mechanism", "result", "discussion")
    if focus == "background":
        return ("background", "summary", "discussion")
    return ("result", "mechanism", "method")


def _mask_chunks_for_ablation(
    *,
    goal: str,
    chunks: list[dict[str, Any]],
    chunk_embeddings: np.ndarray,
    embedding_dim: int,
    mask_kind: str,
) -> tuple[list[dict[str, Any]], np.ndarray, dict[str, Any]]:
    chunk_copy = [dict(chunk) for chunk in chunks]
    masked_embeddings = np.array(chunk_embeddings, copy=True)
    kept_indices = list(range(len(chunk_copy)))
    allowed_types: tuple[str, ...] = ()
    cosine_scores: list[float] = []

    if mask_kind == "cosine_topk":
        goal_embedding = make_text_only_embeddings([goal], dim=embedding_dim)[0]
        cosine_scores = [float(score) for score in (chunk_embeddings @ goal_embedding)]
        keep_count = max(1, min(len(chunk_copy), math.ceil(len(chunk_copy) * 0.6)))
        ranked = np.argsort(-np.asarray(cosine_scores), kind="stable")[:keep_count]
        kept_indices = sorted(int(index) for index in ranked)
    elif mask_kind == "relation_type_goal_heuristic":
        allowed_types = _allowed_point_types(goal)
        kept_indices = [
            index
            for index, chunk in enumerate(chunk_copy)
            if chunk.get("point_type") in allowed_types
        ]
        if not kept_indices:
            kept_indices = [
                index
                for index, chunk in enumerate(chunk_copy)
                if chunk.get("point_type") != "meta"
            ] or list(range(len(chunk_copy)))

    kept_index_set = set(kept_indices)
    kept_chunk_ids: list[str] = []
    masked_chunk_ids: list[str] = []
    for index, chunk in enumerate(chunk_copy):
        chunk_id = str(chunk.get("id") or chunk.get("chunk_id") or f"chunk_{index}")
        keep = index in kept_index_set
        chunk["pilot_mask_keep"] = keep
        if cosine_scores:
            chunk["pilot_mask_score"] = round(float(cosine_scores[index]), 6)
        if keep:
            kept_chunk_ids.append(chunk_id)
        else:
            masked_chunk_ids.append(chunk_id)
            masked_embeddings[index] = 0.0

    return (
        chunk_copy,
        masked_embeddings,
        {
            "mask_kind": mask_kind,
            "kept_count": len(kept_chunk_ids),
            "masked_count": len(masked_chunk_ids),
            "kept_chunk_ids": kept_chunk_ids,
            "masked_chunk_ids": masked_chunk_ids,
            "allowed_point_types": list(allowed_types),
        },
    )


def _run_one_ablation(
    *,
    goal: str,
    chunks: list[dict[str, Any]],
    chunk_embeddings: np.ndarray,
    embedding_dim: int,
    ablation: str,
) -> dict[str, Any]:
    weighting, evidence_enabled, mask_kind = _parse_ablation(ablation)
    uses_maq = weighting == "maq"
    config = _make_config(evidence_enabled=evidence_enabled)
    engine = TOLFEngine(config)

    chunk_copy, masked_embeddings, mask_summary = _mask_chunks_for_ablation(
        goal=goal,
        chunks=chunks,
        chunk_embeddings=chunk_embeddings,
        embedding_dim=embedding_dim,
        mask_kind=mask_kind,
    )

    if uses_maq:
        aspect_queries = engine.generate_aspect_queries(goal)
        aspect_query_embeddings = make_text_only_embeddings(
            list(aspect_queries.values()),
            dim=embedding_dim,
        )
    elif ablation.startswith("fixed"):
        aspect_query_embeddings = None
    else:
        raise ValueError(f"Unknown TOLF text pilot ablation: {ablation}")

    fish = engine.run(
        goal=goal,
        chunks=chunk_copy,
        embeddings=masked_embeddings,
        aspect_query_embeddings=aspect_query_embeddings,
    )
    if mask_kind in {"cosine_topk", "relation_type_goal_heuristic"}:
        kept = set(mask_summary["kept_chunk_ids"])
        fish = [result for result in fish if result.chunk_id in kept]

    return {
        "ablation": ablation,
        "ablation_axes": {
            "weighting": weighting,
            "mask": mask_kind,
            "evidence_gate": "enabled" if evidence_enabled else "disabled",
        },
        "config": {
            "activation_threshold": config.activation_threshold,
            "evidence_threshold": config.evidence_threshold,
            "umap_n_components": config.umap_n_components,
            "umap_n_neighbors": config.umap_n_neighbors,
        },
        "representative_rerank": {
            "enabled": False,
            "stage": "post_evidence_gate",
        },
        "mask_summary": mask_summary,
        "fish_count": len(fish),
        "fish": [_fish_to_payload(result) for result in fish],
    }


def run_text_only_tolf_pilot(
    goal: str,
    chunks: Sequence[dict[str, Any]],
    *,
    embedding_dim: int = 128,
    ablations: Sequence[str] = _DEFAULT_ABLATIONS,
) -> dict[str, Any]:
    """Run a local text-only TOLF pilot and return a stable report payload."""
    unknown = [name for name in ablations if name not in _SUPPORTED_ABLATIONS]
    if unknown:
        raise ValueError(f"Unknown TOLF text pilot ablation: {unknown[0]}")

    normalized_chunks = normalize_text_chunks(chunks)
    chunk_embeddings = make_text_only_embeddings(
        [chunk["content"] for chunk in normalized_chunks],
        dim=embedding_dim,
    )

    return {
        "schema_version": "tolf-text-pilot/v1",
        "goal": goal,
        "input": {
            "chunk_count": len(normalized_chunks),
            "embedding_backend": "local_hashing_text_only",
            "embedding_dim": embedding_dim,
            "external_api_calls": 0,
        },
        "ablations": {
            ablation: _run_one_ablation(
                goal=goal,
                chunks=normalized_chunks,
                chunk_embeddings=chunk_embeddings,
                embedding_dim=embedding_dim,
                ablation=ablation,
            )
            for ablation in ablations
        },
    }


def _load_input(path: Path) -> tuple[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    goal = str(payload.get("goal") or "")
    chunks = payload.get("chunks")
    if not goal:
        raise ValueError("input JSON must include a non-empty 'goal'")
    if not isinstance(chunks, list):
        raise ValueError("input JSON must include a 'chunks' list")
    return goal, chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local text-only TOLF pilot.")
    parser.add_argument("--input", required=True, help="JSON file with goal and chunks")
    parser.add_argument("--output", required=True, help="Output report JSON path")
    parser.add_argument("--embedding-dim", type=int, default=128)
    parser.add_argument(
        "--ablation",
        action="append",
        choices=sorted(_SUPPORTED_ABLATIONS),
        help="Ablation to run; repeatable. Defaults to the 2x2 fixed/MAQ and evidence on/off matrix. Additional cosine/relation mask variants are available explicitly.",
    )
    args = parser.parse_args()

    goal, chunks = _load_input(Path(args.input))
    report = run_text_only_tolf_pilot(
        goal,
        chunks,
        embedding_dim=args.embedding_dim,
        ablations=tuple(args.ablation or _DEFAULT_ABLATIONS),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote TOLF text-only pilot report: {output_path}")


if __name__ == "__main__":
    main()

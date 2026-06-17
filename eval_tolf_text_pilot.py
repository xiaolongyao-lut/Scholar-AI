# -*- coding: utf-8 -*-
"""Deterministic text-only TOLF pilot harness."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any

import numpy as np


_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def make_text_only_embeddings(texts: Sequence[str], dim: int = 64) -> np.ndarray:
    """Create deterministic normalized hashing embeddings for text snippets."""

    if dim < 1:
        raise ValueError("dim must be positive")
    if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence):
        raise TypeError("texts must be a sequence of strings")
    matrix = np.zeros((len(texts), dim), dtype=np.float32)
    for row, text in enumerate(texts):
        if not isinstance(text, str):
            raise TypeError("texts entries must be strings")
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            matrix[row, index] += sign
        norm = float(np.linalg.norm(matrix[row]))
        if norm > 0.0:
            matrix[row] /= norm
    return matrix


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0.0:
        return 0.0
    return float(np.dot(left, right) / denom)


def _aspect_weights(ablation: str, point_type: str) -> dict[str, float]:
    base = {"semantic": 0.45, "evidence": 0.35, "relation": 0.20}
    if "maq" in ablation:
        base = {"semantic": 0.35, "evidence": 0.30, "relation": 0.35}
    if point_type in {"result", "mechanism"}:
        base["evidence"] += 0.1
    total = sum(base.values())
    return {key: round(value / total, 4) for key, value in base.items()}


def _evidence_score(content: str, point_type: str) -> float:
    text = content.lower()
    score = 0.0
    if re.search(r"\d", text):
        score += 0.35
    if any(term in text for term in ("hardness", "microstructure", "wear", "mechanism", "result", "increased", "decreased")):
        score += 0.45
    if point_type in {"result", "mechanism", "discussion", "method"}:
        score += 0.2
    return min(1.0, score)


def _allowed_relation_types(goal: str) -> list[str]:
    lowered = goal.lower()
    if "mechanism" in lowered or "机制" in lowered:
        return ["mechanism", "result", "discussion"]
    return ["result", "method", "mechanism", "discussion"]


def run_text_only_tolf_pilot(
    goal: str,
    chunks: Sequence[dict[str, Any]],
    *,
    embedding_dim: int = 64,
    ablations: Sequence[str] = ("fixed", "maq"),
) -> dict[str, Any]:
    """Run deterministic TOLF-style ablations over text chunks."""

    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal must be a non-empty string")
    if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
        raise TypeError("chunks must be a sequence of dictionaries")
    allowed = {"fixed", "maq", "fixed_no_evidence", "fixed_cosine_mask", "maq_relation_mask"}
    for ablation in ablations:
        if ablation not in allowed:
            raise ValueError(f"Unknown TOLF text pilot ablation: {ablation}")
    normalized_chunks = [dict(chunk) for chunk in chunks]
    texts = [goal, *[str(chunk.get("content", "")) for chunk in normalized_chunks]]
    embeddings = make_text_only_embeddings(texts, dim=embedding_dim)
    goal_vec = embeddings[0]
    chunk_vecs = embeddings[1:]

    report = {
        "schema_version": "tolf-text-pilot/v1",
        "goal": goal,
        "input": {"chunk_count": len(normalized_chunks), "embedding_dim": embedding_dim},
        "ablations": {},
    }
    for ablation in ablations:
        mask_summary: dict[str, Any] = {"kept_count": len(normalized_chunks), "masked_chunk_ids": []}
        allowed_types: list[str] | None = None
        candidate_indices = list(range(len(normalized_chunks)))
        if ablation == "fixed_cosine_mask":
            scored = sorted(
                (
                    (
                        index,
                        (_cosine(goal_vec, chunk_vecs[index]) * 0.65)
                        + (_evidence_score(
                            str(normalized_chunks[index].get("content", "")),
                            str(normalized_chunks[index].get("point_type", "")),
                        ) * 0.35),
                    )
                    for index in candidate_indices
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            keep = {index for index, _score in scored[: max(1, min(2, len(scored)))]}
            candidate_indices = [index for index in candidate_indices if index in keep]
            mask_summary = {
                "kept_count": len(candidate_indices),
                "masked_chunk_ids": [
                    str(chunk.get("id") or chunk.get("chunk_id"))
                    for index, chunk in enumerate(normalized_chunks)
                    if index not in keep
                ],
            }
        if ablation == "maq_relation_mask":
            allowed_types = _allowed_relation_types(goal)
            candidate_indices = [
                index
                for index in candidate_indices
                if str(normalized_chunks[index].get("point_type", "")) in allowed_types
            ]
            mask_summary = {
                "allowed_point_types": allowed_types,
                "kept_count": len(candidate_indices),
                "masked_chunk_ids": [
                    str(chunk.get("id") or chunk.get("chunk_id"))
                    for index, chunk in enumerate(normalized_chunks)
                    if index not in candidate_indices
                ],
            }
        fish: list[dict[str, Any]] = []
        for index in candidate_indices:
            chunk = normalized_chunks[index]
            point_type = str(chunk.get("point_type", "unknown"))
            content = str(chunk.get("content", ""))
            semantic = max(0.0, _cosine(goal_vec, chunk_vecs[index]))
            evidence = _evidence_score(content, point_type)
            if ablation != "fixed_no_evidence" and evidence < 0.2:
                continue
            weights = _aspect_weights(ablation, point_type)
            activation = semantic * weights["semantic"] + evidence * weights["evidence"] + weights["relation"] * 0.5
            fish.append(
                {
                    "chunk_id": str(chunk.get("id") or chunk.get("chunk_id") or f"chunk-{index}"),
                    "activation_score": round(float(activation), 6),
                    "evidence_score": round(float(evidence), 6),
                    "aspect_weights": weights,
                    "point_type": point_type,
                    "in_convex_hull": bool(semantic >= 0.0 and math.isfinite(semantic)),
                    "content": content,
                }
            )
        fish.sort(key=lambda item: item["activation_score"], reverse=True)
        axes = {
            "weighting": "maq" if "maq" in ablation else "fixed",
            "evidence_gate": "disabled" if ablation == "fixed_no_evidence" else "enabled",
        }
        if ablation == "fixed_cosine_mask":
            axes["mask"] = "cosine_topk"
        if ablation == "maq_relation_mask":
            axes["mask"] = "relation_type_goal_heuristic"
        report["ablations"][ablation] = {
            "ablation": ablation,
            "ablation_axes": axes,
            "fish_count": len(fish),
            "fish": fish,
            "mask_summary": mask_summary,
            "representative_rerank": {
                "enabled": False,
                "stage": "post_evidence_gate",
            },
        }
    return report

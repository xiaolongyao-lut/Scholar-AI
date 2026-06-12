# -*- coding: utf-8 -*-
"""A15 ablation evaluator — runs chunk_type weight candidates on a goldset.

Per A15 tuning spec(`docs/plans/specs/a15-chunk-type-weighting-tuning.md` §3):
  - User prepares a goldset(`goldset.jsonl`)of {query, ground_truth_chunk_ids}.
  - This runner loads a project's chunk_store, scores each candidate weight
    config, and emits nDCG@5/@10, Recall@10, MRR + paired-bootstrap 95% CI.
  - It does NOT switch CHUNK_TYPE_WEIGHTS — output is decision support only.

Usage (from .venv-1):
    .\\.venv-1\\Scripts\\python.exe \\
        literature_assistant/core/rag_ablation_evaluator.py \\
        --project-id proj_ec65a4e90854 \\
        --goldset workspace_artifacts/marker-rag-pipeline-evidence-2026-06-11/\\
                  goldset/proj_ec65a4e90854.goldset.jsonl \\
        --output workspace_artifacts/marker-rag-pipeline-evidence-2026-06-11/\\
                 goldset/proj_ec65a4e90854.ablation_report.json

goldset.jsonl 每行格式(see goldset_template.jsonl):
    {"query": "...", "query_type": "numeric|method|mechanism|general",
     "ground_truth_chunk_ids": ["chunk_id_1", "chunk_id_2", ...]}

5 个候选配置:
  baseline           : flag off,无 weighting
  all_one            : flag on,所有权重 1.0(应与 baseline 相等)
  proposed           : flag on,§2.1 推荐表(narrative=1.0 / heading=0.75 /
                       table=1.30 / formula=1.20 / figure_caption=1.15 /
                       list=0.95 / code=0.90 / image_caption=1.10)
  table_heavy        : flag on,只 table=1.5,其它 1.0
  heading_suppressed : flag on,只 heading=0.5,其它 1.0

Scoring helper:
  BM25 + cosine 两路 score 简单线性融合 → rerank_score 候选,然后 hook 加权。
  注意:这只是 ablation 内部的 *相对评估* — 真实 RAG 用的是 retriever 完整
  hybrid + rerank,本工具不复用那条管道(那条需要凭据 + rerank API 服务)。
  但加权 hook 本身相同,因此结果对*权重值排名*仍有指示意义。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


# Decision-support candidate configs.See spec §3.3.
CANDIDATE_CONFIGS: dict[str, dict[str, float] | None] = {
    "baseline": None,  # flag off — no weighting
    "all_one": {  # flag on,all weights 1.0(should match baseline byte-level)
        "narrative": 1.0,
        "heading": 1.0,
        "table": 1.0,
        "formula": 1.0,
        "figure_caption": 1.0,
        "list": 1.0,
        "code": 1.0,
        "image_caption": 1.0,
    },
    "proposed": {  # spec §2.1 recommended weights
        "narrative": 1.00,
        "heading": 0.75,
        "table": 1.30,
        "formula": 1.20,
        "figure_caption": 1.15,
        "list": 0.95,
        "code": 0.90,
        "image_caption": 1.10,
    },
    "table_heavy": {  # single-variable: table 上调
        "narrative": 1.0,
        "heading": 1.0,
        "table": 1.5,
        "formula": 1.0,
        "figure_caption": 1.0,
        "list": 1.0,
        "code": 1.0,
        "image_caption": 1.0,
    },
    "heading_suppressed": {  # single-variable: heading 降权防刷榜
        "narrative": 1.0,
        "heading": 0.5,
        "table": 1.0,
        "formula": 1.0,
        "figure_caption": 1.0,
        "list": 1.0,
        "code": 1.0,
        "image_caption": 1.0,
    },
}


def load_chunks(project_id: str, repo_root: Path) -> list[dict[str, Any]]:
    chunk_dir = repo_root / "workspace_artifacts" / "projects" / project_id / "chunk_store" / project_id
    chunks: list[dict[str, Any]] = []
    for jsonl in chunk_dir.glob("*.jsonl"):
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def load_goldset(path: Path) -> list[dict[str, Any]]:
    goldset: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = json.loads(line)
        # Skip template/empty rows so a partially-filled file still runs.
        if not entry.get("ground_truth_chunk_ids"):
            continue
        goldset.append(entry)
    return goldset


def naive_bm25ish_score(query: str, content: str) -> float:
    """Cheap query-on-content scorer.NOT a real BM25 — this only powers
    ablation's *relative* ranking. The retriever production path uses a
    real hybrid stack;here we just need a baseline score so chunk_type
    weighting has something to multiply."""
    if not query or not content:
        return 0.0
    q_tokens = {t.lower() for t in query.split() if len(t) >= 2}
    c_lower = content.lower()
    hits = sum(1 for t in q_tokens if t in c_lower)
    if not q_tokens:
        return 0.0
    return hits / len(q_tokens)


def search(query: str, chunks: list[dict[str, Any]], weights: dict[str, float] | None) -> list[dict[str, Any]]:
    """Rank chunks for query.weights=None → no weighting (baseline path)."""
    scored: list[dict[str, Any]] = []
    for c in chunks:
        s = naive_bm25ish_score(query, str(c.get("content") or ""))
        if s <= 0:
            continue
        scored_chunk = dict(c)
        scored_chunk["rerank_score"] = s
        scored.append(scored_chunk)
    scored.sort(key=lambda c: c["rerank_score"], reverse=True)

    if weights is None:
        return scored

    # Replicate apply_chunk_type_weights logic without depending on
    # feature flag state (the runner force-on the weighting):
    for c in scored:
        ctype = c.get("chunk_type")
        w = weights.get(str(ctype) if ctype is not None else "", 1.0)
        c["rerank_score"] = float(c["rerank_score"]) * w
    scored.sort(key=lambda c: c["rerank_score"], reverse=True)
    return scored


# --------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------- #


def dcg(rel_list: list[int]) -> float:
    return sum((2 ** rel - 1) / math.log2(i + 2) for i, rel in enumerate(rel_list))


def ndcg(retrieved: list[str], gold: set[str], k: int) -> float:
    rel = [1 if c in gold else 0 for c in retrieved[:k]]
    ideal = sorted(rel, reverse=True)
    idcg = dcg(ideal)
    return dcg(rel) / idcg if idcg > 0 else 0.0


def recall_at_k(retrieved: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    top = set(retrieved[:k])
    return len(top & gold) / len(gold)


def mrr(retrieved: list[str], gold: set[str]) -> float:
    for i, c in enumerate(retrieved):
        if c in gold:
            return 1.0 / (i + 1)
    return 0.0


def paired_bootstrap_ci(deltas: list[float], alpha: float = 0.05, n: int = 1000) -> tuple[float, float, float]:
    """Return (mean_delta, ci_low, ci_high) for paired bootstrap.
    deltas[i] = metric_proposed(query i) - metric_baseline(query i)."""
    if not deltas:
        return (0.0, 0.0, 0.0)
    rng = random.Random(42)
    means = []
    for _ in range(n):
        sample = [deltas[rng.randrange(len(deltas))] for _ in range(len(deltas))]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int(n * (alpha / 2))]
    high = means[int(n * (1 - alpha / 2))]
    return (statistics.fmean(deltas), low, high)


# --------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------- #


def run(project_id: str, goldset_path: Path, output_path: Path, repo_root: Path) -> int:
    chunks = load_chunks(project_id, repo_root)
    if not chunks:
        print(f"[error] no chunks for project {project_id}")
        return 2
    goldset = load_goldset(goldset_path)
    if not goldset:
        print(f"[error] empty / template-only goldset at {goldset_path}")
        print(f"        please fill in ground_truth_chunk_ids and re-run")
        return 3

    print(f"[info] loaded {len(chunks)} chunks for project {project_id}")
    print(f"[info] loaded {len(goldset)} goldset queries from {goldset_path}")

    # chunk_type distribution sanity
    type_dist = Counter(c.get("chunk_type", "unknown") for c in chunks)
    print(f"[info] chunk_type distribution: {dict(type_dist)}")

    # Per-config metrics
    report: dict[str, Any] = {
        "project_id": project_id,
        "chunk_count": len(chunks),
        "chunk_type_distribution": dict(type_dist),
        "goldset_size": len(goldset),
        "candidates": {},
        "paired_vs_baseline": {},
    }

    metric_keys = ["ndcg@5", "ndcg@10", "recall@10", "mrr"]
    per_query_metrics: dict[str, dict[str, list[float]]] = {}
    for cname in CANDIDATE_CONFIGS:
        per_query_metrics[cname] = {m: [] for m in metric_keys}

    for entry in goldset:
        gold = set(entry["ground_truth_chunk_ids"])
        for cname, cfg in CANDIDATE_CONFIGS.items():
            retrieved = [c["chunk_id"] for c in search(entry["query"], chunks, cfg)]
            per_query_metrics[cname]["ndcg@5"].append(ndcg(retrieved, gold, 5))
            per_query_metrics[cname]["ndcg@10"].append(ndcg(retrieved, gold, 10))
            per_query_metrics[cname]["recall@10"].append(recall_at_k(retrieved, gold, 10))
            per_query_metrics[cname]["mrr"].append(mrr(retrieved, gold))

    for cname, per_metric in per_query_metrics.items():
        report["candidates"][cname] = {
            m: round(statistics.fmean(per_metric[m]) if per_metric[m] else 0.0, 4)
            for m in metric_keys
        }

    # Paired bootstrap vs baseline
    baseline_metrics = per_query_metrics["baseline"]
    for cname, per_metric in per_query_metrics.items():
        if cname == "baseline":
            continue
        report["paired_vs_baseline"][cname] = {}
        for m in metric_keys:
            deltas = [
                per_metric[m][i] - baseline_metrics[m][i]
                for i in range(len(baseline_metrics[m]))
            ]
            mean, low, high = paired_bootstrap_ci(deltas)
            report["paired_vs_baseline"][cname][m] = {
                "mean_delta": round(mean, 4),
                "ci95_low": round(low, 4),
                "ci95_high": round(high, 4),
                "significant_positive": low > 0,
                "significant_negative": high < 0,
            }

    # Acceptance rule per spec §3.4
    proposed = report["paired_vs_baseline"].get("proposed", {})
    ndcg5 = proposed.get("ndcg@5", {})
    accept = ndcg5.get("significant_positive", False)
    report["recommendation"] = {
        "accept_proposed": accept,
        "rationale": (
            "proposed nDCG@5 paired-bootstrap 95% CI 下界严格 > baseline → accept"
            if accept
            else (
                "proposed 未显著超过 baseline → 维持 all_one(等价于 baseline);"
                "考虑增加 goldset 规模或重新设计权重组合"
            )
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] report written to {output_path}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project-id", required=True)
    p.add_argument("--goldset", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(run(args.project_id, args.goldset, args.output, args.repo_root))

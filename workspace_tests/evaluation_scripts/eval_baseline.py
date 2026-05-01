from __future__ import annotations

from eval_retrieval_runtime import run_eval


def evaluate() -> dict:
    """Backward-compatible entrypoint for baseline evaluation."""
    return run_eval(
        queries_path="eval_queries_v1.0.jsonl",
        output_path="BASELINE_METRICS.json",
        top_k=10,
    )


if __name__ == "__main__":
    metrics = evaluate()
    agg = metrics.get("aggregated_metrics", {})
    print("Baseline evaluation completed.")
    print(
        f"Recall@5={agg.get('recall_at_5', 0.0)} | "
        f"MRR={agg.get('mrr', 0.0)} | "
        f"P95={agg.get('p95_latency_ms', 0.0)}ms"
    )

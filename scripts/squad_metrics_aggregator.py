# -*- coding: utf-8 -*-
"""
Squad Metrics Aggregator
Role: 处理 Tier 3 全量评估结果，为 RAG 演进提供数据支撑
"""

import json
import logging
from pathlib import Path

def aggregate():
    input_path = Path("output/tier3_u1a3269.per_query.jsonl")
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        return

    recalls = {1: [], 3: [], 5: [], 10: []}
    mrrs = []
    latencies = []

    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            recalls[1].append(data.get("recall_at_1", 0))
            recalls[3].append(data.get("recall_at_3", 0))
            recalls[5].append(data.get("recall_at_5", 0))
            recalls[10].append(data.get("recall_at_10", 0))
            mrrs.append(data.get("mrr", 0))
            latencies.append(data.get("latency_ms", 0))
            count += 1

    if count == 0: return

    report = {
        "total_queries": count,
        "recall_at_1": round(sum(recalls[1]) / count, 4),
        "recall_at_3": round(sum(recalls[3]) / count, 4),
        "recall_at_5": round(sum(recalls[5]) / count, 4),
        "recall_at_10": round(sum(recalls[10]) / count, 4),
        "mrr": round(sum(mrrs) / count, 4),
        "avg_latency_ms": round(sum(latencies) / count, 2)
    }

    output_path = Path("output/tier3_final_summary.json")
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"✅ Report generated: {report}")

if __name__ == "__main__":
    aggregate()

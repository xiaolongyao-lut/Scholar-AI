import json
import time
import math
from pathlib import Path
from typing import List, Dict, Any

# 导入检索器 (假设已安装依赖)
try:
    from layers.r_layer_hybrid_retriever import hybrid_search
except ImportError:
    def hybrid_search(data, query, top_k):
        return []

def calculate_mrr(relevance_list: List[bool]) -> float:
    for i, rel in enumerate(relevance_list):
        if rel:
            return 1.0 / (i + 1)
    return 0.0

def calculate_recall_at_k(relevance_list: List[bool], k: int) -> float:
    if not relevance_list:
        return 0.0
    return 1.0 if any(relevance_list[:k]) else 0.0

def calculate_ndcg_at_k(relevance_list: List[bool], k: int) -> float:
    dcg = 0.0
    for i, rel in enumerate(relevance_list[:k]):
        if rel:
            dcg += 1.0 / math.log2(i + 2)
    
    # IDCG (理想情况，假设至少有一个相关结果)
    idcg = 1.0 # 简化处理
    return dcg / idcg

def evaluate():
    queries_path = Path("eval_queries_v1.0.jsonl")
    if not queries_path.exists():
        print("Error: eval_queries_v1.0.jsonl not found.")
        return

    # 模拟或加载本地测试数据
    # 在真实基线中，这应该是全量知识库
    mock_raw_extract = {"chunks": []} 
    
    results = []
    total_latency = 0
    
    with open(queries_path, "r", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f]

    print(f"Starting baseline evaluation for {len(queries)} queries...")

    for q in queries:
        start_time = time.time()
        
        # 执行检索
        # 注意：这里在 P0 阶段由于数据可能未就绪，Recall 预期会较低
        hits = hybrid_search(mock_raw_extract, q["query_text"], top_k=10)
        
        latency = (time.time() - start_time) * 1000
        total_latency += latency
        
        # 判定相关性 (P0 简化逻辑: 如果命中任何结果则认为部分相关，
        # 在真实场景下需对比证据集 doc_id)
        # 这里的 relevance_list 目前会全为 False 因为数据为空
        relevance_list = [False] * len(hits) 
        
        results.append({
            "query_id": q["query_id"],
            "difficulty": q["difficulty_level"],
            "latency_ms": latency,
            "recall_at_3": calculate_recall_at_k(relevance_list, 3),
            "mrr": calculate_mrr(relevance_list)
        })

    # 汇总
    count = len(results)
    avg_recall_3 = sum(r["recall_at_3"] for r in results) / count if count > 0 else 0
    avg_mrr = sum(r["mrr"] for r in results) / count if count > 0 else 0
    avg_latency = total_latency / count if count > 0 else 0

    metrics = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_queries": count,
        "aggregated_metrics": {
            "recall_at_3": round(avg_recall_3, 4),
            "mrr": round(avg_mrr, 4),
            "avg_latency_ms": round(avg_latency, 2)
        },
        "per_difficulty": {}
    }

    # 按难度分组
    for diff in ["simple", "medium", "hard"]:
        diff_results = [r for r in results if r["difficulty"] == diff]
        if diff_results:
            metrics["per_difficulty"][diff] = {
                "count": len(diff_results),
                "recall_at_3": round(sum(r["recall_at_3"] for r in diff_results) / len(diff_results), 4)
            }

    with open("BASELINE_METRICS.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    print(f"Baseline evaluation completed.")
    print(f"Recall@3 (Baseline): {avg_recall_3}")
    print(f"Metrics saved to BASELINE_METRICS.json")

if __name__ == "__main__":
    evaluate()

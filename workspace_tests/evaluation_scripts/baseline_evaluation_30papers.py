#!/usr/bin/env python3
"""
运行评测基线：在 30 篇论文的知识库上计算 Recall/MRR 等指标
"""

import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))


def compute_recall_metrics(
    retrieved_ids: list[str],
    relevant_ids: list[str],
    k_values: list[int] = None,
) -> dict[str, float]:
    """
    计算 Recall@K 指标
    """
    if k_values is None:
        k_values = [1, 5, 10]

    metrics = {}
    for k in k_values:
        top_k = retrieved_ids[:k]
        recall = len(set(top_k) & set(relevant_ids)) / max(len(relevant_ids), 1)
        metrics[f"recall@{k}"] = recall

    return metrics


def compute_mrr(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    """
    计算 Mean Reciprocal Rank (MRR)
    """
    relevant_set = set(relevant_ids)
    for rank, doc_id in enumerate(retrieved_ids, 1):
        if doc_id in relevant_set:
            return 1.0 / rank
    return 0.0


def simple_keyword_retrieval(
    query: str,
    chunk_store: dict[str, Any],
    doc_store: dict[str, Any],
    top_k: int = 10,
) -> list[str]:
    """
    简单的关键词检索：在 chunk_store 中查找匹配的分块
    返回相关的 material_id 列表（按相关性排序）
    """
    results = []

    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue

        match_count = 0
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue

            content = chunk.get("raw_content") or chunk.get("content") or ""
            # 简单的单词级别匹配
            words = query.lower().split()
            for word in words:
                if word in content.lower():
                    match_count += 1

        if match_count > 0:
            results.append((material_id, match_count))

    # 按匹配度排序
    results = sorted(results, key=lambda x: -x[1])
    return [doc_id for doc_id, _ in results[:top_k]]


def main():
    print("\n" + "=" * 80)
    print("评测基线：30 篇激光焊接论文知识库")
    print("=" * 80)

    project_id = "laser_welding_30"

    # 1. 加载知识库
    print("\n1. 加载知识库...")
    chunk_store_path = Path("./output/chunk_store") / f"{project_id}_chunks.json"
    doc_store_path = Path("./output/doc_store") / f"{project_id}.json"

    if not chunk_store_path.exists() or not doc_store_path.exists():
        print(f"✗ 未找到知识库文件")
        return False

    with open(chunk_store_path, "r", encoding="utf-8") as f:
        chunk_store = json.load(f)

    with open(doc_store_path, "r", encoding="utf-8") as f:
        doc_store = json.load(f)

    total_chunks = sum(len(v) if isinstance(v, list) else 1 for v in chunk_store.values())
    print(f"  ✓ 加载完成")
    print(f"    材料数: {len(chunk_store)}")
    print(f"    分块数: {total_chunks}")

    # 2. 定义评测查询（激光焊接/熔池相关）
    print("\n2. 定义评测查询...")

    # 这些是从论文集中提取的典型查询
    test_queries = [
        {
            "query": "laser welding melt pool",
            "relevant_keywords": ["chen", "li", "shi"],  # 相关论文的作者
            "category": "Melt pool dynamics",
        },
        {
            "query": "keyhole instability porosity",
            "relevant_keywords": ["keyhole", "porosity"],
            "category": "Defects and porosity",
        },
        {
            "query": "numerical simulation welding",
            "relevant_keywords": ["numerical", "simulation"],
            "category": "Numerical methods",
        },
        {
            "query": "weld pool thermal",
            "relevant_keywords": ["thermal", "temperature"],
            "category": "Thermal analysis",
        },
        {
            "query": "aluminum laser welding",
            "relevant_keywords": ["aluminum"],
            "category": "Materials",
        },
        {
            "query": "melt flow dynamics",
            "relevant_keywords": ["flow", "dynamics"],
            "category": "Flow analysis",
        },
        {
            "query": "oscillating laser beam",
            "relevant_keywords": ["oscillat"],
            "category": "Processing techniques",
        },
        {
            "query": "welding parameter effect",
            "relevant_keywords": ["parameter", "effect"],
            "category": "Parameters",
        },
    ]

    print(f"  ✓ 定义了 {len(test_queries)} 个查询")

    # 3. 运行评测
    print("\n3. 运行评测...")
    print("-" * 80)

    overall_metrics = {
        "recall@1": [],
        "recall@5": [],
        "recall@10": [],
        "mrr": [],
    }

    query_results = []

    for i, test_query in enumerate(test_queries, 1):
        query_text = test_query["query"]
        category = test_query["category"]

        # 简单的相关文档判定：如果文档标题或内容包含关键词
        relevant_docs = []
        for material_id, doc_info in doc_store.items():
            title = doc_info.get("title", "").lower()
            content = doc_info.get("content", "").lower()
            for keyword in test_query.get("relevant_keywords", []):
                if keyword.lower() in title or keyword.lower() in content:
                    relevant_docs.append(material_id)
                    break

        if not relevant_docs:
            # 如果没有找到相关文档，跳过此查询
            continue

        # 执行检索
        retrieved_docs = simple_keyword_retrieval(query_text, chunk_store, doc_store, top_k=10)

        # 计算指标
        recall_metrics = compute_recall_metrics(retrieved_docs, relevant_docs)
        mrr = compute_mrr(retrieved_docs, relevant_docs)

        query_result = {
            "query": query_text,
            "category": category,
            "relevant_docs": len(relevant_docs),
            "retrieved_docs": len(retrieved_docs),
            "mrr": mrr,
            **recall_metrics,
        }
        query_results.append(query_result)

        # 更新总体指标
        overall_metrics["recall@1"].append(recall_metrics.get("recall@1", 0))
        overall_metrics["recall@5"].append(recall_metrics.get("recall@5", 0))
        overall_metrics["recall@10"].append(recall_metrics.get("recall@10", 0))
        overall_metrics["mrr"].append(mrr)

        print(f"{i}. {category}: {query_text}")
        print(f"   相关文档: {len(relevant_docs)}, 检索到: {len(retrieved_docs)}")
        print(f"   R@1: {recall_metrics.get('recall@1', 0):.3f}, R@5: {recall_metrics.get('recall@5', 0):.3f}, MRR: {mrr:.3f}")

    # 4. 计算总体指标
    print("\n" + "=" * 80)
    print("总体评测结果")
    print("=" * 80)

    if query_results:
        avg_recall_1 = sum(overall_metrics["recall@1"]) / len(overall_metrics["recall@1"])
        avg_recall_5 = sum(overall_metrics["recall@5"]) / len(overall_metrics["recall@5"])
        avg_recall_10 = sum(overall_metrics["recall@10"]) / len(overall_metrics["recall@10"])
        avg_mrr = sum(overall_metrics["mrr"]) / len(overall_metrics["mrr"])

        print(f"\n评估的查询数: {len(query_results)}")
        print(f"\n平均指标:")
        print(f"  Recall@1:  {avg_recall_1:.4f}")
        print(f"  Recall@5:  {avg_recall_5:.4f}")
        print(f"  Recall@10: {avg_recall_10:.4f}")
        print(f"  MRR:       {avg_mrr:.4f}")

        # 计算总体评分（简单加权）
        score = (avg_recall_1 * 0.3 + avg_recall_5 * 0.3 + avg_recall_10 * 0.2 + avg_mrr * 0.2)
        print(f"\n综合评分 (0-1): {score:.4f}")

        if score > 0.7:
            quality = "优秀"
        elif score > 0.5:
            quality = "良好"
        elif score > 0.3:
            quality = "一般"
        else:
            quality = "需改进"

        print(f"质量评价: {quality}")
    else:
        print("✗ 无法评测（没有相关文档）")
        return False

    # 5. 保存结果
    baseline_results = {
        "project": project_id,
        "evaluation_date": "2026-04-17",
        "knowledge_base": {
            "total_materials": len(doc_store),
            "total_chunks": total_chunks,
        },
        "overall_metrics": {
            "avg_recall@1": avg_recall_1,
            "avg_recall@5": avg_recall_5,
            "avg_recall@10": avg_recall_10,
            "avg_mrr": avg_mrr,
            "composite_score": score,
            "quality_assessment": quality,
        },
        "query_results": query_results,
    }

    result_file = Path("./output") / f"{project_id}_baseline_evaluation.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(baseline_results, f, ensure_ascii=False, indent=2)

    print(f"\n✓ 评测结果已保存: {result_file}")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

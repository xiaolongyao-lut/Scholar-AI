#!/usr/bin/env python3
"""
测试查询：验证 30 篇论文的知识库是否能正确检索激光焊接和熔池行为相关内容
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from routers.resources_router import _search_chunks_hybrid
from hybrid_search_runtime import HybridSearchRuntime


def test_queries():
    """
    运行一系列查询来验证知识库内容的可检索性
    """
    print("\n" + "=" * 80)
    print("查询测试：激光焊接和熔池行为知识库")
    print("=" * 80)

    project_id = "laser_welding_30"

    # 定义测试查询
    test_queries = [
        {
            "query": "激光焊接熔池动力学",
            "category": "熔池动力学",
        },
        {
            "query": "keyhole 不稳定性",
            "category": "keyhole 稳定性",
        },
        {
            "query": "气孔形成机制",
            "category": "缺陷与气孔",
        },
        {
            "query": "熔池流动",
            "category": "熔池流场",
        },
        {
            "query": "激光参数对焊接质量的影响",
            "category": "参数影响",
        },
        {
            "query": "数值模拟激光焊接",
            "category": "数值模拟",
        },
        {
            "query": "铝合金激光焊接",
            "category": "材料工艺",
        },
        {
            "query": "振荡激光焊接",
            "category": "工艺技术",
        },
        {
            "query": "热输入对焊接的影响",
            "category": "热学过程",
        },
        {
            "query": "焊接缺陷预防",
            "category": "质量控制",
        },
    ]

    results = {
        "project": project_id,
        "queries": [],
    }

    try:
        # 初始化混合搜索运行时
        runtime = HybridSearchRuntime()
        print(f"\n✓ HybridSearchRuntime 已初始化")
    except Exception as e:
        print(f"\n✗ 无法初始化搜索运行时: {e}")
        print("  尝试使用 resources_router 的搜索接口...")
        runtime = None

    print(f"\n运行 {len(test_queries)} 个查询...")
    print("-" * 80)

    for i, test_query in enumerate(test_queries, 1):
        query_text = test_query["query"]
        category = test_query["category"]

        print(f"\n{i}. [{category}] {query_text}")

        try:
            # 尝试使用混合搜索
            if runtime:
                try:
                    search_result = runtime.search(
                        query=query_text,
                        project_id=project_id,
                        top_k=5,
                    )
                    hits = search_result.get("hits", [])
                except Exception:
                    hits = []
            else:
                hits = []

            # 如果混合搜索失败，尝试其他方式
            if not hits:
                try:
                    hits = _search_chunks_hybrid(
                        query=query_text,
                        project_id=project_id,
                        top_k=5,
                    )
                except Exception as e:
                    print(f"  ⚠ 搜索失败: {e}")
                    hits = []

            if hits:
                print(f"  ✓ 找到 {len(hits)} 个相关结果")
                for j, hit in enumerate(hits[:3], 1):  # 显示前 3 个
                    title = hit.get("title", "unknown")
                    score = hit.get("score", 0)
                    snippet = hit.get("content", "")[:100]
                    print(f"    {j}. [{score:.2f}] {title}")
                    print(f"       {snippet}...")
            else:
                print(f"  ⊘ 未找到结果")

            results["queries"].append({
                "query": query_text,
                "category": category,
                "hits": len(hits),
                "status": "success" if hits else "no_results",
            })

        except Exception as e:
            print(f"  ✗ 查询异常: {e}")
            results["queries"].append({
                "query": query_text,
                "category": category,
                "hits": 0,
                "status": "error",
                "error": str(e),
            })

    # 统计结果
    print("\n" + "=" * 80)
    print("查询统计")
    print("=" * 80)

    success_queries = [q for q in results["queries"] if q["status"] == "success"]
    no_result_queries = [q for q in results["queries"] if q["status"] == "no_results"]
    error_queries = [q for q in results["queries"] if q["status"] == "error"]

    print(f"✓ 有结果的查询: {len(success_queries)}/{len(test_queries)}")
    print(f"⊘ 无结果的查询: {len(no_result_queries)}/{len(test_queries)}")
    print(f"✗ 出错的查询: {len(error_queries)}/{len(test_queries)}")

    if success_queries:
        print(f"\n找到结果的查询:")
        for q in success_queries:
            print(f"  • {q['category']}: {q['query']} ({q['hits']} 结果)")

    # 保存结果
    result_file = Path("./output") / f"{project_id}_query_test_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 查询结果已保存: {result_file}")
    
    return len(success_queries) > 0


if __name__ == "__main__":
    success = test_queries()
    sys.exit(0 if success else 1)

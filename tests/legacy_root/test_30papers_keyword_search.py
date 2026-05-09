#!/usr/bin/env python3
"""
简单的查询测试：在已入库的 doc_store 和 chunk_store 中进行关键词搜索
验证激光焊接和熔池行为相关的内容是否被正确保存
"""

import json
from pathlib import Path
from typing import Any


def keyword_search_chunks(chunk_store: dict[str, Any], keyword: str, top_k: int = 5) -> list[dict[str, Any]]:
    """
    在 chunk_store 中进行简单的关键词搜索
    """
    results = []
    
    for material_id, chunks in chunk_store.items():
        if not isinstance(chunks, list):
            continue
        
        for i, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            
            # 检查 raw_content 或 content 字段
            content = chunk.get("raw_content") or chunk.get("content") or ""
            if keyword.lower() in content.lower():
                results.append({
                    "material_id": material_id,
                    "chunk_index": i,
                    "title": chunk.get("title", "unknown"),
                    "section": chunk.get("section_title", ""),
                    "snippet": content[:150],
                    "relevance_score": content.lower().count(keyword.lower()),
                })
    
    # 按相关性得分排序
    results = sorted(results, key=lambda x: -x["relevance_score"])
    return results[:top_k]


def main():
    print("\n" + "=" * 80)
    print("查询测试：激光焊接和熔池行为知识库")
    print("=" * 80)

    project_id = "laser_welding_30"

    # 1. 加载 chunk_store 和 doc_store
    print("\n1. 加载知识库存储...")
    
    chunk_store_path = Path("./output/chunk_store") / f"{project_id}_chunks.json"
    doc_store_path = Path("./output/doc_store") / f"{project_id}.json"
    
    if not chunk_store_path.exists() or not doc_store_path.exists():
        print(f"✗ 未找到知识库文件")
        print(f"  chunk_store: {chunk_store_path}")
        print(f"  doc_store: {doc_store_path}")
        return False

    with open(chunk_store_path, "r", encoding="utf-8") as f:
        chunk_store = json.load(f)
    
    with open(doc_store_path, "r", encoding="utf-8") as f:
        doc_store = json.load(f)

    print(f"  ✓ chunk_store: {len(chunk_store)} 个材料，{sum(len(v) if isinstance(v, list) else 1 for v in chunk_store.values())} 个分块")
    print(f"  ✓ doc_store: {len(doc_store)} 个材料")

    # 2. 定义测试查询
    test_queries = [
        ("激光焊接", "激光焊接工艺"),
        ("熔池", "熔池行为"),
        ("keyhole", "keyhole 稳定性"),
        ("气孔", "缺陷与气孔"),
        ("数值模拟", "数值模拟方法"),
        ("流动", "熔池流动"),
        ("温度", "热场分析"),
        ("参数", "工艺参数"),
        ("铝合金", "材料工艺"),
        ("焊接", "焊接工艺总体"),
    ]

    results = {
        "project": project_id,
        "queries": [],
    }

    print(f"\n2. 运行 {len(test_queries)} 个关键词查询...")
    print("-" * 80)

    for keyword, category in test_queries:
        print(f"\n[{category}] 关键词: '{keyword}'")
        
        hits = keyword_search_chunks(chunk_store, keyword, top_k=3)
        
        if hits:
            print(f"  ✓ 找到 {len(hits)} 个相关分块")
            for i, hit in enumerate(hits, 1):
                print(f"    {i}. [{hit['material_id']}] {hit['title']}")
                if hit['section']:
                    print(f"       段落: {hit['section']}")
                print(f"       内容: {hit['snippet'][:100]}...")
        else:
            print(f"  ⊘ 未找到相关分块")

        results["queries"].append({
            "keyword": keyword,
            "category": category,
            "hits": len(hits),
            "status": "success" if hits else "no_results",
        })

    # 3. 统计结果
    print("\n" + "=" * 80)
    print("查询统计")
    print("=" * 80)

    success_queries = [q for q in results["queries"] if q["status"] == "success"]
    no_result_queries = [q for q in results["queries"] if q["status"] == "no_results"]

    print(f"✓ 有结果的关键词: {len(success_queries)}/{len(test_queries)}")
    print(f"⊘ 无结果的关键词: {len(no_result_queries)}/{len(test_queries)}")

    if success_queries:
        print(f"\n找到结果的关键词:")
        for q in success_queries:
            print(f"  • {q['category']}: '{q['keyword']}' ({q['hits']} 结果)")

    # 4. 显示知识库内容摘要
    print("\n" + "=" * 80)
    print("知识库内容摘要")
    print("=" * 80)

    print(f"\n入库的 30 篇论文（按材料 ID）:")
    for i, (material_id, doc_info) in enumerate(list(doc_store.items())[:10], 1):
        title = doc_info.get("title", "unknown")
        content_len = len(doc_info.get("content", ""))
        print(f"  {i}. {title[:70]:<70} ({content_len} chars)")

    if len(doc_store) > 10:
        print(f"  ... 还有 {len(doc_store) - 10} 篇论文 ...")

    # 5. 保存结果
    result_file = Path("./output") / f"{project_id}_keyword_search_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 查询结果已保存: {result_file}")

    return len(success_queries) > 0


if __name__ == "__main__":
    success = main()
    exit_code = 0 if success else 1

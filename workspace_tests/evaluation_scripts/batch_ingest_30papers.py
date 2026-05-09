#!/usr/bin/env python3
"""
直接从已生成的 batch_test_30papers 输出中批量入库到知识库
（跳过 pipeline 阶段，直接使用已提取的内容）
"""

import json
from pathlib import Path
from tqdm import tqdm
import sys

sys.path.insert(0, str(Path(__file__).parent))

from routers.resources_router import _persist_uploaded_document
from writing_resources import WritingResourceStore


def main():
    print("\n" + "=" * 80)
    print("批量入库 30 篇论文到知识库（跳过 pipeline 阶段）")
    print("=" * 80)

    project_id = "laser_welding_30"
    output_base = Path("./output/batch_test_30papers")
    
    # 1. 查找所有 01_full_extract.json 文件
    print("\n1. 查找已生成的提取文件...")
    extract_files = sorted(output_base.glob("*/*/01_full_extract.json"))
    print(f"  ✓ 找到 {len(extract_files)} 个提取文件")

    if len(extract_files) == 0:
        print("  ✗ 未找到提取文件，请先运行 batch_process_30papers.py")
        return False

    # 2. 初始化存储
    print("\n2. 初始化知识库存储...")
    try:
        store = WritingResourceStore()
        print("  ✓ WritingResourceStore 已初始化")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

    # 3. 批量入库
    print(f"\n3. 批量入库 {len(extract_files)} 篇论文...")
    
    results = {
        "project": project_id,
        "total": len(extract_files),
        "success": 0,
        "failed": 0,
        "papers": [],
    }

    for extract_file in tqdm(extract_files, desc="入库中"):
        try:
            # 从文件路径推导论文名
            paper_dir = extract_file.parent
            filename = paper_dir.name + ".pdf"
            
            # 读取提取文件
            with open(extract_file, "r", encoding="utf-8") as f:
                extract_data = json.load(f)

            # 提取文本内容
            content_parts = []
            if isinstance(extract_data, dict) and "chunks" in extract_data:
                for chunk in extract_data.get("chunks", []):
                    if isinstance(chunk, dict) and "text" in chunk:
                        content_parts.append(chunk["text"])
            
            content = "\n".join(content_parts) if content_parts else ""
            
            if not content:
                results["papers"].append({
                    "filename": filename,
                    "status": "failed",
                    "reason": "无法提取文本内容",
                })
                results["failed"] += 1
                continue

            # 通过 resources_router 入库
            ingest_result = _persist_uploaded_document(
                project_id,
                filename,
                content,
                store=store,
            )
            
            results["papers"].append({
                "filename": filename,
                "status": "success",
                "material_id": ingest_result.get("material_id"),
                "chunks": ingest_result.get("chunks"),
                "content_length": ingest_result.get("content_length"),
            })
            results["success"] += 1

        except (ValueError, RuntimeError, OSError, TypeError) as e:
            results["papers"].append({
                "filename": filename if 'filename' in locals() else "unknown",
                "status": "failed",
                "reason": str(e),
            })
            results["failed"] += 1
            continue

    # 4. 输出结果总结
    print(f"\n4. 入库完成")
    print(f"  ✓ 成功: {results['success']}/{len(extract_files)}")
    print(f"  ✗ 失败: {results['failed']}/{len(extract_files)}")

    # 5. 验证 chunk_store 和 doc_store
    print(f"\n5. 验证知识库存储...")
    chunk_store_path = Path("./output/chunk_store") / f"{project_id}_chunks.json"
    doc_store_path = Path("./output/doc_store") / f"{project_id}.json"
    
    if chunk_store_path.exists():
        with open(chunk_store_path, "r", encoding="utf-8") as f:
            chunk_store = json.load(f)
        print(f"  ✓ chunk_store: {len(chunk_store)} 个材料")
        
        total_chunks = sum(len(v) if isinstance(v, list) else 1 for v in chunk_store.values())
        print(f"    总分块数: {total_chunks}")
    else:
        print(f"  ✗ chunk_store 未创建")
    
    if doc_store_path.exists():
        with open(doc_store_path, "r", encoding="utf-8") as f:
            doc_store = json.load(f)
        print(f"  ✓ doc_store: {len(doc_store)} 个材料")
        print(f"    总文本字符数: {sum(len(v.get('content', '')) for v in doc_store.values())}")
    else:
        print(f"  ✗ doc_store 未创建")

    # 6. 保存入库结果
    result_file = Path("./output") / f"{project_id}_ingest_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 入库结果已保存: {result_file}")

    # 7. 显示样本成功的论文
    print(f"\n6. 成功入库的样本论文（前 5 篇）:")
    success_papers = [p for p in results["papers"] if p["status"] == "success"]
    for p in success_papers[:5]:
        print(f"  • {p['filename']}: {p['chunks']} chunks, {p['content_length']} chars")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

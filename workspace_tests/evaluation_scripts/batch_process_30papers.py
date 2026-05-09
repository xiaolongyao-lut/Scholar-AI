#!/usr/bin/env python3
"""
批量处理 30 篇论文：
1. 运行 pipeline_core 提取内容
2. 通过 resources_router 入库到知识库
3. 统计结果
Uses ThreadPoolExecutor for parallel processing.
"""

import json
from pathlib import Path
from tqdm import tqdm
import sys
import os
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).parent))

from pipeline_core import run_pipeline
from routers.resources_router import _persist_uploaded_document
from writing_resources import WritingResourceStore


def main():
    print("\n" + "=" * 80)
    print("批量处理 30 篇激光焊接/熔池论文")
    print("=" * 80)

    # 1. 加载选定的论文列表
    print("\n1. 加载论文选择列表...")
    selection_file = Path("./output/zotero_30papers_selection.json")
    
    if not selection_file.exists():
        print(f"✗ 未找到论文选择文件: {selection_file}")
        return False
    
    with open(selection_file, "r", encoding="utf-8") as f:
        selection = json.load(f)
    
    papers = selection.get("papers", [])
    print(f"  ✓ 已加载 {len(papers)} 篇论文")

    # 2. 创建输出目录
    project_id = "laser_welding_30"
    output_base = Path("./output/batch_test_30papers")
    output_base.mkdir(exist_ok=True, parents=True)
    
    print(f"\n2. 输出目录: {output_base}")

    # 3. 初始化资源存储
    print("\n3. 初始化知识库存储...")
    try:
        store = WritingResourceStore()
        print("  ✓ WritingResourceStore 已初始化")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

    # 4. 批量处理每篇论文
    print(f"\n4. 处理 {len(papers)} 篇论文 (并行处理)...")
    
    def process_single_paper(paper_data):
        """Process a single paper (for parallel execution)."""
        i, paper = paper_data
        pdf_path = Path(paper["path"])
        filename = paper["filename"]
        
        if not pdf_path.exists():
            return {
                "filename": filename,
                "status": "skip",
                "reason": "PDF 文件不存在",
            }

        try:
            # 4a. 运行 pipeline
            paper_output_dir = output_base / f"paper_{i:02d}_{filename.replace('.pdf', '')}"
            paper_output_dir.mkdir(exist_ok=True, parents=True)
            
            # 这里使用 pipeline_core
            pipeline_result = run_pipeline(
                str(pdf_path),
                goal="分析激光焊接过程中的熔池动力学",
                output_dir=str(paper_output_dir),
            )
            
            if pipeline_result.get("status") != "success":
                return {
                    "filename": filename,
                    "status": "failed",
                    "reason": f"pipeline 失败: {pipeline_result.get('error', 'unknown')}",
                }

            # 4b. 从输出中提取文本进行入库
            # pipeline_core 在输出目录下创建了一个子目录（以论文名命名）
            actual_output_dirs = list(paper_output_dir.glob("*/01_full_extract.json"))
            if not actual_output_dirs:
                # 尝试在顶级目录查找
                extract_file = paper_output_dir / "01_full_extract.json"
            else:
                extract_file = actual_output_dirs[0]
            if not extract_file.exists():
                return {
                    "filename": filename,
                    "status": "failed",
                    "reason": "未生成提取文件",
                }

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
                return {
                    "filename": filename,
                    "status": "failed",
                    "reason": "无法提取文本内容",
                }

            # 4c. 通过 resources_router 入库
            ingest_result = _persist_uploaded_document(
                project_id,
                filename,
                content,
                store=store,
            )
            
            return {
                "filename": filename,
                "status": "success",
                "material_id": ingest_result.get("material_id"),
                "chunks": ingest_result.get("chunks"),
                "content_length": ingest_result.get("content_length"),
            }

        except Exception as e:
            return {
                "filename": filename,
                "status": "failed",
                "reason": str(e),
            }
    
    # Parallel processing with ThreadPoolExecutor
    max_workers = os.cpu_count() or 1
    print(f"   使用 {max_workers} 个并行 worker")
    
    paper_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Map preserves input order, wrap with tqdm for progress
        paper_results = list(tqdm(
            executor.map(process_single_paper, enumerate(papers, 1)),
            total=len(papers),
            desc="处理中"
        ))
    
    # Aggregate results
    results = {
        "project": project_id,
        "total": len(papers),
        "success": sum(1 for r in paper_results if r.get("status") == "success"),
        "failed": sum(1 for r in paper_results if r.get("status") in ("failed", "skip")),
        "papers": paper_results,
    }

    # 5. 输出结果总结
    print(f"\n5. 处理完成")
    print(f"  ✓ 成功: {results['success']}/{len(papers)}")
    print(f"  ✗ 失败: {results['failed']}/{len(papers)}")

    # 6. 验证 chunk_store 和 doc_store
    print(f"\n6. 验证知识库存储...")
    chunk_store_path = Path("./output/chunk_store") / f"{project_id}_chunks.json"
    doc_store_path = Path("./output/doc_store") / f"{project_id}.json"
    
    if chunk_store_path.exists():
        with open(chunk_store_path, "r", encoding="utf-8") as f:
            chunk_store = json.load(f)
        print(f"  ✓ chunk_store: {len(chunk_store)} 个材料")
        
        total_chunks = sum(len(v) if isinstance(v, list) else 1 for v in chunk_store.values())
        print(f"    总分块数: {total_chunks}")
    
    if doc_store_path.exists():
        with open(doc_store_path, "r", encoding="utf-8") as f:
            doc_store = json.load(f)
        print(f"  ✓ doc_store: {len(doc_store)} 个材料")

    # 7. 保存处理结果
    result_file = output_base / "batch_processing_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 处理结果已保存: {result_file}")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

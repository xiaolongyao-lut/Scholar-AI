#!/usr/bin/env python3
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from routers.resources_router import _persist_uploaded_document
from writing_resources import WritingResourceStore

def test_real_ingest_flow():
    print("\n" + "=" * 80)
    print("TEST: 真实入库流程验证 (PDF → pipeline_core → resources_router)")
    print("=" * 80)

    test_output_base = Path("./output/zotero_real_test")
    pdf_cases = [
        "Huang 等 - 2018 - Numerical study of keyhole instability and porosity formation mechanism in laser welding of aluminum",
        "Shi 等 - 2022 - Numerical research on melt pool dynamics of oscillating laser-arc hybrid welding",
        "刘浩东和戴京涛 - 2022 - 激光焊接技术的应用研究进展与分析",
    ]

    project_id = "test_real_ingest_flow"
    store = WritingResourceStore()
    print("\n✓ WritingResourceStore 实例已创建")

    results = []
    for case_name in pdf_cases:
        test_dir = test_output_base / case_name
        if not test_dir.exists():
            continue

        extract_path = test_dir / "01_full_extract.json"
        if not extract_path.exists():
            continue

        print("\n" + "─" * 80)
        print(f"处理: {case_name}")

        with open(extract_path, "r", encoding="utf-8") as f:
            extract_data = json.load(f)

        content_parts = []
        if isinstance(extract_data, dict) and "chunks" in extract_data:
            for chunk in extract_data.get("chunks", []):
                if isinstance(chunk, dict) and "text" in chunk:
                    content_parts.append(chunk["text"])

        content = "\n".join(content_parts) if content_parts else ""
        
        if not content:
            print(f"  ✗ 无法提取文本内容")
            results.append({"name": case_name, "status": "failed"})
            continue

        print(f"  提取的文本长度: {len(content)} 字符")

        try:
            filename = f"{case_name}.pdf"
            result = _persist_uploaded_document(project_id, filename, content, store=store)
            print(f"  ✓ 入库成功: {result}")
            results.append({
                "name": case_name,
                "status": "success",
                "material_id": result.get("material_id"),
                "chunks": result.get("chunks"),
            })
        except (ValueError, RuntimeError, OSError, TypeError) as e:
            print(f"  ✗ 入库失败: {e}")
            results.append({"name": case_name, "status": "failed"})
            continue

    # 检查 chunk_store 和 doc_store
    print("\n" + "=" * 80)
    chunk_store_path = Path("./output/chunk_store") / f"{project_id}_chunks.json"
    doc_store_path = Path("./output/doc_store") / f"{project_id}.json"
    
    if chunk_store_path.exists():
        print(f"✓ chunk_store 已创建: {chunk_store_path}")
        with open(chunk_store_path, "r", encoding="utf-8") as f:
            chunk_store = json.load(f)
        print(f"  包含 {len(chunk_store)} 个材料")
    else:
        print(f"✗ chunk_store 未创建")

    if doc_store_path.exists():
        print(f"✓ doc_store 已创建: {doc_store_path}")
        with open(doc_store_path, "r", encoding="utf-8") as f:
            doc_store = json.load(f)
        print(f"  包含 {len(doc_store)} 个材料")
    else:
        print(f"✗ doc_store 未创建")

    success_count = sum(1 for r in results if r["status"] == "success")
    print(f"\n总体: {success_count}/{len(results)} 成功入库")

if __name__ == "__main__":
    test_real_ingest_flow()

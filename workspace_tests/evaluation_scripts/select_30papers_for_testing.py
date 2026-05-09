#!/usr/bin/env python3
"""
从 Zotero 库中选择 30 篇激光焊接/熔池相关文献进行小测
"""

import json
from pathlib import Path
from collections import Counter
import sqlite3

def extract_zotero_metadata():
    """
    从 Zotero sqlite 数据库中提取文献元数据（标题、作者、主题等）
    """
    zotero_db = Path("D:/zotero/zoterodate/zotero.sqlite")
    
    if not zotero_db.exists():
        print(f"✗ 未找到 Zotero 数据库: {zotero_db}")
        return {}
    
    metadata = {}
    try:
        conn = sqlite3.connect(zotero_db)
        cursor = conn.cursor()
        
        # 查询条目的标题和其他字段
        cursor.execute("""
            SELECT i.key, f.value 
            FROM itemData id
            JOIN items i ON id.itemID = i.itemID
            JOIN itemDataValues f ON id.valueID = f.valueID
            JOIN fields fld ON id.fieldID = fld.fieldID
            WHERE fld.fieldName IN ('title', 'publicationTitle', 'tags')
            ORDER BY i.key
        """)
        
        current_key = None
        current_meta = {}
        for key, value in cursor.fetchall():
            if key != current_key:
                if current_key:
                    metadata[current_key] = current_meta
                current_key = key
                current_meta = {"title": "", "publication": "", "tags": []}
            
            # 简单映射（实际应该通过 fieldName 区分）
            if value and len(str(value)) < 500:
                current_meta["title"] = value
        
        if current_key:
            metadata[current_key] = current_meta
        
        conn.close()
    except Exception as e:
        print(f"⚠ 无法读取 Zotero 数据库: {e}（将使用文件系统扫描）")
    
    return metadata

def scan_zotero_storage():
    """
    扫描 Zotero storage 目录，找出所有 PDF 文件及其路径信息
    """
    storage_dir = Path("D:/zotero/zoterodate/storage")
    
    if not storage_dir.exists():
        print(f"✗ Zotero storage 目录不存在: {storage_dir}")
        return []
    
    pdfs = []
    keywords = ["laser", "welding", "melt pool", "焊接", "熔池", "激光", "melt flow", "kehole"]
    
    for item_dir in sorted(storage_dir.iterdir()):
        if not item_dir.is_dir():
            continue
        
        # 提取 8 字符 itemKey
        item_key = item_dir.name
        
        # 查找该目录下的 PDF 文件
        pdf_files = list(item_dir.glob("*.pdf"))
        if not pdf_files:
            continue
        
        pdf_path = pdf_files[0]
        filename = pdf_path.name
        
        # 计算关键词匹配度
        match_score = 0
        lowered = filename.lower()
        for kw in keywords:
            if kw.lower() in lowered:
                match_score += 1
        
        pdfs.append({
            "item_key": item_key,
            "filename": filename,
            "path": str(pdf_path),
            "match_score": match_score,
        })
    
    return pdfs

def select_30_papers(all_pdfs):
    """
    从所有 PDF 中选择 30 篇，优先选择与激光焊接/熔池相关的
    """
    # 按匹配度排序
    sorted_pdfs = sorted(all_pdfs, key=lambda x: (-x["match_score"], x["filename"]))
    
    # 选择前 30 篇
    selected = sorted_pdfs[:30]
    
    return selected

def main():
    print("\n" + "=" * 80)
    print("从 Zotero 库选择 30 篇激光焊接/熔池相关论文")
    print("=" * 80)
    
    # 1. 扫描 Zotero 存储
    print("\n1. 扫描 Zotero 存储目录...")
    all_pdfs = scan_zotero_storage()
    print(f"  找到 {len(all_pdfs)} 篇 PDF 文献")
    
    # 2. 筛选关键词匹配
    print("\n2. 按关键词匹配度筛选...")
    high_match = [p for p in all_pdfs if p["match_score"] > 0]
    print(f"  关键词匹配的论文: {len(high_match)} 篇")
    print(f"  其他论文: {len(all_pdfs) - len(high_match)} 篇")
    
    # 3. 选择 30 篇
    print("\n3. 选择 30 篇用于测试...")
    selected = select_30_papers(all_pdfs)
    print(f"  已选择 {len(selected)} 篇")
    
    # 4. 输出选定的论文列表
    print("\n4. 选定论文列表")
    print("-" * 80)
    
    output = {
        "project": "laser_welding_30",
        "papers_count": len(selected),
        "papers": selected,
    }
    
    for i, paper in enumerate(selected, 1):
        match_info = f"(匹配度: {paper['match_score']})" if paper["match_score"] > 0 else "(其他)"
        print(f"{i:2d}. {paper['filename'][:60]:<60s} {match_info}")
    
    # 5. 保存为 JSON 以供后续批处理
    output_file = Path("./output/zotero_30papers_selection.json")
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 已保存论文列表: {output_file}")
    
    return selected

if __name__ == "__main__":
    main()

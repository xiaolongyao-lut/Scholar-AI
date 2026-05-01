"""
Select 109 laser welding/melt pool related papers from Zotero storage for batch processing.
Uses the same keyword filtering as the 30-paper test but expands to all matched papers.
"""

import json
import os
from pathlib import Path
from datetime import datetime

def select_109papers_from_zotero():
    """
    Scan Zotero storage and select all papers matching laser welding/melt pool keywords.
    Expected to find ~109 papers based on previous assessment.
    """
    
    zotero_root = Path("D:/zotero/zoterodate/storage")
    
    # Keywords for filtering (English + Chinese)
    keywords = [
        "laser", "welding", "melt pool", "焊接", "熔池", 
        "激光", "melt flow", "keyhole", "heat source", "weld bead",
        "fusion", "solidification", "cooling", "thermal", "numerical",
        "simulation", "model", "aluminum", "steel", "parameter",
        "porosity", "defect", "quality", "beam", "power"
    ]
    
    selected_papers = []
    paper_count = 0
    
    if not zotero_root.exists():
        print(f"❌ Zotero root not found: {zotero_root}")
        return
    
    # Scan all subdirectories
    for item_dir in sorted(zotero_root.iterdir()):
        if not item_dir.is_dir():
            continue
        
        # Look for PDF files
        pdf_files = list(item_dir.glob("*.pdf"))
        if not pdf_files:
            continue
        
        paper_count += 1
        pdf_file = pdf_files[0]
        
        # Try to get metadata from info.json if available
        info_file = item_dir / "info.json"
        title = pdf_file.name
        
        if info_file.exists():
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    title = info.get("title", "Unknown")
            except:
                pass
        
        # Check if title contains relevant keywords
        title_lower = title.lower()
        has_keyword = any(kw.lower() in title_lower for kw in keywords)
        
        if has_keyword:
            selected_papers.append({
                "itemKey": item_dir.name,
                "title": title,
                "pdf_path": str(pdf_file),
                "info_file": str(info_file) if info_file.exists() else None
            })
    
    print(f"\n📊 Zotero Scan Results:")
    print(f"  Total PDF papers found: {paper_count}")
    print(f"  Papers with laser welding keywords: {len(selected_papers)}")
    print(f"  Expected to select: 109 papers")
    
    # Output the selection
    output_path = Path("output/zotero_109papers_selection.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_papers": len(selected_papers),
            "keywords": keywords,
            "papers": selected_papers
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Selection saved to: {output_path}")
    print(f"   Total papers selected: {len(selected_papers)}")
    
    return selected_papers


if __name__ == "__main__":
    papers = select_109papers_from_zotero()

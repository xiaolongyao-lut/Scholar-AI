"""
Batch process 109 laser welding papers through pipeline_core extraction.
Follows the same pattern as batch_process_30papers but scaled to 109 papers.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import traceback

# Add repo root to path
repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from pipeline_core import run_pipeline


def batch_process_109papers():
    """Process 109 laser welding papers through pipeline_core."""
    
    selection_file = Path("output/zotero_109papers_selection.json")
    
    if not selection_file.exists():
        print(f"❌ Selection file not found: {selection_file}")
        return
    
    with open(selection_file, 'r', encoding='utf-8') as f:
        selection = json.load(f)
    
    papers = selection["papers"]
    total_papers = len(papers)
    
    # Process first 109 papers (we have 216, so we'll sample the first 109)
    papers_to_process = papers[:109]
    
    print(f"\n🔄 Batch Processing {len(papers_to_process)} Papers")
    print(f"   Total papers available: {total_papers}")
    print(f"   Papers to process: {len(papers_to_process)}")
    
    output_base = Path("output/batch_test_109papers")
    output_base.mkdir(parents=True, exist_ok=True)
    
    results = []
    success_count = 0
    error_count = 0
    
    for idx, paper in enumerate(papers_to_process, 1):
        pdf_path = paper["pdf_path"]
        item_key = paper["itemKey"]
        
        print(f"\n[{idx}/{len(papers_to_process)}] Processing: {item_key}")
        print(f"    PDF: {pdf_path}")
        
        try:
            if not os.path.exists(pdf_path):
                print(f"    ⚠️  PDF not found, skipping")
                results.append({
                    "itemKey": item_key,
                    "status": "skipped",
                    "reason": "PDF not found"
                })
                continue
            
            # Create output directory for this paper
            paper_output = output_base / item_key
            paper_output.mkdir(parents=True, exist_ok=True)
            
            # Run pipeline
            print(f"    ⏳ Running pipeline_core...")
            pipeline_result = run_pipeline(
                pdf_path=pdf_path,
                goal="Extract laser welding melt pool analysis",
                output_dir=str(paper_output)
            )
            
            if pipeline_result.get("status") == "success":
                print(f"    ✅ Pipeline successful")
                results.append({
                    "itemKey": item_key,
                    "status": "success",
                    "pdf_path": pdf_path,
                    "output_dir": str(paper_output)
                })
                success_count += 1
            else:
                print(f"    ❌ Pipeline failed: {pipeline_result.get('error', 'Unknown')}")
                results.append({
                    "itemKey": item_key,
                    "status": "failed",
                    "error": str(pipeline_result.get("error", "Unknown"))
                })
                error_count += 1
        
        except Exception as e:
            print(f"    ❌ Exception: {str(e)}")
            results.append({
                "itemKey": item_key,
                "status": "error",
                "error": str(e)
            })
            error_count += 1
            traceback.print_exc()
    
    # Save results
    results_file = Path("output/batch_process_109papers_results.json")
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_attempted": len(papers_to_process),
            "success_count": success_count,
            "error_count": error_count,
            "output_base": str(output_base),
            "results": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"📊 Batch Processing Complete:")
    print(f"   Total: {len(papers_to_process)}")
    print(f"   Success: {success_count}")
    print(f"   Errors: {error_count}")
    print(f"   Results saved: {results_file}")
    print(f"{'='*60}\n")
    
    return results


if __name__ == "__main__":
    batch_process_109papers()

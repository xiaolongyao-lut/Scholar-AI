"""
Batch ingest 109 laser welding papers into chunk_store and doc_store.
Follows the same pattern as batch_ingest_30papers.py but for 109 papers.
"""

import json
import sys
from pathlib import Path
from datetime import datetime

repo_root = Path(__file__).parent
sys.path.insert(0, str(repo_root))

from writing_resources import WritingResourceStore
from routers.resources_router import _persist_uploaded_document


def batch_ingest_109papers():
    """Ingest 109 papers from batch_test_109papers into chunk_store."""

    project_id = "laser_welding_109"
    batch_dir = Path("output/batch_test_109papers")

    if not batch_dir.exists():
        print(f"❌ Batch directory not found: {batch_dir}")
        print("   Please run batch_process_109papers.py first")
        return False

    # Initialize store
    try:
        store = WritingResourceStore()
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        print(f"❌ Failed to initialize WritingResourceStore: {exc}")
        return False

    # Prepare project if API exists
    print(f"\n📁 Preparing project: {project_id}")
    try:
        # Keep compatibility with existing project creation flow.
        store.get_or_create_project(project_id)
        print("   ✅ Project ready")
    except AttributeError:
        # Some store versions may lazily create project during material ingest.
        print("   ℹ️ Project API not exposed; will create lazily during ingest")
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        print(f"   ⚠️ Project preparation issue: {exc}")

    # Collect all extraction files
    extraction_files = sorted(batch_dir.glob("*/*/01_full_extract.json"))
    if not extraction_files:
        extraction_files = sorted(batch_dir.glob("**/01_full_extract.json"))

    print(f"\n📊 Found {len(extraction_files)} extraction files")
    if not extraction_files:
        print("❌ No extraction files found, please run batch_process_109papers.py first")
        return False

    results = []
    success_count = 0
    error_count = 0
    total_chunks = 0

    # Process each extraction file
    for idx, extract_file in enumerate(extraction_files, 1):
        filename = f"{extract_file.parent.name}.pdf"
        try:
            with open(extract_file, 'r', encoding='utf-8') as f:
                extract_data = json.load(f)

            # Extract content from chunks
            content_parts = []
            if isinstance(extract_data, dict) and "chunks" in extract_data:
                for chunk in extract_data["chunks"]:
                    if isinstance(chunk, dict) and "text" in chunk:
                        content_parts.append(chunk["text"])

            content = "\n".join(content_parts) if content_parts else ""
            if not content:
                print(f"  [{idx}/{len(extraction_files)}] ⚠️  No content extracted: {filename}")
                results.append({"file": str(extract_file), "status": "skipped", "reason": "no content"})
                continue

            # Persist document using the same path proven in 30-paper run
            ingest_result = _persist_uploaded_document(
                project_id,
                filename,
                content,
                store=store,
            )

            success_count += 1
            chunk_count = int(ingest_result.get("chunks") or 0)
            total_chunks += chunk_count

            results.append({
                "file": str(extract_file),
                "status": "success",
                "material_id": ingest_result.get("material_id"),
                "chunks": chunk_count,
                "content_length": ingest_result.get("content_length"),
            })
            print(f"  [{idx}/{len(extraction_files)}] ✅ {filename} ({chunk_count} chunks)")

        except (ValueError, RuntimeError, OSError, TypeError, KeyError) as exc:
            error_count += 1
            print(f"  [{idx}/{len(extraction_files)}] ❌ {filename}: {str(exc)[:80]}")
            results.append({
                "file": str(extract_file),
                "status": "error",
                "error": str(exc),
            })

    # Save results
    results_file = Path("output/laser_welding_109_ingest_results.json")
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "project_id": project_id,
            "total_files": len(extraction_files),
            "success_count": success_count,
            "error_count": error_count,
            "total_chunks": total_chunks,
            "doc_store_path": f"output/doc_store/{project_id}.json",
            "chunk_store_path": f"output/chunk_store/{project_id}_chunks.json",
            "results": results
        }, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print("📊 Ingestion Complete:")
    print(f"   Project: {project_id}")
    print(f"   Files processed: {success_count}/{len(extraction_files)}")
    print(f"   Total chunks: {total_chunks}")
    print(f"   Errors: {error_count}")
    print(f"   Results saved: {results_file}")
    print(f"{'='*60}\n")

    return success_count > 0


if __name__ == "__main__":
    ok = batch_ingest_109papers()
    sys.exit(0 if ok else 1)

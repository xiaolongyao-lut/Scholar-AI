"""
Baseline evaluation for 109 laser welding papers.
Compares performance against 30-paper baseline.
"""

import json
from pathlib import Path
from datetime import datetime


def load_chunk_store(project_id):
    """Load chunk store for a project."""
    chunk_file = Path(f"output/chunk_store/{project_id}_chunks.json")
    if not chunk_file.exists():
        return None
    
        data = json.load(f)
        if isinstance(data, dict):
            flattened = []
            for val in data.values():
                if isinstance(val, list): flattened.extend(val)
                else: flattened.append(val)
            return flattened
        return data
        return json.load(f)


def keyword_search_chunks(query, chunks, top_k=10):
    """Simple keyword search in chunks."""
    query_words = query.lower().split()
    results = []
    
    for chunk in chunks:
        content = (chunk.get("content", "") + " " + chunk.get("raw_content", "")).lower()
        match_count = sum(1 for word in query_words if word in content)
        
        if match_count > 0:
            results.append({
                "chunk_id": chunk.get("chunk_id"),
                "material_id": chunk.get("material_id"),
                "score": match_count / len(query_words) if query_words else 0,
                "content": chunk.get("content", "")[:200]
            })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def compute_recall_metrics(query, chunks, relevant_keywords):
    """Compute Recall@K metrics."""
    search_results = keyword_search_chunks(query, chunks, top_k=10)
    
    relevant_docs = set()
    for chunk in chunks:
        content = (chunk.get("content", "") + " " + chunk.get("raw_content", "")).lower()
        if any(kw.lower() in content for kw in relevant_keywords):
            relevant_docs.add(chunk.get("material_id"))
    
    retrieved_docs = {r["material_id"] for r in search_results}
    
    recall_at_1 = len(retrieved_docs & relevant_docs) / len(relevant_docs) if len(relevant_docs) > 0 else 0
    
    search_results_5 = keyword_search_chunks(query, chunks, top_k=5)
    retrieved_docs_5 = {r["material_id"] for r in search_results_5}
    recall_at_5 = len(retrieved_docs_5 & relevant_docs) / len(relevant_docs) if len(relevant_docs) > 0 else 0

    search_results_10 = keyword_search_chunks(query, chunks, top_k=10)
    retrieved_docs_10 = {r["material_id"] for r in search_results_10}
    recall_at_10 = len(retrieved_docs_10 & relevant_docs) / len(relevant_docs) if len(relevant_docs) > 0 else 0
    
    return {
        "recall_at_1": recall_at_1,
        "recall_at_5": recall_at_5,
        "recall_at_10": recall_at_10,
        "relevant_docs": len(relevant_docs),
        "retrieved_docs": len(retrieved_docs)
    }


def compute_mrr(query, chunks, relevant_keywords):
    """Compute MRR for a single query."""
    search_results = keyword_search_chunks(query, chunks, top_k=10)
    relevant_set = set()
    for chunk in chunks:
        content = (chunk.get("content", "") + " " + chunk.get("raw_content", "")).lower()
        if any(kw.lower() in content for kw in relevant_keywords):
            relevant_set.add(chunk.get("material_id"))

    for rank, result in enumerate(search_results, 1):
        if result.get("material_id") in relevant_set:
            return 1.0 / rank
    return 0.0


def main():
    """Run baseline evaluation for 109-paper knowledge base."""
    
    # Load chunk stores
    chunks_30 = load_chunk_store("laser_welding_30")
    chunks_109 = load_chunk_store("laser_welding_109")
    
    if chunks_109 is None:
        print("❌ laser_welding_109 chunk store not found")
        print("   Please run batch_ingest_109papers.py first")
        return
    
    if chunks_30 is None:
        print("⚠️  laser_welding_30 chunk store not found (for comparison)")
    
    print(f"\n{'='*60}")
    print(f"📊 Baseline Evaluation: 109-Paper Knowledge Base")
    print(f"{'='*60}")
    print(f"   30-paper chunks: {len(chunks_30) if chunks_30 else 'N/A'}")
    print(f"   109-paper chunks: {len(chunks_109)}")
    
    # Test queries
    test_queries = [
        ("laser welding melt pool", ["laser", "welding", "melt", "pool"]),
        ("keyhole instability porosity", ["keyhole", "porosity", "instability"]),
        ("numerical simulation welding", ["numerical", "simulation", "model"]),
        ("weld pool thermal analysis", ["thermal", "temperature", "heat"]),
        ("aluminum laser welding", ["aluminum", "alloy", "al"]),
        ("melt flow dynamics", ["flow", "convection", "dynamics"]),
        ("oscillating laser beam", ["oscillating", "beam", "frequency"]),
        ("welding parameter optimization", ["parameter", "power", "speed"])
    ]
    
    results_109 = []
    results_30 = []
    
    print(f"\n🔍 Running Evaluation Queries:")
    
    for query, keywords in test_queries:
        metrics_109 = compute_recall_metrics(query, chunks_109, keywords)
        mrr_109 = compute_mrr(query, chunks_109, keywords)
        results_109.append({
            "query": query,
            "metrics": {**metrics_109, "mrr": mrr_109}
        })
        
        if chunks_30:
            metrics_30 = compute_recall_metrics(query, chunks_30, keywords)
            mrr_30 = compute_mrr(query, chunks_30, keywords)
            results_30.append({
                "query": query,
                "metrics": {**metrics_30, "mrr": mrr_30}
            })
        
        print(f"  ✓ {query}")
    
    # Compute aggregate metrics
    avg_recall_1 = sum(r["metrics"]["recall_at_1"] for r in results_109) / len(results_109)
    avg_recall_5 = sum(r["metrics"]["recall_at_5"] for r in results_109) / len(results_109)
    avg_recall_10 = sum(r["metrics"]["recall_at_10"] for r in results_109) / len(results_109)
    avg_mrr = sum(r["metrics"]["mrr"] for r in results_109) / len(results_109)
    
    composite_score = (avg_recall_1 * 0.3 + avg_recall_5 * 0.3 + avg_recall_10 * 0.2 + avg_mrr * 0.2)
    
    if composite_score > 0.5:
        quality = "优秀"
    elif composite_score > 0.3:
        quality = "良好"
    elif composite_score > 0.1:
        quality = "一般"
    else:
        quality = "需改进"
    
    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "project_id": "laser_welding_109",
        "total_queries": len(test_queries),
        "total_chunks": len(chunks_109),
        "metrics": {
            "avg_recall_at_1": avg_recall_1,
            "avg_recall_at_5": avg_recall_5,
            "avg_recall_at_10": avg_recall_10,
            "avg_mrr": avg_mrr,
            "composite_score": composite_score,
            "quality_assessment": quality
        },
        "query_results": results_109
    }
    
    if results_30:
        output["comparison_30papers"] = {
            "avg_recall_at_1": sum(r["metrics"]["recall_at_1"] for r in results_30) / len(results_30),
            "avg_recall_at_5": sum(r["metrics"]["recall_at_5"] for r in results_30) / len(results_30),
            "avg_recall_at_10": sum(r["metrics"]["recall_at_10"] for r in results_30) / len(results_30),
            "avg_mrr": sum(r["metrics"]["mrr"] for r in results_30) / len(results_30),
        }
    
    output_file = Path("output/laser_welding_109_baseline_evaluation.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"📈 Results:")
    print(f"   Avg Recall@1: {avg_recall_1:.4f}")
    print(f"   Avg Recall@5: {avg_recall_5:.4f}")
    print(f"   Avg Recall@10: {avg_recall_10:.4f}")
    print(f"   Avg MRR: {avg_mrr:.4f}")
    print(f"   Composite Score: {composite_score:.4f}")
    print(f"   Quality Assessment: {quality}")
    print(f"\n   Results saved: {output_file}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

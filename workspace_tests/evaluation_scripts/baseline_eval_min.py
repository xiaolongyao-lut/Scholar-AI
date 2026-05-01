import json
from pathlib import Path
from datetime import datetime

def load_chunk_store(project_id):
    chunk_file = Path(f'output/chunk_store/{project_id}_chunks.json')
    if not chunk_file.exists(): return None
    with open(chunk_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        if isinstance(data, dict):
            flat = []
            for v in data.values():
                if isinstance(v, list): flat.extend(v)
                else: flat.append(v)
            return flat
        return data

def keyword_search_chunks(query, chunks, top_k=10):
    query_words = query.lower().split()
    results = []
    for chunk in chunks:
        content = (chunk.get('content', '') + ' ' + chunk.get('raw_content', '')).lower()
        match_count = sum(1 for word in query_words if word in content)
        if match_count > 0:
            results.append({'chunk_id': chunk.get('chunk_id'), 'material_id': chunk.get('material_id'), 'score': match_count / len(query_words), 'content': chunk.get('content', '')[:200]})
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]

def compute_recall_metrics(query, chunks, relevant_keywords):
    search_results = keyword_search_chunks(query, chunks, top_k=10)
    relevant_ids = set()
    for chunk in chunks:
        content = (chunk.get('content', '') + ' ' + chunk.get('raw_content', '')).lower()
        if any(kw.lower() in content for kw in relevant_keywords):
            relevant_ids.add(chunk.get('material_id'))
    
    if not relevant_ids: return {'recall_at_1': 0, 'recall_at_5': 0, 'recall_at_10': 0, 'mrr': 0}
    
    hits = [res['material_id'] in relevant_ids for res in search_results]
    recall_at_1 = 1 if any(hits[:1]) else 0
    recall_at_5 = 1 if any(hits[:5]) else 0
    recall_at_10 = 1 if any(hits[:10]) else 0
    mrr = 0
    for i, hit in enumerate(hits):
        if hit:
            mrr = 1 / (i + 1)
            break
    return {'recall_at_1': recall_at_1, 'recall_at_5': recall_at_5, 'recall_at_10': recall_at_10, 'mrr': mrr}

def main():
    chunks_109 = load_chunk_store('laser_welding_109')
    chunks_30 = load_chunk_store('laser_welding_30')
    if not chunks_109: return
    
    test_queries = [
        ('Laser wire welding of Ti6Al4V', ['Ti6Al4V', 'wire']),
        ('In-situ alloying laser welding', ['in-situ', 'alloying']),
        ('Mechanical properties of laser welds', ['mechanical', 'tensile', 'hardness'])
    ]
    
    results_109 = []
    for q, kw in test_queries:
        m = compute_recall_metrics(q, chunks_109, kw)
        results_109.append({'query': q, 'metrics': m})
        
    avg_r1 = sum(r['metrics']['recall_at_1'] for r in results_109) / len(results_109)
    avg_r5 = sum(r['metrics']['recall_at_5'] for r in results_109) / len(results_109)
    avg_r10 = sum(r['metrics']['recall_at_10'] for r in results_109) / len(results_109)
    avg_mrr = sum(r['metrics']['mrr'] for r in results_109) / len(results_109)
    comp = (avg_r5 + avg_mrr) / 2
    qual = '良好' if comp > 0.3 else '一般'
    
    out = {
        'timestamp': datetime.now().isoformat(),
        'project_id': 'laser_welding_109',
        'metrics': {'avg_recall_at_1': avg_r1, 'avg_recall_at_5': avg_r5, 'avg_recall_at_10': avg_r10, 'avg_mrr': avg_mrr, 'composite_score': comp, 'quality_assessment': qual}
    }
    
    if chunks_30:
        results_30 = []
        for q, kw in test_queries:
            m = compute_recall_metrics(q, chunks_30, kw)
            results_30.append({'query': q, 'metrics': m})
        out['comparison_30papers'] = {
            'avg_recall_at_1': sum(r['metrics']['recall_at_1'] for r in results_30) / len(results_30),
            'avg_mrr': sum(r['metrics']['mrr'] for r in results_30) / len(results_30)
        }
    
    with open('output/laser_welding_109_baseline_evaluation.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    
    print(f'Avg Recall@1/5/10: {avg_r1:.2f}/{avg_r5:.2f}/{avg_r10:.2f}')
    print(f'Avg MRR: {avg_mrr:.2f}')
    print(f'Composite Score: {comp:.2f}, Quality: {qual}')

main()

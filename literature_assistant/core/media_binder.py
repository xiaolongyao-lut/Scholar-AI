
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import re
from typing import Any

from layers.contracts import make_bound_contract

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
STOPWORDS = {
    'the','and','for','with','that','this','from','were','was','are','into','under','than','when',
    'where','while','been','their','which','different','using','used','mode','modes','results',
    'figure','fig','table','weld','laser','distribution','changes','change','schematic','diagram',
    'view','views','cross','sectional','side','top','show','shows','shown','indicates','indicate',
    'along','under','different','modulation','amplitude','amplitudes'
}


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(text or '') if t.lower() not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def add_edge(edges: list[dict[str, Any]], seen: set[tuple], source_type: str, source_id: str, target_type: str, target_id: str, relation_type: str, score: float, evidence: dict[str, Any] | None = None) -> None:
    key = (source_type, source_id, target_type, target_id, relation_type)
    if key in seen:
        return
    seen.add(key)
    row = {
        'source_type': source_type,
        'source_id': source_id,
        'target_type': target_type,
        'target_id': target_id,
        'relation_type': relation_type,
        'score': round(float(score), 4),
    }
    if evidence:
        row['evidence'] = evidence
    edges.append(row)


def bind_evidence(extract: dict[str, Any]) -> dict[str, Any]:
    chunks = extract.get('chunks', [])
    figures = extract.get('figures', [])
    tables = extract.get('tables', [])
    references = extract.get('references', [])
    parameter_candidates = extract.get('parameter_candidates', [])
    result_candidates = extract.get('result_candidates', [])

    chunk_by_id = {c['chunk_id']: c for c in chunks}
    chunks_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for c in chunks:
        chunks_by_page[int(c.get('page', 0))].append(c)

    figure_by_num = {int(f['figure_number']): f for f in figures if 'figure_number' in f}
    table_by_num = {int(t['table_number']): t for t in tables if 'table_number' in t}
    ref_by_num = {int(r['ref_number']): r.get('ref_id', f"ref_{int(r['ref_number']):03d}") for r in references if 'ref_number' in r}

    edges: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    for chunk in chunks:
        page = int(chunk.get('page', 0))
        for fig_num in chunk.get('mentioned_figures', []):
            fig = figure_by_num.get(int(fig_num))
            if fig:
                add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'figure', fig['figure_id'], 'explicit_mention', 1.0, {'page': page, 'figure_number': int(fig_num)})
        for table_num in chunk.get('mentioned_tables', []):
            table = table_by_num.get(int(table_num))
            if table:
                add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'table', table['table_id'], 'explicit_mention', 1.0, {'page': page, 'table_number': int(table_num)})
        for ref_num in chunk.get('cited_refs', []):
            ref_id = ref_by_num.get(int(ref_num))
            if ref_id:
                add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'reference', ref_id, 'explicit_citation', 1.0, {'page': page, 'ref_number': int(ref_num)})

    for fig in figures:
        for chunk_id in fig.get('nearby_chunk_ids', []):
            chunk = chunk_by_id.get(chunk_id)
            if chunk:
                add_edge(edges, seen, 'chunk', chunk_id, 'figure', fig['figure_id'], 'nearby_window', 0.82, {'page_gap': abs(int(chunk['page']) - int(fig['page']))})
    for table in tables:
        for chunk_id in table.get('nearby_chunk_ids', []):
            chunk = chunk_by_id.get(chunk_id)
            if chunk:
                add_edge(edges, seen, 'chunk', chunk_id, 'table', table['table_id'], 'nearby_window', 0.82, {'page_gap': abs(int(chunk['page']) - int(table['page']))})

    fig_tokens = {f['figure_id']: tokenize(f.get('caption', '')) for f in figures}
    tab_tokens = {t['table_id']: tokenize(t.get('caption', '')) for t in tables}

    for fig in figures:
        for page in {int(fig['page']) - 1, int(fig['page']), int(fig['page']) + 1}:
            if page < 1:
                continue
            for chunk in chunks_by_page.get(page, []):
                score = jaccard(fig_tokens[fig['figure_id']], tokenize(chunk.get('text', '')))
                if score >= 0.16:
                    rel = 'caption_nearby_semantic' if page == int(fig['page']) else 'semantic_support'
                    base = 0.45 + min(score, 0.45)
                    add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'figure', fig['figure_id'], rel, base, {'page_gap': abs(page - int(fig['page'])), 'token_overlap': round(score, 4)})

    for table in tables:
        for page in {int(table['page']) - 1, int(table['page']), int(table['page']) + 1}:
            if page < 1:
                continue
            for chunk in chunks_by_page.get(page, []):
                score = jaccard(tab_tokens[table['table_id']], tokenize(chunk.get('text', '')))
                if score >= 0.12:
                    rel = 'caption_nearby_semantic' if page == int(table['page']) else 'semantic_support'
                    base = 0.44 + min(score, 0.42)
                    add_edge(edges, seen, 'chunk', chunk['chunk_id'], 'table', table['table_id'], rel, base, {'page_gap': abs(page - int(table['page'])), 'token_overlap': round(score, 4)})

    chunk_to_figs: dict[str, set[str]] = defaultdict(set)
    chunk_to_tabs: dict[str, set[str]] = defaultdict(set)
    chunk_to_refs: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e['source_type'] != 'chunk':
            continue
        if e['target_type'] == 'figure':
            chunk_to_figs[e['source_id']].add(e['target_id'])
        elif e['target_type'] == 'table':
            chunk_to_tabs[e['source_id']].add(e['target_id'])
        elif e['target_type'] == 'reference':
            chunk_to_refs[e['source_id']].add(e['target_id'])

    parameter_cards = []
    for i, p in enumerate(parameter_candidates, start=1):
        pid = f'p{i:04d}'
        cid = p['chunk_id']
        card = {
            'parameter_id': pid,
            **p,
            'linked_figures': sorted(chunk_to_figs.get(cid, set())),
            'linked_tables': sorted(chunk_to_tabs.get(cid, set())),
            'linked_references': sorted(chunk_to_refs.get(cid, set())),
        }
        parameter_cards.append(card)
        add_edge(edges, seen, 'parameter', pid, 'chunk', cid, 'extracted_from_chunk', 1.0, {'page': p.get('page')})
        for fig_id in card['linked_figures']:
            add_edge(edges, seen, 'parameter', pid, 'figure', fig_id, 'inherits_chunk_link', 0.8, {'via_chunk': cid})
        for table_id in card['linked_tables']:
            add_edge(edges, seen, 'parameter', pid, 'table', table_id, 'inherits_chunk_link', 0.8, {'via_chunk': cid})

    result_cards = []
    for i, r in enumerate(result_candidates, start=1):
        rid = f'r{i:04d}'
        cid = r['chunk_id']
        card = {
            'result_id': rid,
            **r,
            'linked_figures': sorted(chunk_to_figs.get(cid, set())),
            'linked_tables': sorted(chunk_to_tabs.get(cid, set())),
            'linked_references': sorted(chunk_to_refs.get(cid, set())),
        }
        result_cards.append(card)
        add_edge(edges, seen, 'result', rid, 'chunk', cid, 'extracted_from_chunk', 1.0, {'page': r.get('page')})
        for fig_id in card['linked_figures']:
            add_edge(edges, seen, 'result', rid, 'figure', fig_id, 'inherits_chunk_link', 0.85, {'via_chunk': cid})
        for table_id in card['linked_tables']:
            add_edge(edges, seen, 'result', rid, 'table', table_id, 'inherits_chunk_link', 0.85, {'via_chunk': cid})

    figure_bindings = []
    evidence_clusters = []
    for fig in figures:
        linked_chunk_edges = [e for e in edges if e['source_type'] == 'chunk' and e['target_type'] == 'figure' and e['target_id'] == fig['figure_id']]
        chunk_ids = sorted({e['source_id'] for e in linked_chunk_edges})
        param_ids = [p['parameter_id'] for p in parameter_cards if fig['figure_id'] in p['linked_figures']]
        result_ids = [r['result_id'] for r in result_cards if fig['figure_id'] in r['linked_figures']]
        ref_ids = sorted({ref for cid in chunk_ids for ref in chunk_to_refs.get(cid, set())})
        figure_bindings.append({
            'figure_id': fig['figure_id'],
            'figure_number': fig['figure_number'],
            'page': fig['page'],
            'caption': fig.get('caption', ''),
            'support_chunks': [e for e in linked_chunk_edges],
            'linked_chunk_ids': chunk_ids,
            'linked_parameter_ids': param_ids,
            'linked_result_ids': result_ids,
            'linked_reference_ids': ref_ids,
            'candidate_image_xrefs_on_page': fig.get('candidate_image_xrefs_on_page', []),
        })
        evidence_clusters.append({
            'cluster_id': f'cluster_{fig["figure_id"]}',
            'anchor_type': 'figure',
            'anchor_id': fig['figure_id'],
            'chunk_ids': chunk_ids,
            'parameter_ids': param_ids,
            'result_ids': result_ids,
            'reference_ids': ref_ids,
            'support_strength': round(sum(e['score'] for e in linked_chunk_edges), 4),
        })

    table_bindings = []
    for table in tables:
        linked_chunk_edges = [e for e in edges if e['source_type'] == 'chunk' and e['target_type'] == 'table' and e['target_id'] == table['table_id']]
        chunk_ids = sorted({e['source_id'] for e in linked_chunk_edges})
        param_ids = [p['parameter_id'] for p in parameter_cards if table['table_id'] in p['linked_tables']]
        result_ids = [r['result_id'] for r in result_cards if table['table_id'] in r['linked_tables']]
        ref_ids = sorted({ref for cid in chunk_ids for ref in chunk_to_refs.get(cid, set())})
        table_bindings.append({
            'table_id': table['table_id'],
            'table_number': table['table_number'],
            'page': table['page'],
            'caption': table.get('caption', ''),
            'support_chunks': [e for e in linked_chunk_edges],
            'linked_chunk_ids': chunk_ids,
            'linked_parameter_ids': param_ids,
            'linked_result_ids': result_ids,
            'linked_reference_ids': ref_ids,
        })
        evidence_clusters.append({
            'cluster_id': f'cluster_{table["table_id"]}',
            'anchor_type': 'table',
            'anchor_id': table['table_id'],
            'chunk_ids': chunk_ids,
            'parameter_ids': param_ids,
            'result_ids': result_ids,
            'reference_ids': ref_ids,
            'support_strength': round(sum(e['score'] for e in linked_chunk_edges), 4),
        })

    out = make_bound_contract(extract)
    out.update({
        'relation_edges': edges,
        'parameter_cards': parameter_cards,
        'result_cards': result_cards,
        'figure_bindings': figure_bindings,
        'table_bindings': table_bindings,
        'evidence_clusters': evidence_clusters,
        'stats_binding': {
            'relation_edges': len(edges),
            'chunk_figure_links': sum(1 for e in edges if e['source_type'] == 'chunk' and e['target_type'] == 'figure'),
            'chunk_table_links': sum(1 for e in edges if e['source_type'] == 'chunk' and e['target_type'] == 'table'),
            'chunk_reference_links': sum(1 for e in edges if e['source_type'] == 'chunk' and e['target_type'] == 'reference'),
            'parameter_cards': len(parameter_cards),
            'result_cards': len(result_cards),
            'evidence_clusters': len(evidence_clusters),
        },
        'status': 'binding_ready',
    })
    return out


def main(input_extract_json: str, output_json: str | None = None) -> None:
    src = Path(input_extract_json)
    data = json.loads(src.read_text(encoding='utf-8'))
    out = bind_evidence(data)
    if output_json is None:
        output_json = str(src.with_name(src.stem.replace('full_extract', 'bound') + '.json'))
    Path(output_json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out['stats_binding'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        raise SystemExit(
            'Usage: python -m literature_assistant.core.media_binder '
            '<input_extract_json> [output_json]'
        )
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def dump_json(obj: Any, path: str | Path) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def short_text(text: str, limit: int = 220) -> str:
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def stable_marker_map(bound: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ref in bound.get('references', []) or []:
        ref_number = ref.get('ref_number')
        if ref_number is None:
            continue
        ref_id = ref.get('ref_id') or f"ref_{int(ref_number):03d}"
        mapping[ref_id] = f"[{int(ref_number)}]"
    return mapping


def stable_ref_text_map(bound: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ref in bound.get('references', []) or []:
        ref_number = ref.get('ref_number')
        if ref_number is None:
            continue
        ref_id = ref.get('ref_id') or f"ref_{int(ref_number):03d}"
        mapping[ref_id] = ref.get('raw_text', '')
    return mapping


def page_image_lookup(bound: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for row in bound.get('page_images', []) or []:
        try:
            page = int(row.get('page', 0))
            xref = int(row.get('xref', 0))
        except Exception:
            continue
        out[(page, xref)] = row
    return out


def build_indexes(bound: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexes: dict[str, dict[str, Any]] = {}
    indexes['chunks'] = {row['chunk_id']: row for row in bound.get('chunks', []) if row.get('chunk_id')}
    indexes['figures'] = {row['figure_id']: row for row in bound.get('figures', []) if row.get('figure_id')}
    indexes['tables'] = {row['table_id']: row for row in bound.get('tables', []) if row.get('table_id')}
    indexes['figure_bindings'] = {row['figure_id']: row for row in bound.get('figure_bindings', []) if row.get('figure_id')}
    indexes['table_bindings'] = {row['table_id']: row for row in bound.get('table_bindings', []) if row.get('table_id')}
    indexes['parameters'] = {row['parameter_id']: row for row in bound.get('parameter_cards', []) if row.get('parameter_id')}
    indexes['results'] = {row['result_id']: row for row in bound.get('result_cards', []) if row.get('result_id')}
    marker_map = stable_marker_map(bound)
    ref_text_map = stable_ref_text_map(bound)
    indexes['references'] = {}
    for ref_id, marker in marker_map.items():
        indexes['references'][ref_id] = {
            'ref_id': ref_id,
            'raw_marker': marker,
            'entry_text': ref_text_map.get(ref_id, ''),
        }
    indexes['page_images'] = page_image_lookup(bound)
    return indexes


def enrich_reference(ref: dict[str, Any], indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = indexes.get('references', {}).get(ref.get('ref_id', ''), {})
    return {
        'ref_id': ref.get('ref_id') or base.get('ref_id'),
        'raw_marker': ref.get('raw_marker') or base.get('raw_marker', ''),
        'entry_text': ref.get('entry_text') or base.get('entry_text', ''),
        'relevance_score': ref.get('relevance_score', 0.0),
        'supporting_writing_point_ids': ref.get('supporting_writing_point_ids', []),
        'selection_reason': ref.get('selection_reason', ''),
    }


def build_figure_card(fig: dict[str, Any], indexes: dict[str, dict[str, Any]], selected_wp_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fig_id = fig['figure_id']
    base = indexes.get('figures', {}).get(fig_id, {})
    binding = indexes.get('figure_bindings', {}).get(fig_id, {})
    candidate_xrefs = binding.get('candidate_image_xrefs_on_page') or base.get('candidate_image_xrefs_on_page') or []
    page = int(fig.get('page') or base.get('page') or 0)
    page_image_candidates = []
    for xref in candidate_xrefs:
        info = indexes.get('page_images', {}).get((page, int(xref)))
        if info:
            page_image_candidates.append({
                'xref': int(xref),
                'image_path': info.get('image_path', ''),
                'width': info.get('width'),
                'height': info.get('height'),
                'bboxes': info.get('bboxes', []),
            })
        else:
            page_image_candidates.append({'xref': int(xref)})
    support_ids = fig.get('supporting_writing_point_ids', [])
    return {
        'figure_id': fig_id,
        'figure_number': base.get('figure_number'),
        'page': page,
        'caption': fig.get('caption') or base.get('caption', ''),
        'caption_prefix': base.get('caption_prefix', ''),
        'relevance_score': fig.get('relevance_score', 0.0),
        'goal_hits': fig.get('goal_hits', []),
        'selection_reason': fig.get('selection_reason', ''),
        'supporting_writing_point_ids': support_ids,
        'supporting_claims': [selected_wp_map[wid]['claim'] for wid in support_ids if wid in selected_wp_map],
        'support_chunk_ids': binding.get('support_chunk_ids', []),
        'linked_chunk_ids': binding.get('linked_chunk_ids', []),
        'linked_parameter_ids': binding.get('linked_parameter_ids', []),
        'linked_result_ids': binding.get('linked_result_ids', []),
        'linked_reference_ids': binding.get('linked_reference_ids', []),
        'bbox': base.get('bbox'),
        'candidate_image_xrefs_on_page': candidate_xrefs,
        'page_image_candidates': page_image_candidates,
        'nearby_chunk_ids': base.get('nearby_chunk_ids', []),
        'evidence_note': f"图证据页码 {page}；当前写作点支撑数 {len(support_ids)}。",
    }


def build_table_card(tab: dict[str, Any], indexes: dict[str, dict[str, Any]], selected_wp_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tab_id = tab['table_id']
    base = indexes.get('tables', {}).get(tab_id, {})
    binding = indexes.get('table_bindings', {}).get(tab_id, {})
    support_ids = tab.get('supporting_writing_point_ids', [])
    return {
        'table_id': tab_id,
        'table_number': base.get('table_number'),
        'page': int(tab.get('page') or base.get('page') or 0),
        'caption': tab.get('caption') or base.get('caption', ''),
        'caption_prefix': base.get('caption_prefix', ''),
        'relevance_score': tab.get('relevance_score', 0.0),
        'goal_hits': tab.get('goal_hits', []),
        'selection_reason': tab.get('selection_reason', ''),
        'supporting_writing_point_ids': support_ids,
        'supporting_claims': [selected_wp_map[wid]['claim'] for wid in support_ids if wid in selected_wp_map],
        'linked_chunk_ids': binding.get('linked_chunk_ids', []),
        'linked_parameter_ids': binding.get('linked_parameter_ids', []),
        'linked_result_ids': binding.get('linked_result_ids', []),
        'linked_reference_ids': binding.get('linked_reference_ids', []),
        'bbox': base.get('bbox'),
        'nearby_chunk_ids': base.get('nearby_chunk_ids', []),
        'evidence_note': f"表证据页码 {int(tab.get('page') or base.get('page') or 0)}；当前写作点支撑数 {len(support_ids)}。",
    }


def build_parameter_card(row: dict[str, Any], indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = indexes.get('parameters', {}).get(row.get('parameter_id', ''), {})
    text = row.get('text') or base.get('text', '')
    return {
        'parameter_id': row.get('parameter_id') or base.get('parameter_id'),
        'page': row.get('page') or base.get('page'),
        'chunk_id': row.get('chunk_id') or base.get('chunk_id'),
        'text': text,
        'text_preview': short_text(text, 180),
        'relevance_score': row.get('relevance_score', 0.0),
        'goal_hits': row.get('goal_hits', []),
        'supporting_writing_point_ids': row.get('supporting_writing_point_ids', []),
        'selection_reason': row.get('selection_reason', ''),
        'linked_figures': base.get('linked_figures', []),
        'linked_tables': base.get('linked_tables', []),
        'linked_references': base.get('linked_references', []),
    }


def build_result_card(row: dict[str, Any], indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = indexes.get('results', {}).get(row.get('result_id', ''), {})
    text = row.get('text') or base.get('text', '')
    return {
        'result_id': row.get('result_id') or base.get('result_id'),
        'page': row.get('page') or base.get('page'),
        'chunk_id': row.get('chunk_id') or base.get('chunk_id'),
        'text': text,
        'text_preview': short_text(text, 180),
        'relevance_score': row.get('relevance_score', 0.0),
        'goal_hits': row.get('goal_hits', []),
        'supporting_writing_point_ids': row.get('supporting_writing_point_ids', []),
        'selection_reason': row.get('selection_reason', ''),
        'linked_figures': base.get('linked_figures', []),
        'linked_tables': base.get('linked_tables', []),
        'linked_references': base.get('linked_references', []),
    }


def build_writing_point_card(wp: dict[str, Any], figure_cards: dict[str, dict[str, Any]], table_cards: dict[str, dict[str, Any]], ref_cards: dict[str, dict[str, Any]], parameter_cards: dict[str, dict[str, Any]], result_cards: dict[str, dict[str, Any]]) -> dict[str, Any]:
    linked_refs = [ref_cards[rid] for rid in wp.get('linked_references', []) if rid in ref_cards]
    linked_figs = [figure_cards[fid] for fid in wp.get('linked_figures', []) if fid in figure_cards]
    linked_tabs = [table_cards[tid] for tid in wp.get('linked_tables', []) if tid in table_cards]
    linked_params = [parameter_cards[pid] for pid in wp.get('linked_parameters', []) if pid in parameter_cards]
    linked_results = [result_cards[rid] for rid in wp.get('linked_results', []) if rid in result_cards]
    original_markers = [x['raw_marker'] for x in linked_refs if x.get('raw_marker')]
    evidence_bundle = {
        'figure_ids': [x['figure_id'] for x in linked_figs],
        'table_ids': [x['table_id'] for x in linked_tabs],
        'parameter_ids': [x['parameter_id'] for x in linked_params],
        'result_ids': [x['result_id'] for x in linked_results],
        'reference_ids': [x['ref_id'] for x in linked_refs],
    }
    return {
        'writing_point_id': wp['writing_point_id'],
        'claim': wp.get('claim') or wp.get('representative_claim', ''),
        'representative_claim': wp.get('representative_claim') or wp.get('claim', ''),
        'claim_preview': short_text(wp.get('claim') or wp.get('representative_claim', ''), 220),
        'point_type': wp.get('point_type', ''),
        'boundary_type': wp.get('boundary_type', ''),
        'boundary_note': wp.get('boundary_note', ''),
        'citation_role': wp.get('citation_role', ''),
        'original_reference_markers': original_markers,
        'pages': wp.get('pages', []),
        'page': wp.get('page'),
        'section_title': wp.get('section_title', ''),
        'source_chunk_ids': wp.get('source_chunk_ids', []),
        'source_text': wp.get('source_text', ''),
        'source_text_preview': short_text(wp.get('source_text', ''), 260),
        'causal_roles': wp.get('causal_roles', []),
        'goal_hits': wp.get('goal_hits', []),
        'goal_alignment_note': wp.get('goal_alignment_note', ''),
        'relevance_score': wp.get('relevance_score', 0.0),
        'evidence_strength': wp.get('evidence_strength', 0.0),
        'analysis_confidence': wp.get('analysis_confidence', 0.0),
        'selection_reason': wp.get('selection_reason', ''),
        'support_count': wp.get('support_count', 0),
        'linked_figure_ids': [x['figure_id'] for x in linked_figs],
        'linked_table_ids': [x['table_id'] for x in linked_tabs],
        'linked_parameter_ids': [x['parameter_id'] for x in linked_params],
        'linked_result_ids': [x['result_id'] for x in linked_results],
        'linked_reference_ids': [x['ref_id'] for x in linked_refs],
        'evidence_bundle_ids': wp.get('evidence_bundle_ids', []),
        'evidence_bundle': evidence_bundle,
        'evidence_summary': f"{len(linked_figs)} 图 / {len(linked_tabs)} 表 / {len(linked_params)} 参数 / {len(linked_results)} 结果 / {len(linked_refs)} 引用",
        'figure_card_refs': [
            {
                'figure_id': x['figure_id'],
                'page': x['page'],
                'caption': x['caption'],
                'relevance_score': x['relevance_score'],
            }
            for x in linked_figs
        ],
        'table_card_refs': [
            {
                'table_id': x['table_id'],
                'page': x['page'],
                'caption': x['caption'],
                'relevance_score': x['relevance_score'],
            }
            for x in linked_tabs
        ],
        'parameter_card_refs': [
            {
                'parameter_id': x['parameter_id'],
                'page': x['page'],
                'text_preview': x['text_preview'],
                'relevance_score': x['relevance_score'],
            }
            for x in linked_params
        ],
        'result_card_refs': [
            {
                'result_id': x['result_id'],
                'page': x['page'],
                'text_preview': x['text_preview'],
                'relevance_score': x['relevance_score'],
            }
            for x in linked_results
        ],
        'reference_card_refs': [
            {
                'ref_id': x['ref_id'],
                'raw_marker': x['raw_marker'],
                'entry_text': x['entry_text'],
                'relevance_score': x['relevance_score'],
            }
            for x in linked_refs
        ],
    }


def build_material_pack(analysis: dict[str, Any], bound: dict[str, Any] | None = None) -> dict[str, Any]:
    bound = bound or {}
    indexes = build_indexes(bound)

    selected_figures = analysis.get('selected_figures', []) or analysis.get('selected_images', []) or []
    selected_tables = analysis.get('selected_tables', []) or []
    selected_references = analysis.get('selected_references', []) or []
    selected_parameters = analysis.get('selected_parameters', []) or []
    selected_results = analysis.get('selected_results', []) or []
    selected_writing_points = analysis.get('selected_writing_points', []) or []

    figure_cards = {row['figure_id']: build_figure_card(row, indexes, {wp['writing_point_id']: wp for wp in selected_writing_points}) for row in selected_figures}
    table_cards = {row['table_id']: build_table_card(row, indexes, {wp['writing_point_id']: wp for wp in selected_writing_points}) for row in selected_tables}
    reference_cards = {row['ref_id']: enrich_reference(row, indexes) for row in selected_references}
    parameter_cards = {row['parameter_id']: build_parameter_card(row, indexes) for row in selected_parameters}
    result_cards = {row['result_id']: build_result_card(row, indexes) for row in selected_results}

    writing_point_cards = [
        build_writing_point_card(wp, figure_cards, table_cards, reference_cards, parameter_cards, result_cards)
        for wp in selected_writing_points
    ]

    evidence_bundles = []
    for card in writing_point_cards:
        evidence_bundles.append({
            'bundle_id': f"bundle::{card['writing_point_id']}",
            'writing_point_id': card['writing_point_id'],
            'claim': card['claim'],
            'boundary_type': card['boundary_type'],
            'boundary_note': card['boundary_note'],
            'original_reference_markers': card['original_reference_markers'],
            'figure_ids': card['linked_figure_ids'],
            'table_ids': card['linked_table_ids'],
            'parameter_ids': card['linked_parameter_ids'],
            'result_ids': card['linked_result_ids'],
            'reference_ids': card['linked_reference_ids'],
            'evidence_summary': card['evidence_summary'],
        })

    pack = {
        'goal': analysis.get('goal', ''),
        'goal_profile': analysis.get('goal_profile', {}),
        'status': 'ok',
        'pipeline_stage': 'S3_target_material_packaging',
        'pack_summary': {
            'selected_writing_points': len(writing_point_cards),
            'selected_figures': len(figure_cards),
            'selected_tables': len(table_cards),
            'selected_references': len(reference_cards),
            'selected_parameters': len(parameter_cards),
            'selected_results': len(result_cards),
            'evidence_bundles': len(evidence_bundles),
        },
        'quality_gates': {
            'has_writing_points': bool(writing_point_cards),
            'has_figure_level_evidence': bool(figure_cards),
            'has_original_reference_markers': any(x.get('raw_marker') for x in reference_cards.values()),
            'has_boundary_notes': all(bool(x.get('boundary_note')) for x in writing_point_cards) if writing_point_cards else False,
        },
        'writing_point_cards': writing_point_cards,
        'single_figure_cards': list(figure_cards.values()),
        'single_table_cards': list(table_cards.values()),
        'selected_parameter_cards': list(parameter_cards.values()),
        'selected_result_cards': list(result_cards.values()),
        'reference_directory_with_original_markers': list(reference_cards.values()),
        'evidence_bundles': evidence_bundles,
        'boundary_summary': analysis.get('boundary_summary', {}),
        'stats_analysis': analysis.get('stats_analysis', {}),
        'source_analysis_status': analysis.get('status', ''),
        'source_pdf': bound.get('source_pdf', ''),
    }
    return pack


def build_human_markdown(pack: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append('# 目标导向写作材料包（人看版）')
    lines.append('')
    lines.append(f"- 当前目标：{pack.get('goal', '')}")
    summary = pack.get('pack_summary', {})
    lines.append(
        f"- 材料规模：{summary.get('selected_writing_points', 0)} 个写作点，{summary.get('selected_figures', 0)} 张图，{summary.get('selected_tables', 0)} 个表，{summary.get('selected_references', 0)} 条引用，{summary.get('selected_parameters', 0)} 条参数，{summary.get('selected_results', 0)} 条结果。"
    )
    lines.append('')

    lines.append('## 写作点卡')
    lines.append('')
    for i, card in enumerate(pack.get('writing_point_cards', []), start=1):
        lines.append(f"### {i}. {card['writing_point_id']} | {card.get('point_type', '')} | 页 {', '.join(map(str, card.get('pages', []) or [card.get('page')]))}")
        lines.append(f"- 主张：{card.get('claim', '')}")
        lines.append(f"- 证据边界：{card.get('boundary_type', '')}｜{card.get('boundary_note', '')}")
        lines.append(f"- 相关度：{card.get('relevance_score', 0):.3f}｜证据强度：{card.get('evidence_strength', 0):.3f}")
        lines.append(f"- 因果角色：{', '.join(card.get('causal_roles', [])) or '无'}")
        lines.append(f"- 目标对齐：{card.get('goal_alignment_note', '')}")
        lines.append(f"- 证据摘要：{card.get('evidence_summary', '')}")
        if card.get('original_reference_markers'):
            lines.append(f"- 原始编号：{' '.join(card['original_reference_markers'])}")
        if card.get('figure_card_refs'):
            refs = '; '.join(f"{x['figure_id']}@p{x['page']}" for x in card['figure_card_refs'])
            lines.append(f"- 关联图：{refs}")
        if card.get('table_card_refs'):
            refs = '; '.join(f"{x['table_id']}@p{x['page']}" for x in card['table_card_refs'])
            lines.append(f"- 关联表：{refs}")
        if card.get('parameter_card_refs'):
            refs = '; '.join(f"{x['parameter_id']}@p{x['page']}" for x in card['parameter_card_refs'])
            lines.append(f"- 关联参数：{refs}")
        if card.get('result_card_refs'):
            refs = '; '.join(f"{x['result_id']}@p{x['page']}" for x in card['result_card_refs'])
            lines.append(f"- 关联结果：{refs}")
        lines.append('')

    lines.append('## 单图证据卡')
    lines.append('')
    for card in pack.get('single_figure_cards', []):
        lines.append(f"### {card['figure_id']} | 页 {card['page']}")
        lines.append(f"- 图题：{card.get('caption', '')}")
        lines.append(f"- 相关度：{card.get('relevance_score', 0):.3f}")
        lines.append(f"- 选择理由：{card.get('selection_reason', '')}")
        if card.get('supporting_writing_point_ids'):
            lines.append(f"- 支撑写作点：{', '.join(card['supporting_writing_point_ids'])}")
        if card.get('candidate_image_xrefs_on_page'):
            lines.append(f"- 页面图像候选 xref：{', '.join(map(str, card['candidate_image_xrefs_on_page']))}")
        if card.get('page_image_candidates'):
            preview = '; '.join(
                f"xref={x.get('xref')} path={Path(x.get('image_path', '')).name if x.get('image_path') else ''}" for x in card['page_image_candidates'][:4]
            )
            lines.append(f"- 候选图像对象：{preview}")
        lines.append('')

    if pack.get('single_table_cards'):
        lines.append('## 单表证据卡')
        lines.append('')
        for card in pack.get('single_table_cards', []):
            lines.append(f"### {card['table_id']} | 页 {card['page']}")
            lines.append(f"- 表题：{card.get('caption', '')}")
            lines.append(f"- 相关度：{card.get('relevance_score', 0):.3f}")
            lines.append(f"- 选择理由：{card.get('selection_reason', '')}")
            lines.append('')

    if pack.get('selected_parameter_cards'):
        lines.append('## 参数卡')
        lines.append('')
        for card in pack.get('selected_parameter_cards', []):
            lines.append(f"- {card['parameter_id']} | 页 {card.get('page')} | {card.get('text_preview', '')}")
        lines.append('')

    if pack.get('selected_result_cards'):
        lines.append('## 结果卡')
        lines.append('')
        for card in pack.get('selected_result_cards', []):
            lines.append(f"- {card['result_id']} | 页 {card.get('page')} | {card.get('text_preview', '')}")
        lines.append('')

    if pack.get('reference_directory_with_original_markers'):
        lines.append('## 原始参考文献目录')
        lines.append('')
        for ref in pack['reference_directory_with_original_markers']:
            lines.append(f"- {ref.get('raw_marker', '')} {ref.get('entry_text', '')}")
        lines.append('')

    return '\n'.join(lines).strip() + '\n'


def build_target_material_pack(analysis: dict[str, Any], bound: dict[str, Any] | None = None) -> dict[str, Any]:
    """把 07 分析结果和 02 绑定结果整理成真正可写作的目标导向材料包。"""
    return build_material_pack(analysis, bound)


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate target-oriented writing material pack from analysis and binding JSONs.')
    parser.add_argument('analysis_json', help='Path to 07 analysis JSON.')
    parser.add_argument('--bound-json', help='Path to 02 bound JSON for evidence enrichment.', default='')
    parser.add_argument('--out-json', help='Output JSON path.', required=True)
    parser.add_argument('--out-md', help='Output markdown path.', required=True)
    args = parser.parse_args()

    analysis = load_json(args.analysis_json)
    bound = load_json(args.bound_json) if args.bound_json else {}
    pack = build_material_pack(analysis, bound)
    dump_json(pack, args.out_json)
    Path(args.out_md).write_text(build_human_markdown(pack), encoding='utf-8')
    print(json.dumps({
        'status': 'ok',
        'out_json': str(Path(args.out_json).resolve()),
        'out_md': str(Path(args.out_md).resolve()),
        'counts': pack.get('pack_summary', {}),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()

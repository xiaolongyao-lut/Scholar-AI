from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any

PREVIEW_LIMIT_SHORT = 180
PREVIEW_LIMIT_MED = 220
PREVIEW_LIMIT_LONG = 260


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


def safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (ValueError, TypeError):
        return default


def stable_unique(items: list[str]) -> list[str]:
    """Return items with stable first-seen ordering and empty values removed."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def evidence_link_count(payload: dict[str, Any]) -> int:
    """Return the count of linked evidence ids on a card-like payload."""
    return sum(
        len(payload.get(key, []) or [])
        for key in (
            'linked_figure_ids',
            'linked_table_ids',
            'linked_parameter_ids',
            'linked_result_ids',
            'linked_reference_ids',
        )
    )


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
    for ref in bound.get('references') or []:
        ref_number = ref.get('ref_number')
        if ref_number is None:
            continue
        ref_id = ref.get('ref_id') or f"ref_{int(ref_number):03d}"
        mapping[ref_id] = ref.get('raw_text', '')
    return mapping


def page_image_lookup(bound: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for row in bound.get('page_images') or []:
        page = safe_int(row.get('page'))
        xref = safe_int(row.get('xref'))
        if xref > 0:
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
    page = safe_int(fig.get('page') or base.get('page'))
    page_image_candidates = []
    for xref in candidate_xrefs:
        xref_int = safe_int(xref)
        if xref_int <= 0:
            continue

        info = indexes.get('page_images', {}).get((page, xref_int))
        if info:
            page_image_candidates.append({
                'xref': xref_int,
                'image_path': info.get('image_path', ''),
                'width': info.get('width'),
                'height': info.get('height'),
                'bboxes': info.get('bboxes', []),
            })
        else:
            page_image_candidates.append({'xref': xref_int})
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
        'supporting_claims': [selected_wp_map[wid].get('claim', '') for wid in support_ids if wid in selected_wp_map],
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
    page = safe_int(tab.get('page') or base.get('page'))
    return {
        'table_id': tab_id,
        'table_number': base.get('table_number'),
        'page': page,
        'caption': tab.get('caption') or base.get('caption', ''),
        'caption_prefix': base.get('caption_prefix', ''),
        'relevance_score': tab.get('relevance_score', 0.0),
        'goal_hits': tab.get('goal_hits', []),
        'selection_reason': tab.get('selection_reason', ''),
        'supporting_writing_point_ids': support_ids,
        'supporting_claims': [selected_wp_map[wid].get('claim', '') for wid in support_ids if wid in selected_wp_map],
        'linked_chunk_ids': binding.get('linked_chunk_ids', []),
        'linked_parameter_ids': binding.get('linked_parameter_ids', []),
        'linked_result_ids': binding.get('linked_result_ids', []),
        'linked_reference_ids': binding.get('linked_reference_ids', []),
        'bbox': base.get('bbox'),
        'nearby_chunk_ids': base.get('nearby_chunk_ids', []),
        'evidence_note': f"表证据页码 {page}；当前写作点支撑数 {len(support_ids)}。",
    }


def build_parameter_card(row: dict[str, Any], indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = indexes.get('parameters', {}).get(row.get('parameter_id', ''), {})
    text = row.get('text') or base.get('text', '')
    return {
        'parameter_id': row.get('parameter_id') or base.get('parameter_id'),
        'page': row.get('page') or base.get('page'),
        'chunk_id': row.get('chunk_id') or base.get('chunk_id'),
        'text': text,
        'text_preview': short_text(text, PREVIEW_LIMIT_SHORT),
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
        'text_preview': short_text(text, PREVIEW_LIMIT_SHORT),
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

    linked_figure_ids = [x['figure_id'] for x in linked_figs]
    linked_table_ids = [x['table_id'] for x in linked_tabs]
    linked_parameter_ids = [x['parameter_id'] for x in linked_params]
    linked_result_ids = [x['result_id'] for x in linked_results]
    linked_reference_ids = [x['ref_id'] for x in linked_refs]

    evidence_bundle = {
        'figure_ids': linked_figure_ids,
        'table_ids': linked_table_ids,
        'parameter_ids': linked_parameter_ids,
        'result_ids': linked_result_ids,
        'reference_ids': linked_reference_ids,
    }
    return {
        'writing_point_id': wp['writing_point_id'],
        'claim': wp.get('claim') or wp.get('representative_claim', ''),
        'representative_claim': wp.get('representative_claim') or wp.get('claim', ''),
        'claim_preview': short_text(wp.get('claim') or wp.get('representative_claim', ''), PREVIEW_LIMIT_MED),
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
        'source_text_preview': short_text(wp.get('source_text', ''), PREVIEW_LIMIT_LONG),
        'causal_roles': wp.get('causal_roles', []),
        'goal_hits': wp.get('goal_hits', []),
        'goal_alignment_note': wp.get('goal_alignment_note', ''),
        'relevance_score': wp.get('relevance_score', 0.0),
        'evidence_strength': wp.get('evidence_strength', 0.0),
        'analysis_confidence': wp.get('analysis_confidence', 0.0),
        'selection_reason': wp.get('selection_reason', ''),
        'support_count': wp.get('support_count', 0),
        'linked_figure_ids': linked_figure_ids,
        'linked_table_ids': linked_table_ids,
        'linked_parameter_ids': linked_parameter_ids,
        'linked_result_ids': linked_result_ids,
        'linked_reference_ids': linked_reference_ids,
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


def build_semantic_themes(writing_point_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build deterministic semantic themes from writing-point cards.

    Why:
        Word 主文已经依赖 semantic_themes 作为主题化叙事入口，这里必须保证
        输出稳定、真实反映已有证据簇，并避免为了凑数而制造伪主题。

    Args:
        writing_point_cards: 已完成证据绑定的写作点卡列表。

    Returns:
        主题列表；真实只有 1-2 个主题时返回真实数量，仅在主题过多时做合并。
    """
    if not writing_point_cards:
        return []

    groups: dict[str, list[dict[str, Any]]] = {}
    for wp in writing_point_cards:
        section = wp.get('section_title') or wp.get('point_type') or '综合论述'
        causal = '_'.join(sorted(wp.get('causal_roles', []))) or '无因果'
        goal = '_'.join(sorted(wp.get('goal_hits', []))) or '通用目标'
        key = f"{section} | {goal} | {causal}"
        groups.setdefault(key, []).append(wp)

    group_list = list(groups.items())

    # 主题过多时合并最小簇，但不为凑最低主题数做强行拆分。
    while len(group_list) > 6:
        if len(group_list) < 2:
            break
        group_list.sort(key=lambda x: (len(x[1]), x[0]))
        g1 = group_list.pop(0)
        g2 = group_list.pop(0)
        t1 = (g1[0].split('|')[0] if '|' in g1[0] else g1[0]).strip()
        t2 = (g2[0].split('|')[0] if '|' in g2[0] else g2[0]).strip()
        group_list.append((f"{t1}与{t2}", g1[1] + g2[1]))

    def theme_weight(wps: list[dict[str, Any]]) -> tuple[float, int]:
        relevance = sum(float(wp.get('relevance_score', 0.0) or 0.0) for wp in wps)
        evidence = sum(float(wp.get('evidence_strength', 0.0) or 0.0) for wp in wps)
        earliest_page = min((safe_int(wp.get('page')) for wp in wps), default=0)
        return (relevance + evidence, earliest_page)

    group_list.sort(key=lambda item: (-theme_weight(item[1])[0], theme_weight(item[1])[1], item[0]))

    themes = []
    for idx, (title_raw, wps) in enumerate(group_list, 1):
        title = title_raw.split('|')[0].strip() if '|' in title_raw else title_raw.strip()
        wp_ids = [wp['writing_point_id'] for wp in wps]
        fig_ids = stable_unique([fid for wp in wps for fid in wp.get('linked_figure_ids', [])])
        tab_ids = stable_unique([tid for wp in wps for tid in wp.get('linked_table_ids', [])])
        ref_ids = stable_unique([rid for wp in wps for rid in wp.get('linked_reference_ids', [])])
        param_ids = stable_unique([pid for wp in wps for pid in wp.get('linked_parameter_ids', [])])
        result_ids = stable_unique([rid for wp in wps for rid in wp.get('linked_result_ids', [])])
        top_claims = stable_unique([
            short_text(wp.get('claim') or wp.get('representative_claim', ''), 80)
            for wp in wps
            if (wp.get('claim') or wp.get('representative_claim', ''))
        ])[:2]
        summary_tail = f"核心论点包括：{'；'.join(top_claims)}。" if top_claims else ""

        themes.append({
            'theme_id': f"theme_{idx:03d}",
            'theme_title': title,
            'summary': f"本主题围绕“{title}”展开论述，整合了 {len(wps)} 个关键写作点。{summary_tail}".strip(),
            'order_score': round(theme_weight(wps)[0], 3),
            'linked_writing_point_ids': wp_ids,
            'linked_figure_ids': fig_ids,
            'linked_table_ids': tab_ids,
            'linked_reference_ids': ref_ids,
            'linked_parameter_ids': param_ids,
            'linked_result_ids': result_ids,
        })
    return themes


def build_consistency_report(
    writing_point_cards: list[dict[str, Any]],
    semantic_themes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic claim-evidence consistency report for material packs.

    Why:
        主文生成已经基于 semantic_themes 和 writing_point_cards 出稿；在进入
        Word 前，需要把“主张是否有证据”“主题是否真的挂到写作点”显式结构化。

    Args:
        writing_point_cards: 已完成证据绑定的写作点卡。
        semantic_themes: 已聚类完成的主题卡。

    Returns:
        一个包含 summary、issues、writing_point_checks、theme_checks 的校验报告。
    """
    issues: list[dict[str, Any]] = []
    writing_point_checks: list[dict[str, Any]] = []
    theme_checks: list[dict[str, Any]] = []
    writing_point_lookup = {
        str(card.get('writing_point_id')): card
        for card in writing_point_cards
        if card.get('writing_point_id')
    }

    for card in writing_point_cards:
        writing_point_id = str(card.get('writing_point_id', ''))
        claim = str(card.get('claim') or card.get('representative_claim') or '').strip()
        source_chunk_ids = stable_unique([str(item) for item in card.get('source_chunk_ids', []) or [] if item])
        original_markers = stable_unique([str(item) for item in card.get('original_reference_markers', []) or [] if item])
        linked_evidence_count = evidence_link_count(card)
        has_supporting_evidence = bool(linked_evidence_count or source_chunk_ids or original_markers)
        check = {
            'writing_point_id': writing_point_id,
            'claim_present': bool(claim),
            'linked_evidence_count': linked_evidence_count,
            'source_chunk_count': len(source_chunk_ids),
            'reference_marker_count': len(original_markers),
            'has_supporting_evidence': has_supporting_evidence,
            'severity': 'ok',
            'issues': [],
        }
        if not claim:
            issue = {
                'severity': 'error',
                'scope': 'writing_point',
                'id': writing_point_id,
                'message': '写作点缺少 claim/representative_claim，无法建立可审阅主张。',
            }
            check['severity'] = 'error'
            check['issues'].append(issue['message'])
            issues.append(issue)
        if not has_supporting_evidence:
            issue = {
                'severity': 'error',
                'scope': 'writing_point',
                'id': writing_point_id,
                'message': '写作点没有任何图、表、参数、结果、引用或 source_chunk 支撑。',
            }
            check['severity'] = 'error'
            check['issues'].append(issue['message'])
            issues.append(issue)
        elif not original_markers and linked_evidence_count == 0:
            issue = {
                'severity': 'warning',
                'scope': 'writing_point',
                'id': writing_point_id,
                'message': '写作点仅保留 source_chunk 支撑，缺少显式图表/引用链路。',
            }
            if check['severity'] == 'ok':
                check['severity'] = 'warning'
            check['issues'].append(issue['message'])
            issues.append(issue)
        writing_point_checks.append(check)

    for theme in semantic_themes:
        theme_id = str(theme.get('theme_id', ''))
        linked_writing_point_ids = stable_unique([str(item) for item in theme.get('linked_writing_point_ids', []) or [] if item])
        missing_writing_points = [item for item in linked_writing_point_ids if item not in writing_point_lookup]
        covered_cards = [writing_point_lookup[item] for item in linked_writing_point_ids if item in writing_point_lookup]
        aggregated_evidence_count = sum(evidence_link_count(card) for card in covered_cards)
        has_theme_evidence = bool(aggregated_evidence_count)
        check = {
            'theme_id': theme_id,
            'theme_title': str(theme.get('theme_title', '')),
            'linked_writing_point_count': len(linked_writing_point_ids),
            'missing_writing_point_ids': missing_writing_points,
            'aggregated_evidence_count': aggregated_evidence_count,
            'has_supporting_evidence': has_theme_evidence,
            'severity': 'ok',
            'issues': [],
        }
        if not linked_writing_point_ids:
            issue = {
                'severity': 'error',
                'scope': 'theme',
                'id': theme_id,
                'message': '主题未关联任何写作点，不能直接用于主文生成。',
            }
            check['severity'] = 'error'
            check['issues'].append(issue['message'])
            issues.append(issue)
        if missing_writing_points:
            issue = {
                'severity': 'error',
                'scope': 'theme',
                'id': theme_id,
                'message': f"主题引用了不存在的写作点: {', '.join(missing_writing_points)}。",
            }
            check['severity'] = 'error'
            check['issues'].append(issue['message'])
            issues.append(issue)
        if linked_writing_point_ids and not has_theme_evidence:
            issue = {
                'severity': 'warning',
                'scope': 'theme',
                'id': theme_id,
                'message': '主题下写作点缺少显式图表/参数/结果/引用链接，主文支撑较弱。',
            }
            if check['severity'] == 'ok':
                check['severity'] = 'warning'
            check['issues'].append(issue['message'])
            issues.append(issue)
        theme_checks.append(check)

    error_count = sum(1 for issue in issues if issue['severity'] == 'error')
    warning_count = sum(1 for issue in issues if issue['severity'] == 'warning')
    return {
        'summary': {
            'writing_point_count': len(writing_point_cards),
            'theme_count': len(semantic_themes),
            'issue_count': len(issues),
            'error_count': error_count,
            'warning_count': warning_count,
            'overall_pass': error_count == 0,
        },
        'issues': issues,
        'writing_point_checks': writing_point_checks,
        'theme_checks': theme_checks,
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

    selected_wp_map = {wp['writing_point_id']: wp for wp in selected_writing_points}

    figure_cards = {row['figure_id']: build_figure_card(row, indexes, selected_wp_map) for row in selected_figures}
    table_cards = {row['table_id']: build_table_card(row, indexes, selected_wp_map) for row in selected_tables}
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

    semantic_themes = build_semantic_themes(writing_point_cards)
    consistency_report = build_consistency_report(writing_point_cards, semantic_themes)
    consistency_summary = consistency_report.get('summary', {})

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
            'semantic_themes': len(semantic_themes),
            'consistency_issues': consistency_summary.get('issue_count', 0),
        },
        'quality_gates': {
            'has_writing_points': bool(writing_point_cards),
            'has_figure_level_evidence': bool(figure_cards),
            'has_original_reference_markers': any(x.get('raw_marker') for x in reference_cards.values()),
            'has_boundary_notes': all(bool(x.get('boundary_note')) for x in writing_point_cards) if writing_point_cards else False,
            'has_semantic_themes': bool(semantic_themes),
            'has_consistency_report': True,
            'writing_points_have_supporting_evidence': all(
                bool(item.get('has_supporting_evidence')) and item.get('claim_present', True)
                for item in consistency_report.get('writing_point_checks', [])
            ) if writing_point_cards else False,
            'themes_have_linked_writing_points': all(
                item.get('linked_writing_point_count', 0) > 0 and not item.get('missing_writing_point_ids')
                for item in consistency_report.get('theme_checks', [])
            ) if semantic_themes else False,
            'consistency_pass': bool(consistency_summary.get('overall_pass', False)),
        },
        'consistency_report': consistency_report,
        'semantic_themes': semantic_themes,
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
        f"- 材料规模：{summary.get('semantic_themes', 0)} 个业务主题，{summary.get('selected_writing_points', 0)} 个写作点，{summary.get('selected_figures', 0)} 张图，{summary.get('selected_tables', 0)} 个表，{summary.get('selected_references', 0)} 条引用，{summary.get('selected_parameters', 0)} 条参数，{summary.get('selected_results', 0)} 条结果。"
    )
    lines.append('')

    if pack.get('semantic_themes'):
        lines.append('## 语义主题')
        lines.append('')
        for theme in pack['semantic_themes']:
            lines.append(f"### {theme['theme_id']} | {theme['theme_title']}")
            lines.append(f"- 主题摘要：{theme.get('summary', '')}")
            lines.append(f"- 包含写作点：{', '.join(theme.get('linked_writing_point_ids', []))}")
            lines.append('')

    consistency_report = pack.get('consistency_report', {})
    consistency_summary = consistency_report.get('summary', {})
    if consistency_report:
        lines.append('## 一致性校验')
        lines.append('')
        lines.append(
            f"- 校验结论：{'PASS' if consistency_summary.get('overall_pass') else 'FAIL'}"
            f"｜错误 {consistency_summary.get('error_count', 0)}｜警告 {consistency_summary.get('warning_count', 0)}"
        )
        for issue in consistency_report.get('issues', [])[:10]:
            lines.append(
                f"- [{issue.get('severity', 'info').upper()}] {issue.get('scope', '')}:{issue.get('id', '')} - {issue.get('message', '')}"
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
                f"xref={x.get('xref')} path={Path(x['image_path']).name if x.get('image_path') else ''}" for x in card['page_image_candidates'][:4]
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

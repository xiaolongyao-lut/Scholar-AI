from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_text(path: str | Path) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def dump_json(obj: Any, path: str | Path) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def dump_text(text: str, path: str | Path) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def short_text(text: str, limit: int = 220) -> str:
    text = ' '.join((text or '').split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + '…'


def existing_path(value: str | None) -> str:
    if not value:
        return ''
    p = Path(value)
    return str(p) if p.exists() else str(value)


def build_stage_manifest(extract: dict[str, Any], bound: dict[str, Any], analysis: dict[str, Any], material_pack: dict[str, Any], figure_pack: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        'stage_01_extract': {
            'script_path': existing_path(args.script01),
            'input_path': existing_path(args.extract),
            'status': extract.get('status', ''),
            'key_counts': {
                'sections': len(extract.get('sections', []) or []),
                'chunks': len(extract.get('chunks', []) or []),
                'figures': len(extract.get('figures', []) or []),
                'tables': len(extract.get('tables', []) or []),
                'references': len(extract.get('references', []) or []),
                'parameter_candidates': len(extract.get('parameter_candidates', []) or []),
                'result_candidates': len(extract.get('result_candidates', []) or []),
                'page_images': len(extract.get('page_images', []) or []),
            },
        },
        'stage_02_binding': {
            'script_path': existing_path(args.script02),
            'input_path': existing_path(args.bound),
            'status': bound.get('status', ''),
            'key_counts': {
                'relation_edges': len(bound.get('relation_edges', []) or []),
                'figure_bindings': len(bound.get('figure_bindings', []) or []),
                'table_bindings': len(bound.get('table_bindings', []) or []),
                'parameter_cards': len(bound.get('parameter_cards', []) or []),
                'result_cards': len(bound.get('result_cards', []) or []),
            },
        },
        'stage_07_analysis': {
            'script_path': existing_path(args.script07),
            'input_path': existing_path(args.analysis),
            'status': analysis.get('status', ''),
            'goal': analysis.get('goal', ''),
            'key_counts': {
                'raw_writing_points': len(analysis.get('raw_writing_points', []) or []),
                'writing_points': len(analysis.get('writing_points', []) or []),
                'selected_writing_points': len(analysis.get('selected_writing_points', []) or []),
                'selected_figures': len(analysis.get('selected_figures', []) or []),
                'selected_tables': len(analysis.get('selected_tables', []) or []),
                'selected_references': len(analysis.get('selected_references', []) or []),
                'selected_parameters': len(analysis.get('selected_parameters', []) or []),
                'selected_results': len(analysis.get('selected_results', []) or []),
            },
        },
        'stage_03_material_pack': {
            'script_path': existing_path(args.script03),
            'input_path': existing_path(args.material_pack),
            'status': material_pack.get('status', ''),
            'pack_summary': material_pack.get('pack_summary', {}),
        },
        'stage_04_single_figures': {
            'script_path': existing_path(args.script04),
            'input_path': existing_path(args.figure_pack),
            'status': figure_pack.get('status', ''),
            'refinement_stats': figure_pack.get('refinement_stats', {}),
        },
    }


def build_quality_gates(material_pack: dict[str, Any], figure_pack: dict[str, Any]) -> dict[str, Any]:
    wp_cards = material_pack.get('writing_point_cards', []) or []
    fig_cards = material_pack.get('single_figure_cards', []) or []
    refined = figure_pack.get('single_figure_cards_refined', []) or []
    bundle_count = len(material_pack.get('evidence_bundles', []) or [])
    raw_marker_ok = all(bool(card.get('original_reference_markers') is not None) for card in wp_cards)
    boundary_ok = all(bool(card.get('boundary_type')) and bool(card.get('boundary_note')) for card in wp_cards)
    fig_count_match = len(fig_cards) == len(refined)
    primary_ok = all(bool((card.get('primary_single_figure') or {}).get('raw_embedded_image', {}).get('image_path')) for card in refined)
    return {
        'has_writing_points': len(wp_cards) > 0,
        'has_single_figure_cards': len(fig_cards) > 0,
        'has_evidence_bundles': bundle_count > 0,
        'writing_points_have_boundary_notes': boundary_ok,
        'writing_points_keep_original_markers_field': raw_marker_ok,
        'refined_figure_count_matches_material_pack': fig_count_match,
        'refined_figures_have_primary_raw_images': primary_ok,
        'overall_pass': all([
            len(wp_cards) > 0,
            len(fig_cards) > 0,
            bundle_count > 0,
            boundary_ok,
            fig_count_match,
            primary_ok,
        ]),
    }


def build_reference_directory(material_pack: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ref in material_pack.get('reference_directory_with_original_markers', []) or []:
        out.append({
            'ref_id': ref.get('ref_id', ''),
            'raw_marker': ref.get('raw_marker', ''),
            'entry_text': ref.get('entry_text', ''),
            'relevance_score': ref.get('relevance_score', 0.0),
            'selection_reason': ref.get('selection_reason', ''),
            'supporting_writing_point_ids': ref.get('supporting_writing_point_ids', []),
        })
    return out


def build_figure_lookup(figure_pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for card in figure_pack.get('single_figure_cards_refined', []) or []:
        fig_id = card.get('figure_id')
        if fig_id:
            lookup[fig_id] = card
    return lookup


def build_traceability(material_pack: dict[str, Any], figure_pack: dict[str, Any]) -> list[dict[str, Any]]:
    figure_lookup = build_figure_lookup(figure_pack)
    out: list[dict[str, Any]] = []
    for card in material_pack.get('writing_point_cards', []) or []:
        figure_evidence = []
        for fig_id in card.get('linked_figure_ids', []) or []:
            fig = figure_lookup.get(fig_id, {})
            primary = fig.get('primary_single_figure') or {}
            figure_evidence.append({
                'figure_id': fig_id,
                'figure_number': fig.get('figure_number'),
                'page': fig.get('page'),
                'caption': fig.get('caption', ''),
                'raw_image_path': ((primary.get('raw_embedded_image') or {}).get('image_path', '')),
                'page_crop_path': ((primary.get('page_crop_image') or {}).get('image_path', '')),
            })
        out.append({
            'writing_point_id': card.get('writing_point_id', ''),
            'claim': card.get('claim', ''),
            'boundary_type': card.get('boundary_type', ''),
            'original_reference_markers': card.get('original_reference_markers', []),
            'source_chunk_ids': card.get('source_chunk_ids', []),
            'linked_parameter_ids': card.get('linked_parameter_ids', []),
            'linked_result_ids': card.get('linked_result_ids', []),
            'linked_table_ids': card.get('linked_table_ids', []),
            'figure_evidence': figure_evidence,
            'selection_reason': card.get('selection_reason', ''),
            'evidence_summary': card.get('evidence_summary', ''),
        })
    return out


def build_current_task_subset(material_pack: dict[str, Any], figure_pack: dict[str, Any]) -> dict[str, Any]:
    figure_lookup = build_figure_lookup(figure_pack)
    selected_figures = []
    for card in material_pack.get('single_figure_cards', []) or []:
        fig = figure_lookup.get(card.get('figure_id', ''), {})
        primary = fig.get('primary_single_figure') or {}
        selected_figures.append({
            'figure_id': card.get('figure_id', ''),
            'figure_number': card.get('figure_number'),
            'page': card.get('page'),
            'caption': card.get('caption', ''),
            'supporting_writing_point_ids': card.get('supporting_writing_point_ids', []),
            'raw_image_path': ((primary.get('raw_embedded_image') or {}).get('image_path', '')),
            'page_crop_path': ((primary.get('page_crop_image') or {}).get('image_path', '')),
            'selection_reason': card.get('selection_reason', ''),
        })
    return {
        'goal': material_pack.get('goal', ''),
        'selected_writing_points': material_pack.get('writing_point_cards', []),
        'selected_figures': selected_figures,
        'selected_tables': material_pack.get('single_table_cards', []),
        'selected_parameters': material_pack.get('selected_parameter_cards', []),
        'selected_results': material_pack.get('selected_result_cards', []),
        'selected_references': build_reference_directory(material_pack),
    }


def build_project_view(extract: dict[str, Any], bound: dict[str, Any], analysis: dict[str, Any], material_pack: dict[str, Any], figure_pack: dict[str, Any], governance: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    project_view_cfg = governance['project_view']
    prompt_json = governance['prompt_json']
    return {
        'file_role': 'run_master_project_view',
        'version': '1.0.0',
        'source_pdf': extract.get('source_pdf') or material_pack.get('source_pdf', ''),
        'source_pdf_name': Path(extract.get('source_pdf') or material_pack.get('source_pdf', '')).name,
        'goal': analysis.get('goal') or material_pack.get('goal', ''),
        'project_identity': project_view_cfg.get('positioning', {}).get('system_identity', project_view_cfg.get('core_identity', '')),
        'runtime_split': project_view_cfg.get('global_runtime_split', project_view_cfg.get('runtime_split', {})),
        'hard_rules': project_view_cfg.get('hard_rules', prompt_json.get('hard_rules', {})),
        'pipeline': project_view_cfg.get('default_pipeline', prompt_json.get('pipeline', [])),
        'governance_sources': {
            'project_view_path': existing_path(args.project_view),
            'prompt_md_path': existing_path(args.prompt_md),
            'prompt_json_path': existing_path(args.prompt_json),
            'changelog_path': existing_path(args.changelog),
            'route_summary_path': existing_path(args.route_summary),
            'user_profile_path': existing_path(args.user_profile),
        },
        'stage_manifest': build_stage_manifest(extract, bound, analysis, material_pack, figure_pack, args),
        'quality_gates': build_quality_gates(material_pack, figure_pack),
        'current_task_usable_subset': build_current_task_subset(material_pack, figure_pack),
        'traceability_index': build_traceability(material_pack, figure_pack),
        'evidence_bundles': material_pack.get('evidence_bundles', []),
        'boundary_summary': material_pack.get('boundary_summary', analysis.get('boundary_summary', {})),
        'stats': {
            'extract_stats': extract.get('stats', {}),
            'binding_stats': bound.get('stats_binding', {}),
            'analysis_stats': analysis.get('stats_analysis', {}),
            'material_pack_summary': material_pack.get('pack_summary', {}),
            'figure_refinement_stats': figure_pack.get('refinement_stats', {}),
        },
    }


def build_human_view(project_view: dict[str, Any], material_pack: dict[str, Any], figure_pack: dict[str, Any]) -> str:
    figure_lookup = build_figure_lookup(figure_pack)
    lines: list[str] = []
    lines.append(f"# 总文件（人看版）\n")
    lines.append(f"- 来源文献：{project_view.get('source_pdf_name', '')}")
    lines.append(f"- 当前目标：{project_view.get('goal', '')}")
    lines.append(f"- 角色定位：{project_view.get('project_identity', '')}\n")

    stage_manifest = project_view.get('stage_manifest', {})
    lines.append("## 阶段状态")
    for key, row in stage_manifest.items():
        title = key.replace('stage_', 'S')
        status = row.get('status', '')
        counts = row.get('key_counts') or row.get('pack_summary') or row.get('refinement_stats') or {}
        counts_txt = '；'.join([f"{k}={v}" for k, v in counts.items()])
        lines.append(f"- {title}：{status}；{counts_txt}")
    lines.append("")

    gates = project_view.get('quality_gates', {})
    lines.append("## 质量门")
    for k, v in gates.items():
        lines.append(f"- {k}：{'通过' if v else '未通过'}")
    lines.append("")

    lines.append("## 当前最可用写作点")
    for idx, card in enumerate((material_pack.get('writing_point_cards', []) or [])[:12], start=1):
        lines.append(f"### {idx}. {card.get('claim', '')}")
        lines.append(f"- 边界：{card.get('boundary_type', '')}｜{card.get('boundary_note', '')}")
        lines.append(f"- 原始编号：{' '.join(card.get('original_reference_markers', []) or []) or '无'}")
        lines.append(f"- 关联图：{', '.join(card.get('linked_figure_ids', []) or []) or '无'}；关联表：{', '.join(card.get('linked_table_ids', []) or []) or '无'}")
        lines.append(f"- 关联参数：{', '.join(card.get('linked_parameter_ids', []) or []) or '无'}；关联结果：{', '.join(card.get('linked_result_ids', []) or []) or '无'}")
        lines.append(f"- 证据摘要：{short_text(card.get('evidence_summary', '') or card.get('source_text_preview', ''), 260)}")
        lines.append("")

    lines.append("## 图级证据总览")
    for card in (material_pack.get('single_figure_cards', []) or [])[:12]:
        fig = figure_lookup.get(card.get('figure_id', ''), {})
        primary = fig.get('primary_single_figure') or {}
        raw_path = ((primary.get('raw_embedded_image') or {}).get('image_path', ''))
        crop_path = ((primary.get('page_crop_image') or {}).get('image_path', ''))
        lines.append(f"- {card.get('figure_id', '')} / Fig.{card.get('figure_number', '')} / p.{card.get('page', '')}")
        lines.append(f"  - 图题：{short_text(card.get('caption', ''), 180)}")
        lines.append(f"  - 主图：{raw_path or '无'}")
        lines.append(f"  - 辅助定位图：{crop_path or '无'}")
        lines.append(f"  - 支撑写作点：{', '.join(card.get('supporting_writing_point_ids', []) or []) or '无'}")
    lines.append("")

    lines.append("## 参数 / 结果 / 引用")
    lines.append(f"- 参数条目：{len(material_pack.get('selected_parameter_cards', []) or [])}")
    lines.append(f"- 结果条目：{len(material_pack.get('selected_result_cards', []) or [])}")
    lines.append(f"- 引用条目：{len(material_pack.get('reference_directory_with_original_markers', []) or [])}")
    lines.append("")

    lines.append("## 最后判断")
    if project_view.get('quality_gates', {}).get('overall_pass'):
        lines.append("当前主链已经贯通，可直接进入 06 打包交付。")
    else:
        lines.append("当前主链尚未完全通过质量门，建议先修补后再打包。")
    lines.append("")

    return '\n'.join(lines)


def build_master_files(project_view: dict[str, Any], human_view: str, prompt_file: dict[str, Any], changelog: str) -> dict[str, Any]:
    """生成总文件项目看版、人看版、总提示词和更新记录。"""
    return {
        'project_view': project_view,
        'human_view': human_view,
        'prompt_file': prompt_file,
        'changelog': changelog,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Build run-level master project/human view files from stages 01/02/07/03/04.')
    ap.add_argument('--extract', required=True)
    ap.add_argument('--bound', required=True)
    ap.add_argument('--analysis', required=True)
    ap.add_argument('--material-pack', required=True)
    ap.add_argument('--figure-pack', required=True)
    ap.add_argument('--project-view', required=True)
    ap.add_argument('--prompt-md', required=True)
    ap.add_argument('--prompt-json', required=True)
    ap.add_argument('--changelog', required=True)
    ap.add_argument('--route-summary', required=True)
    ap.add_argument('--user-profile', required=True)
    ap.add_argument('--script01', default='')
    ap.add_argument('--script02', default='')
    ap.add_argument('--script03', default='')
    ap.add_argument('--script04', default='')
    ap.add_argument('--script07', default='')
    ap.add_argument('--out-prefix', required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    extract = load_json(args.extract)
    bound = load_json(args.bound)
    analysis = load_json(args.analysis)
    material_pack = load_json(args.material_pack)
    figure_pack = load_json(args.figure_pack)

    governance = {
        'project_view': load_json(args.project_view),
        'prompt_md': load_text(args.prompt_md),
        'prompt_json': load_json(args.prompt_json),
        'changelog': load_text(args.changelog),
        'route_summary': load_text(args.route_summary),
        'user_profile': load_text(args.user_profile),
    }

    project_view = build_project_view(extract, bound, analysis, material_pack, figure_pack, governance, args)
    human_view = build_human_view(project_view, material_pack, figure_pack)
    prompt_file = {
        'prompt_md': governance['prompt_md'],
        'prompt_json': governance['prompt_json'],
        'route_summary': governance['route_summary'],
        'user_profile': governance['user_profile'],
    }
    master = build_master_files(project_view, human_view, prompt_file, governance['changelog'])

    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    project_out = out_prefix.with_name(out_prefix.name + '_项目看版.json')
    human_out = out_prefix.with_name(out_prefix.name + '_人看版.md')
    master_out = out_prefix.with_name(out_prefix.name + '_主文件索引.json')

    dump_json(project_view, project_out)
    dump_text(human_view, human_out)
    dump_json(master, master_out)

    print(json.dumps({
        'status': 'ok',
        'project_view_path': str(project_out),
        'human_view_path': str(human_out),
        'master_manifest_path': str(master_out),
        'overall_pass': project_view.get('quality_gates', {}).get('overall_pass', False),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

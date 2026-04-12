from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from layers.e_layer_multimodal import (
    bbox_score,
    clamp,
    collect_page_image_occurrences,
    extract_raw_image,
    rect_to_list,
    render_page_crop,
)


MARGIN_PX = 18


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def dump_json(obj: Any, path: str | Path) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def refine_single_figures(material_pack: dict[str, Any], out_dir: Path, dpi: int = 220) -> dict[str, Any]:
    source_pdf = material_pack.get('source_pdf')
    if not source_pdf:
        raise ValueError('material pack missing source_pdf')
    pdf_path = Path(source_pdf)
    if not pdf_path.exists():
        raise FileNotFoundError(f'source_pdf not found: {pdf_path}')

    doc = fitz.open(str(pdf_path))
    figure_cards = material_pack.get('single_figure_cards', []) or []

    page_occ_cache: dict[int, dict[int, list[fitz.Rect]]] = {}
    refined_cards: list[dict[str, Any]] = []
    stats = {
        'total_figure_cards': len(figure_cards),
        'with_primary_image': 0,
        'with_raw_embedded_image': 0,
        'with_page_crop': 0,
        'fallback_without_candidates': 0,
    }

    base_name = pdf_path.stem
    figure_root = out_dir / f'{base_name}_single_figures'
    figure_root.mkdir(parents=True, exist_ok=True)

    for fig in figure_cards:
        fig_id = fig.get('figure_id')
        page_num = int(fig.get('page') or 0)
        if not fig_id or page_num < 1 or page_num > len(doc):
            continue
        page = doc[page_num - 1]
        page_rect = page.rect
        caption_rect = fitz.Rect(fig.get('bbox') or [0, 0, page_rect.width, 0])
        if page_num not in page_occ_cache:
            page_occ_cache[page_num] = collect_page_image_occurrences(page)
        occ_map = page_occ_cache[page_num]

        candidate_xrefs = [int(x) for x in fig.get('candidate_image_xrefs_on_page', []) if isinstance(x, (int, float)) or str(x).isdigit()]
        if not candidate_xrefs:
            candidate_xrefs = sorted(occ_map.keys())
            stats['fallback_without_candidates'] += 1

        candidates: list[dict[str, Any]] = []
        for xref in candidate_xrefs:
            for idx, occ in enumerate(occ_map.get(int(xref), []), start=1):
                score = bbox_score(occ, caption_rect, page_rect)
                candidates.append({
                    'xref': int(xref),
                    'occurrence_index': idx,
                    'bbox': rect_to_list(occ),
                    'score': score,
                    'area': round(occ.width * occ.height, 2),
                    'position': 'above_caption' if occ.y1 <= caption_rect.y0 else ('below_caption' if occ.y0 >= caption_rect.y1 else 'overlap_caption'),
                })

        primary = None
        if candidates:
            candidates.sort(key=lambda row: (row['score'], row['area']), reverse=True)
            primary = candidates[0]

        refined = dict(fig)
        refined['image_refinement_candidates'] = candidates
        refined['image_refinement_status'] = 'no_candidate_found'
        refined['primary_single_figure'] = None
        refined['all_output_paths'] = []

        fig_dir = figure_root / f"{int(fig.get('figure_number') or 0):02d}_{fig_id}"
        fig_dir.mkdir(parents=True, exist_ok=True)

        if primary:
            primary_rect = fitz.Rect(primary['bbox'])
            padded = fitz.Rect(
                clamp(primary_rect.x0 - MARGIN_PX, 0, page_rect.width),
                clamp(primary_rect.y0 - MARGIN_PX, 0, page_rect.height),
                clamp(primary_rect.x1 + MARGIN_PX, 0, page_rect.width),
                clamp(primary_rect.y1 + MARGIN_PX, 0, page_rect.height),
            )
            primary_info = {
                'page': page_num,
                'xref': primary['xref'],
                'occurrence_index': primary['occurrence_index'],
                'bbox': primary['bbox'],
                'padded_bbox': rect_to_list(padded),
                'score': primary['score'],
            }

            # raw embedded image
            try:
                raw_meta = extract_raw_image(doc, primary['xref'], fig_dir / f'{fig_id}_raw')
                primary_info['raw_embedded_image'] = raw_meta
                refined['all_output_paths'].append(raw_meta['image_path'])
                stats['with_raw_embedded_image'] += 1
            except Exception as e:
                primary_info['raw_embedded_image_error'] = str(e)

            # page crop using bbox
            try:
                crop_meta = render_page_crop(page, padded, dpi=dpi, out_path=fig_dir / f'{fig_id}_page_crop.png')
                primary_info['page_crop_image'] = crop_meta
                refined['all_output_paths'].append(crop_meta['image_path'])
                stats['with_page_crop'] += 1
            except Exception as e:
                primary_info['page_crop_image_error'] = str(e)

            refined['primary_single_figure'] = primary_info
            refined['image_refinement_status'] = 'ok'
            stats['with_primary_image'] += 1
        
        refined_cards.append(refined)

    result = {
        'status': 'ok',
        'pipeline_stage': 'S4_image_refinement',
        'source_material_pack': material_pack.get('source_analysis_status', ''),
        'source_pdf': str(pdf_path),
        'single_figure_cards_refined': refined_cards,
        'refinement_stats': stats,
    }
    return result


def build_human_md(refined: dict[str, Any], out_path: Path) -> None:
    rows = []
    rows.append('# 单图证据提取结果')
    rows.append('')
    rows.append(f"- 来源 PDF：`{refined.get('source_pdf','')}`")
    rows.append(f"- 图卡总数：{refined.get('refinement_stats',{}).get('total_figure_cards',0)}")
    rows.append(f"- 成功生成主单图：{refined.get('refinement_stats',{}).get('with_primary_image',0)}")
    rows.append(f"- 成功导出原始嵌入图：{refined.get('refinement_stats',{}).get('with_raw_embedded_image',0)}")
    rows.append(f"- 成功生成页面裁切图：{refined.get('refinement_stats',{}).get('with_page_crop',0)}")
    rows.append('')
    for fig in refined.get('single_figure_cards_refined', []):
        rows.append(f"## Figure {fig.get('figure_number')} ({fig.get('figure_id')})")
        rows.append('')
        rows.append(f"- 页码：{fig.get('page')}")
        rows.append(f"- 图题：{fig.get('caption','')}")
        rows.append(f"- 状态：{fig.get('image_refinement_status')}")
        primary = fig.get('primary_single_figure') or {}
        if primary:
            rows.append(f"- 主候选 xref：{primary.get('xref')} | 分数：{primary.get('score')}")
            if primary.get('raw_embedded_image', {}).get('image_path'):
                rows.append(f"- 原始嵌入图：`{primary['raw_embedded_image']['image_path']}`")
            if primary.get('page_crop_image', {}).get('image_path'):
                rows.append(f"- 页面裁切图：`{primary['page_crop_image']['image_path']}`")
        rows.append('')
    out_path.write_text('\n'.join(rows), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='从目标导向材料包中提取单图证据。')
    parser.add_argument('--material-pack', required=True, help='03 输出的材料包 JSON 路径')
    parser.add_argument('--output-json', required=True, help='04 输出 JSON 路径')
    parser.add_argument('--output-md', required=True, help='04 输出人看版 MD 路径')
    parser.add_argument('--out-dir', required=True, help='单图证据文件输出目录')
    parser.add_argument('--dpi', type=int, default=220, help='页面裁切图 DPI，默认 220')
    args = parser.parse_args()

    material_pack = load_json(args.material_pack)
    out_dir = Path(args.out_dir)
    refined = refine_single_figures(material_pack, out_dir=out_dir, dpi=args.dpi)
    dump_json(refined, args.output_json)
    build_human_md(refined, Path(args.output_md))
    stats = refined.get('refinement_stats', {})
    print(json.dumps({
        'status': refined.get('status'),
        'total_figure_cards': stats.get('total_figure_cards', 0),
        'with_primary_image': stats.get('with_primary_image', 0),
        'with_raw_embedded_image': stats.get('with_raw_embedded_image', 0),
        'with_page_crop': stats.get('with_page_crop', 0),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()

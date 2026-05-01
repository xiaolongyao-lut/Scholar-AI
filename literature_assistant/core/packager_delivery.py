from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def dump_json(obj: Any, path: str | Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def safe_name(name: str) -> str:
    name = re.sub(r'\s+', '_', name.strip())
    name = re.sub(r'[^\w\-\u4e00-\u9fff]+', '_', name)
    return name.strip('_') or 'unnamed'


def copy_if_exists(src: str | Path | None, dst: Path) -> str | None:
    if not src:
        return None
    src_p = Path(src)
    if not src_p.exists() or not src_p.is_file():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_p, dst)
    return str(dst)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def build_delivery(
    label: str,
    root_dir: Path,
    material_pack_json: Path,
    material_pack_md: Path,
    master_json: Path,
    master_md: Path,
    master_index_json: Path,
    refined_json: Path,
    refined_md: Path,
    script_paths: list[Path],
    extra_stage_files: list[Path] | None = None,
) -> tuple[Path, Path]:
    root_dir.mkdir(parents=True, exist_ok=True)
    use_dir = root_dir / '实际用写作包'
    code_dir = root_dir / '代码'
    stage_dir = root_dir / '全链路中间结果'
    use_dir.mkdir(parents=True, exist_ok=True)
    code_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    material = load_json(material_pack_json)
    refined = load_json(refined_json)
    master = load_json(master_json)

    # Core human-readable files
    copy_if_exists(material_pack_md, use_dir / '01_写作材料包_人看版.md')
    copy_if_exists(material_pack_json, use_dir / '01_写作材料包.json')
    copy_if_exists(master_md, use_dir / '02_总文件_人看版.md')
    copy_if_exists(master_json, use_dir / '02_总文件_项目看版.json')
    copy_if_exists(master_index_json, use_dir / '02_总文件_索引.json')
    copy_if_exists(refined_md, use_dir / '04_单图证据提取_人看版.md')
    copy_if_exists(refined_json, use_dir / '04_单图证据提取.json')

    image_root = use_dir / '图级主证据'
    image_root.mkdir(parents=True, exist_ok=True)

    copied_image_groups = []
    missing_images = []
    total_raw = 0
    total_crop = 0

    for fig in refined.get('single_figure_cards_refined', []):
        fig_id = fig.get('figure_id') or f"f{fig.get('figure_number') or 'x'}"
        fig_num = int(fig.get('figure_number') or 0)
        fig_dir = image_root / f'{fig_num:02d}_{safe_name(fig_id)}'
        fig_dir.mkdir(parents=True, exist_ok=True)
        primary = fig.get('primary_single_figure') or {}
        record = {
            'figure_id': fig_id,
            'figure_number': fig_num,
            'caption': fig.get('caption', ''),
            'page': fig.get('page'),
            'copied_files': {},
        }
        raw = (primary.get('raw_embedded_image') or {}).get('image_path')
        crop = (primary.get('page_crop_image') or {}).get('image_path')
        if raw:
            raw_src = Path(raw)
            raw_dst = fig_dir / raw_src.name
            if copy_if_exists(raw_src, raw_dst):
                record['copied_files']['raw'] = str(raw_dst.relative_to(use_dir))
                total_raw += 1
            else:
                missing_images.append({'figure_id': fig_id, 'kind': 'raw', 'source_path': raw})
        if crop:
            crop_src = Path(crop)
            crop_dst = fig_dir / crop_src.name
            if copy_if_exists(crop_src, crop_dst):
                record['copied_files']['page_crop'] = str(crop_dst.relative_to(use_dir))
                total_crop += 1
            else:
                missing_images.append({'figure_id': fig_id, 'kind': 'page_crop', 'source_path': crop})

        meta = {
            'figure_id': fig_id,
            'figure_number': fig_num,
            'page': fig.get('page'),
            'caption': fig.get('caption', ''),
            'selection_reason': fig.get('selection_reason', ''),
            'supporting_claims': fig.get('supporting_claims', []),
            'supporting_writing_point_ids': fig.get('supporting_writing_point_ids', []),
            'copied_files': record['copied_files'],
        }
        dump_json(meta, fig_dir / 'figure_card.json')
        copied_image_groups.append(record)

    # Stage files for traceability
    for p in [material_pack_json, material_pack_md, master_json, master_md, master_index_json, refined_json, refined_md]:
        copy_if_exists(p, stage_dir / p.name)
    if extra_stage_files:
        for p in extra_stage_files:
            copy_if_exists(p, stage_dir / p.name)

    # Script files
    for sp in script_paths:
        copy_if_exists(sp, code_dir / sp.name)

    summary = {
        'label': label,
        'status': 'ok' if not missing_images else 'partial',
        'source_pdf': material.get('source_pdf'),
        'pack_summary': material.get('pack_summary', {}),
        'master_quality_gates': master.get('quality_gates', {}),
        'image_summary': {
            'figure_cards_total': len(refined.get('single_figure_cards_refined', [])),
            'raw_images_copied': total_raw,
            'page_crops_copied': total_crop,
            'missing_images': missing_images,
        },
        'paths': {
            'writing_pack_md': '01_写作材料包_人看版.md',
            'writing_pack_json': '01_写作材料包.json',
            'master_md': '02_总文件_人看版.md',
            'master_json': '02_总文件_项目看版.json',
            'master_index_json': '02_总文件_索引.json',
            'figure_evidence_dir': '图级主证据',
        },
        'figure_evidence_index': copied_image_groups,
    }
    dump_json(summary, use_dir / '03_实际用写作包清单.json')

    guide = f"""# 交付包说明

- 文档标签：{label}
- 来源 PDF：`{material.get('source_pdf','')}`
- 写作点数量：{material.get('pack_summary',{}).get('writing_point_cards', 0)}
- 图卡数量：{material.get('pack_summary',{}).get('single_figure_cards', 0)}
- 成功拷入 raw 主图：{total_raw}
- 成功拷入 page_crop 辅助定位图：{total_crop}

## 建议使用顺序

1. 先看 `实际用写作包/01_写作材料包_人看版.md`
2. 再看 `实际用写作包/02_总文件_人看版.md`
3. 需要图证据时，打开 `实际用写作包/图级主证据/`
4. 若要程序调用，优先用 `实际用写作包/03_实际用写作包清单.json`

## 图片说明

- `raw`：主交付图，优先使用。
- `page_crop`：辅助定位图，用于核对页面位置和图号。
"""
    write_text(root_dir / 'README_交付包说明.md', guide)

    zip_path = root_dir.with_suffix('.zip')
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root_dir.rglob('*')):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(root_dir.parent)))
    return root_dir, zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description='构建最终交付包（带图片的实际用写作包）。')
    parser.add_argument('--label', required=True)
    parser.add_argument('--out-root', required=True)
    parser.add_argument('--material-pack-json', required=True)
    parser.add_argument('--material-pack-md', required=True)
    parser.add_argument('--master-json', required=True)
    parser.add_argument('--master-md', required=True)
    parser.add_argument('--master-index-json', required=True)
    parser.add_argument('--refined-json', required=True)
    parser.add_argument('--refined-md', required=True)
    parser.add_argument('--scripts', nargs='*', default=[])
    parser.add_argument('--extra-stage-files', nargs='*', default=[])
    args = parser.parse_args()

    root, zip_path = build_delivery(
        label=args.label,
        root_dir=Path(args.out_root),
        material_pack_json=Path(args.material_pack_json),
        material_pack_md=Path(args.material_pack_md),
        master_json=Path(args.master_json),
        master_md=Path(args.master_md),
        master_index_json=Path(args.master_index_json),
        refined_json=Path(args.refined_json),
        refined_md=Path(args.refined_md),
        script_paths=[Path(x) for x in args.scripts],
        extra_stage_files=[Path(x) for x in args.extra_stage_files],
    )
    print(json.dumps({'status': 'ok', 'root_dir': str(root), 'zip_path': str(zip_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

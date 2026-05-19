from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def build_volume_bundle(material_pack_paths: list[str | Path], volume_id: str = 'V01') -> dict[str, Any]:
    packs = [_load_json(p) for p in material_pack_paths]

    merged_points: list[dict[str, Any]] = []
    merged_figures: list[dict[str, Any]] = []
    merged_refs: list[dict[str, Any]] = []

    for idx, pack in enumerate(packs, start=1):
        paper_id = pack.get('paper_id') or f'P{idx:04d}'
        for wp in pack.get('writing_point_cards', []) or []:
            row = dict(wp)
            row['source_paper_id'] = paper_id
            merged_points.append(row)
        for fig in pack.get('single_figure_cards', []) or []:
            row = dict(fig)
            row['source_paper_id'] = paper_id
            merged_figures.append(row)
        for ref in pack.get('selected_references', []) or []:
            row = dict(ref)
            row['source_paper_id'] = paper_id
            merged_refs.append(row)

    return {
        'status': 'volume_bundle_ready',
        'volume_id': volume_id,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'paper_count': len(packs),
        'writing_points': merged_points,
        'figures': merged_figures,
        'references': merged_refs,
        'stats': {
            'writing_point_count': len(merged_points),
            'figure_count': len(merged_figures),
            'reference_count': len(merged_refs),
        },
    }


def dump_volume_bundle(bundle: dict[str, Any], output_json: str | Path) -> None:
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')

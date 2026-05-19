from __future__ import annotations

import argparse
import json
from pathlib import Path

from layers.v_layer_volume_bundle import build_volume_bundle, dump_volume_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description='V-Layer: 合并多篇 writing_material_pack 为 volume_bundle。')
    parser.add_argument('--inputs', nargs='+', required=True, help='多个写作材料包 JSON 路径')
    parser.add_argument('--output-json', required=True, help='输出 volume_bundle.json 路径')
    parser.add_argument('--volume-id', default='V01')
    args = parser.parse_args()

    bundle = build_volume_bundle(args.inputs, volume_id=args.volume_id)
    dump_volume_bundle(bundle, args.output_json)
    print(json.dumps({'status': bundle['status'], 'paper_count': bundle['paper_count'], 'output': str(Path(args.output_json).resolve())}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

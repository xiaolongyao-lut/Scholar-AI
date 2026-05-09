from __future__ import annotations

import argparse
import json

from layers.a_layer_agent_coordinator import ARCHITECTURE_LAYERS, infer_open_focus_points


def main() -> None:
    parser = argparse.ArgumentParser(description='A-Layer 调度分析：提取临时关注点。')
    parser.add_argument('--command', default='')
    parser.add_argument('--goal', default='')
    args = parser.parse_args()

    open_points = infer_open_focus_points(args.command, args.goal)
    print(json.dumps({
        'status': 'orchestration_ready',
        'architecture_layers': ARCHITECTURE_LAYERS,
        'open_focus_points': open_points,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

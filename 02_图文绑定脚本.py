# -*- coding: utf-8 -*-
"""Legacy compatibility wrapper for the evidence binding CLI."""

from __future__ import annotations

import sys

from literature_assistant.core.media_binder import main as _core_main


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python 02_图文绑定脚本.py <input_extract_json> [output_json]')
    _core_main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == '__main__':
    main()
# -*- coding: utf-8 -*-
"""Legacy compatibility wrapper for the full extraction CLI."""

from __future__ import annotations

import sys

from literature_assistant.core.extractor_full import main as _core_main


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python 01_完整提取脚本.py <input_pdf> [output_json]')
    _core_main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == '__main__':
    main()
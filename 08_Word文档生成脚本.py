# -*- coding: utf-8 -*-
"""Legacy compatibility wrapper for the Word report generator."""

from __future__ import annotations

from literature_assistant.core.word_generator import main as _core_main


def main() -> None:
    _core_main()


if __name__ == '__main__':
    main()
# -*- coding: utf-8 -*-
"""Legacy compatibility wrapper for material-pack generation."""

from __future__ import annotations

from literature_assistant.core.material_bundler import (
    build_material_pack,
    build_semantic_themes,
    main as _core_main,
)

__all__ = ["build_material_pack", "build_semantic_themes", "main"]


def main() -> None:
    _core_main()


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""PyInstaller hiddenimports audit — compare registered routers vs spec file.

Prevents runtime ImportError by ensuring all dynamically imported router modules
are listed in the PyInstaller spec's hiddenimports.

Exit codes:
    0 — all routers present in hiddenimports
    1 — missing routers detected or error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_router_imports_from_server(server_path: Path) -> set[str]:
    """Extract router module names from include_router calls."""
    text = server_path.read_text(encoding="utf-8")

    # Match: from <module> import <name> [as <alias>]
    # e.g., from routers.chat_router import router as chat_router
    router_modules = set()
    for match in re.finditer(
        r"from\s+(routers\.[\w_]+|recovery_autopilot_router)\s+import\s+\w+(?:\s+as\s+\w+)?",
        text
    ):
        module_name = match.group(1)
        router_modules.add(module_name)

    return router_modules


def extract_hiddenimports_from_spec(spec_path: Path) -> set[str]:
    """Extract hiddenimports list from PyInstaller spec file."""
    text = spec_path.read_text(encoding="utf-8")

    # Match: hiddenimports = [...]
    match = re.search(r"hiddenimports\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not match:
        return set()

    list_content = match.group(1)
    # Extract quoted strings
    hidden = set()
    for string_match in re.finditer(r'["\']([^"\']+)["\']', list_content):
        hidden.add(string_match.group(1))

    return hidden


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit PyInstaller hiddenimports vs registered routers"
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("packaging/pyinstaller/literature-assistant.spec"),
        help="PyInstaller spec file path",
    )
    parser.add_argument(
        "--server",
        type=Path,
        default=Path("literature_assistant/core/python_adapter_server.py"),
        help="Server file path",
    )
    args = parser.parse_args(argv)

    if not args.server.exists():
        print(f"ERROR: server file not found: {args.server}", file=sys.stderr)
        return 1

    if not args.spec.exists():
        print(f"ERROR: spec file not found: {args.spec}", file=sys.stderr)
        return 1

    try:
        routers = extract_router_imports_from_server(args.server)
        hidden = extract_hiddenimports_from_spec(args.spec)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    missing = routers - hidden

    if missing:
        print("FAIL: The following router modules are registered but not in hiddenimports:")
        for module in sorted(missing):
            print(f"  - {module}")
        print()
        print(f"Add them to {args.spec} hiddenimports list.")
        return 1

    print(f"PASS: All {len(routers)} registered routers are in hiddenimports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

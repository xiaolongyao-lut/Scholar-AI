"""Export the FastAPI OpenAPI schema to a JSON file.

This keeps the generated contract snapshot in sync with the running API and
provides a stable input for frontend type generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python_adapter_server import app  # noqa: E402


def export_schema(output_path: Path) -> None:
    schema = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI schema")
    parser.add_argument(
        "--output",
        default=str(ROOT / "frontend" / "openapi" / "modular-pipeline-openapi.json"),
        help="Where to write the OpenAPI JSON schema.",
    )
    args = parser.parse_args()
    export_schema(Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
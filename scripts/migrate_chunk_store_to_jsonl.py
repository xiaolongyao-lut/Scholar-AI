from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from routers import resources_router as rr


def _discover_project_ids(root: Path) -> list[str]:
    project_ids: list[str] = []
    for legacy_path in sorted(root.glob("*_chunks.json")):
        project_ids.append(legacy_path.name[: -len("_chunks.json")])
    return project_ids


def migrate_project(root: Path, project_id: str) -> dict[str, object]:
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    rr._CHUNK_STORE_DIR = root

    legacy_path = root / f"{rr._safe_project_id(project_id)}_chunks.json"
    if not legacy_path.exists():
        return {"project_id": project_id, "status": "skipped", "reason": "legacy_missing"}

    store = rr._load_chunk_store(project_id)
    rr._save_chunk_store(project_id, store)

    # 迁移��功后将旧文件备份，不再写回 legacy 视图
    legacy_bak = legacy_path.with_suffix(".json.legacy.bak")
    if not legacy_bak.exists():
        legacy_path.rename(legacy_bak)

    project_dir = root / rr._safe_project_id(project_id)
    manifest = json.loads((project_dir / "manifest.json").read_text(encoding="utf-8"))
    total_chunks = sum(
        int(entry.get("total_chunks") or entry.get("count") or 0)
        for entry in manifest.get("materials", {}).values()
        if isinstance(entry, dict)
    )
    return {
        "project_id": project_id,
        "status": "migrated",
        "materials": len(store),
        "total_chunks": total_chunks,
        "project_dir": str(project_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy *_chunks.json stores to per-material JSONL layout.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("output/chunk_store"),
        help="Chunk store root directory containing legacy *_chunks.json files.",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        dest="project_ids",
        default=[],
        help="Specific project_id to migrate. Repeat to migrate multiple projects.",
    )
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    project_ids = list(args.project_ids or []) or _discover_project_ids(root)
    if not project_ids:
        print(json.dumps({"status": "noop", "root": str(root), "reason": "no_legacy_files_found"}, ensure_ascii=False))
        return 0

    results = [migrate_project(root, project_id) for project_id in project_ids]
    print(json.dumps({"root": str(root), "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

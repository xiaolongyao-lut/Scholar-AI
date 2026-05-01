# -*- coding: utf-8 -*-
"""Non-interactive MemPalace bootstrap for the Modular Pipeline workspace."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from datetime_utils import utc_now_iso_z
from project_paths import REPO_ROOT, output_path

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from layers.m_layer_mempalace_memory import (  # noqa: E402
    MempalaceMemoryAdapter,
    MempalaceSettings,
    load_mempalace_settings,
)


DEFAULT_BOOTSTRAP_AGENT = "modular-pipeline-bootstrap"
DEFAULT_BOOTSTRAP_ROOM = "bootstrap-history"
DEFAULT_EXCLUDED_DIRS = {
    ".backup_before_script_rename_20260404_232650_808",
    ".git",
    ".pytest_cache",
    ".rollback_snapshots",
    ".venv",
    ".vs",
    "__pycache__",
    "legacy_archive",
    "output",
}


@dataclass(frozen=True)
class BootstrapSummary:
    """Serializable summary of a bootstrap run."""

    project_dir: str
    palace_path: str
    wing: str
    config_path: str
    identity_path: str
    rollback_snapshot: str | None
    config_written: bool
    identity_written: bool
    bootstrap_memory: dict[str, Any] | None
    conversation_imports: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe payload."""
        return {
            "project_dir": self.project_dir,
            "palace_path": self.palace_path,
            "wing": self.wing,
            "config_path": self.config_path,
            "identity_path": self.identity_path,
            "rollback_snapshot": self.rollback_snapshot,
            "config_written": self.config_written,
            "identity_written": self.identity_written,
            "bootstrap_memory": self.bootstrap_memory,
            "conversation_imports": self.conversation_imports,
        }


def _iso_utc_now() -> str:
    """Return a UTC ISO timestamp."""
    return utc_now_iso_z()


def _slugify(value: str) -> str:
    """Normalize a string for wing/room names."""
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _ensure_vendor_modules(settings: MempalaceSettings) -> tuple[Any, Any]:
    """Import the vendored MemPalace helpers required for bootstrap."""
    adapter = MempalaceMemoryAdapter(settings)
    room_detector = adapter._import_module("mempalace.room_detector_local")
    miner = adapter._import_module("mempalace.miner")
    return room_detector, miner


def _detect_rooms(
    room_detector: Any,
    project_dir: Path,
    excluded_dirs: set[str],
) -> list[dict[str, Any]]:
    """Derive project rooms using MemPalace heuristics without prompting."""
    rooms = room_detector.detect_rooms_from_folders(str(project_dir))
    if not rooms or len(rooms) <= 1:
        rooms = room_detector.detect_rooms_from_files(str(project_dir))

    excluded_room_names = {_slugify(name) for name in excluded_dirs}
    normalized_rooms: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for room in rooms:
        name = str(room.get("name", "")).strip()
        if not name:
            continue
        normalized_name = _slugify(name)
        if normalized_name in excluded_room_names:
            continue
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        normalized_rooms.append(
            {
                "name": normalized_name,
                "description": str(room.get("description", f"Files related to {normalized_name}")).strip(),
                "keywords": list(room.get("keywords", [])),
            }
        )

    if "general" not in seen_names:
        normalized_rooms.append(
            {
                "name": "general",
                "description": "Files that do not fit a more specific room",
                "keywords": [],
            }
        )
    return normalized_rooms


def _write_project_config(
    config_path: Path,
    wing: str,
    rooms: list[dict[str, Any]],
    refresh: bool,
) -> bool:
    """Create or refresh the project-local MemPalace config."""
    if config_path.exists() and not refresh:
        return False

    config_payload = {
        "wing": wing,
        "rooms": [
            {
                "name": room["name"],
                "description": room["description"],
                "keywords": room.get("keywords", []),
            }
            for room in rooms
        ],
    }
    with open(config_path, "w", encoding="utf-8") as config_file:
        yaml.safe_dump(
            config_payload,
            config_file,
            allow_unicode=True,
            sort_keys=False,
        )
    return True


def _build_identity_text(project_dir: Path, wing: str, rooms: list[dict[str, Any]]) -> str:
    """Build a repo-local Layer0 identity file for wake-up context."""
    room_names = ", ".join(room["name"] for room in rooms[:12])
    return "\n".join(
        [
            "I am the Modular Pipeline harness assistant for this repository.",
            f"Primary workspace: {project_dir}",
            f"Primary memory wing: {wing}",
            "Mission: orchestrate academic literature processing, retrieval, writing, and skill-assisted runtime flows.",
            "Core subsystems: numbered pipeline scripts, semantic routing, focus registry, RAG integration, writing runtime, capability registry, and audit/approval harness.",
            "Operational rules: create rollback snapshots before risky edits, preserve backward compatibility for legacy actions, prefer typed protocol resources, and search mature external patterns before redesigning major subsystems.",
            "AI memory priority: keep short-term session state in the harness, persist durable job/project memory in MemPalace, and reserve semantic retrieval for cross-session recall.",
            f"Known rooms: {room_names}",
        ]
    ).strip()


def _write_identity(identity_path: Path, content: str, refresh: bool) -> bool:
    """Create or refresh the repo-local identity file."""
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    if identity_path.exists() and not refresh:
        return False
    with open(identity_path, "w", encoding="utf-8") as identity_file:
        identity_file.write(content + "\n")
    return True


def _create_rollback_snapshot(paths: list[Path]) -> str | None:
    """Copy mutable files into a rollback snapshot before bootstrap writes."""
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        return None

    snapshot_root = REPO_ROOT / ".rollback_snapshots" / f"mempalace-bootstrap-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    for path in existing_paths:
        shutil.copy2(path, snapshot_root / path.name)
    return str(snapshot_root)


def _mine_project(
    miner: Any,
    project_dir: Path,
    palace_path: Path,
    wing: str,
    agent: str,
    limit: int,
    dry_run: bool,
    excluded_dirs: set[str],
) -> None:
    """Run the MemPalace project miner against this repository."""
    if hasattr(miner, "SKIP_DIRS") and isinstance(miner.SKIP_DIRS, set):
        miner.SKIP_DIRS.update(excluded_dirs)
    miner.mine(
        project_dir=str(project_dir),
        palace_path=str(palace_path),
        wing_override=wing,
        agent=agent,
        limit=limit,
        dry_run=dry_run,
    )


def _mine_conversations(
    adapter: MempalaceMemoryAdapter,
    conversation_dirs: list[str],
    palace_path: Path,
    agent: str,
    limit: int,
    dry_run: bool,
    extract_mode: str,
) -> list[dict[str, Any]]:
    """Optionally import exported conversations into separate wings."""
    if not conversation_dirs:
        return []

    convo_miner = adapter._import_module("mempalace.convo_miner")
    imports: list[dict[str, Any]] = []
    for raw_dir in conversation_dirs:
        conversation_path = Path(raw_dir).expanduser()
        if not conversation_path.exists():
            raise FileNotFoundError(f"Conversation directory not found: {conversation_path}")
        wing = _slugify(f"convos_{conversation_path.name}")
        convo_miner.mine_convos(
            convo_dir=str(conversation_path),
            palace_path=str(palace_path),
            wing=wing,
            agent=agent,
            limit=limit,
            dry_run=dry_run,
            extract_mode=extract_mode,
        )
        imports.append(
            {
                "path": str(conversation_path.resolve()),
                "wing": wing,
                "extract_mode": extract_mode,
            }
        )
    return imports


def _record_bootstrap_memory(
    adapter: MempalaceMemoryAdapter,
    project_dir: Path,
    wing: str,
    rooms: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any] | None:
    """Persist one durable bootstrap record so the assistant remembers initialization."""
    if dry_run:
        return None

    content = "\n".join(
        [
            "## MemPalace Bootstrap",
            f"timestamp: {_iso_utc_now()}",
            f"project_dir: {project_dir}",
            f"wing: {wing}",
            f"room_count: {len(rooms)}",
            "purpose: Initialize durable AI memory for the Modular Pipeline harness and repository history.",
            "notes: Bootstrap created local identity context, generated non-interactive room config, and mined the repository into MemPalace.",
        ]
    )
    result = adapter.add_memory(
        wing=wing,
        room=DEFAULT_BOOTSTRAP_ROOM,
        content=content,
        source_file="bootstrap_mempalace_repo.py",
        metadata={"bootstrap": True, "room_count": len(rooms)},
        added_by=DEFAULT_BOOTSTRAP_AGENT,
    )
    return result.to_dict()


def bootstrap_repo_memory(args: argparse.Namespace) -> BootstrapSummary:
    """Bootstrap repository history into MemPalace with rollback safety."""
    project_dir = Path(args.project_dir).expanduser().resolve()
    if not project_dir.is_dir():
        raise NotADirectoryError(f"Project directory not found: {project_dir}")

    settings = load_mempalace_settings()
    palace_path = Path(args.palace).expanduser().resolve() if args.palace else settings.palace_path
    wing = _slugify(args.wing) if args.wing else settings.default_wing
    identity_path = settings.identity_path or output_path("mempalace", "identity.txt")
    config_path = project_dir / "mempalace.yaml"
    excluded_dirs = set(DEFAULT_EXCLUDED_DIRS)
    excluded_dirs.update(name.strip() for name in args.exclude_dir if isinstance(name, str) and name.strip())

    room_detector, miner = _ensure_vendor_modules(settings)
    adapter = MempalaceMemoryAdapter(
        MempalaceSettings(
            enabled=True,
            vendor_repo_path=settings.vendor_repo_path,
            palace_path=palace_path,
            collection_name=settings.collection_name,
            default_wing=wing,
            default_room=settings.default_room,
            search_limit=settings.search_limit,
            max_content_chars=settings.max_content_chars,
            auto_sync_runtime_jobs=settings.auto_sync_runtime_jobs,
            identity_path=identity_path,
        )
    )

    rooms = _detect_rooms(room_detector, project_dir, excluded_dirs)
    rollback_snapshot = _create_rollback_snapshot([config_path, identity_path])
    config_written = _write_project_config(config_path, wing, rooms, refresh=args.refresh_config)
    identity_written = _write_identity(
        identity_path,
        _build_identity_text(project_dir, wing, rooms),
        refresh=args.refresh_identity,
    )

    if not args.skip_project_mine:
        _mine_project(
            miner=miner,
            project_dir=project_dir,
            palace_path=palace_path,
            wing=wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            excluded_dirs=excluded_dirs,
        )

    conversation_imports = _mine_conversations(
        adapter=adapter,
        conversation_dirs=args.conversation_dir,
        palace_path=palace_path,
        agent=args.agent,
        limit=args.limit,
        dry_run=args.dry_run,
        extract_mode=args.extract_mode,
    )
    bootstrap_memory = _record_bootstrap_memory(
        adapter=adapter,
        project_dir=project_dir,
        wing=wing,
        rooms=rooms,
        dry_run=args.dry_run or args.skip_bootstrap_memory,
    )

    return BootstrapSummary(
        project_dir=str(project_dir),
        palace_path=str(palace_path),
        wing=wing,
        config_path=str(config_path),
        identity_path=str(identity_path),
        rollback_snapshot=rollback_snapshot,
        config_written=config_written,
        identity_written=identity_written,
        bootstrap_memory=bootstrap_memory,
        conversation_imports=conversation_imports,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Bootstrap MemPalace for this repository without interactive prompts.",
    )
    parser.add_argument(
        "--project-dir",
        default=str(REPO_ROOT),
        help="Repository directory to index into MemPalace.",
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Override the palace storage directory.",
    )
    parser.add_argument(
        "--wing",
        default=None,
        help="Override the default repository wing name.",
    )
    parser.add_argument(
        "--agent",
        default=DEFAULT_BOOTSTRAP_AGENT,
        help="Agent name recorded on mined drawers.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional file limit for project and conversation mining.",
    )
    parser.add_argument(
        "--conversation-dir",
        action="append",
        default=[],
        help="Optional exported conversation directory to import; repeat for multiple sources.",
    )
    parser.add_argument(
        "--extract-mode",
        choices=["exchange", "general"],
        default="general",
        help="Conversation extraction strategy when importing chat exports.",
    )
    parser.add_argument(
        "--refresh-config",
        action="store_true",
        help="Rewrite mempalace.yaml even if it already exists.",
    )
    parser.add_argument(
        "--refresh-identity",
        action="store_true",
        help="Rewrite the repo-local identity file even if it already exists.",
    )
    parser.add_argument(
        "--skip-project-mine",
        action="store_true",
        help="Skip project file mining and only prepare config/identity/bootstrap memory.",
    )
    parser.add_argument(
        "--skip-bootstrap-memory",
        action="store_true",
        help="Skip writing the bootstrap-history drawer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the bootstrap without writing to the palace.",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Additional top-level directories to exclude from bootstrap mining.",
    )
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        summary = bootstrap_repo_memory(args)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"success": True, **summary.to_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from literature_assistant.core.wiki.graph import WikiGraphSnapshot
from literature_assistant.core.wiki.page_store import atomic_write_text


def export_graph_json(snapshot: WikiGraphSnapshot) -> dict[str, Any]:
    """Return a deterministic graph export payload for UI/debug consumers."""

    if not isinstance(snapshot, WikiGraphSnapshot):
        raise TypeError("snapshot must be a WikiGraphSnapshot")
    return snapshot.to_dict()


def write_graph_json_export(snapshot: WikiGraphSnapshot, output_path: Path) -> None:
    """Write a graph JSON export without mutating source wiki pages."""

    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("output_path must be a file path")
    payload = json.dumps(export_graph_json(snapshot), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(output_path, payload)

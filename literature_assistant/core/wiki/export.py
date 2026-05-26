from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from literature_assistant.core.wiki.graph import WikiGraphSnapshot
from literature_assistant.core.wiki.page_store import atomic_write_text, WikiPageStore


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


def export_wiki_markdown(page_store: WikiPageStore, output_path: Path) -> dict[str, Any]:
    """Export all wiki pages as Markdown zip archive (G15 2026-05-26).

    Args:
        page_store: WikiPageStore instance
        output_path: Output zip file path

    Returns:
        Export result dict with success/page_count/output_path/errors

    Raises:
        ValueError: If output_path is a directory
    """
    if not isinstance(output_path, Path):
        output_path = Path(output_path)
    if output_path.is_dir():
        raise ValueError("output_path must be a file path, not a directory")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    errors = []
    page_count = 0

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for page_path in page_store.list_pages():
                try:
                    content = page_store.read_page(page_path)
                    if content:
                        zf.writestr(page_path.as_posix(), content)
                        page_count += 1
                except Exception as exc:
                    errors.append(f"Failed to export {page_path}: {exc}")

        return {
            "success": len(errors) == 0,
            "page_count": page_count,
            "output_path": str(output_path),
            "errors": errors,
        }
    except Exception as exc:
        return {
            "success": False,
            "page_count": 0,
            "output_path": str(output_path),
            "errors": [f"Export failed: {exc}"],
        }

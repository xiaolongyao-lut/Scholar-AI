# -*- coding: utf-8 -*-
"""Pure scan / Zotero / candidate-selection helpers.

These helpers do not touch any monkeypatched module-level state of the parent
package. They depend only on the standard library plus two pure sibling modules.
"""

from __future__ import annotations

import concurrent.futures as futures
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from ._document_extraction import _extract_document_content, _truncate_document_content
from ._search_helpers import _tokenize_search_text


__all__ = [
    "_iter_scan_files",
    "_build_source_fingerprint",
    "_extract_zotero_item_key",
    "_load_zotero_title_map",
    "_resolve_scan_workers",
    "_iter_scan_batches",
    "_extract_scan_candidate_content",
    "_score_pending_candidate_for_query",
    "_select_query_pending_candidates",
    "_normalize_project_title_for_cleanup",
    "_is_extraction_failure_placeholder",
]


# Set of file extensions and skip directories used by scan helpers.
_SCAN_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".bib", ".ipynb"}
_SCAN_SKIP_DIRS = {".scholarai", ".git", "node_modules", "__pycache__"}


def _iter_scan_files(root: Path) -> list[Path]:
    """Recursively collect supported files under root while skipping internal dirs."""
    candidates: list[Path] = []
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP_DIRS]
        current = Path(current_root)
        for filename in files:
            path = current / filename
            if path.suffix.lower() in _SCAN_EXTENSIONS:
                candidates.append(path)
    return candidates


def _build_source_fingerprint(root: Path, path: Path) -> str:
    """Build a stable-ish fingerprint for dedupe across nested folders."""
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    stat = path.stat()
    return f"{rel}|{stat.st_size}|{int(stat.st_mtime_ns)}"


def _extract_zotero_item_key(relative_path: Path) -> str | None:
    """Infer Zotero item key from storage relative path (usually first segment)."""
    if not relative_path.parts:
        return None
    first = str(relative_path.parts[0]).strip()
    if len(first) == 8 and first.isalnum():
        return first.upper()
    return None


def _load_zotero_title_map(storage_root: Path) -> dict[str, str]:
    """Load itemKey -> title from zotero.sqlite when available.

    Zotero commonly stores `storage/` under the same parent as `zotero.sqlite`.
    This is optional; failures should not block ingestion.
    """
    db_path = storage_root.parent / "zotero.sqlite"
    if not db_path.exists():
        return {}

    title_map: dict[str, str] = {}
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            queries = [
                """
                SELECT items.key, itemDataValues.value
                FROM items
                JOIN itemData ON itemData.itemID = items.itemID
                JOIN fields ON fields.fieldID = itemData.fieldID
                JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
                WHERE fields.fieldName = 'title'
                """,
                """
                SELECT items.key, itemDataValues.value
                FROM items
                JOIN itemData ON itemData.itemID = items.itemID
                JOIN fieldsCombined ON fieldsCombined.fieldID = itemData.fieldID
                JOIN itemDataValues ON itemDataValues.valueID = itemData.valueID
                WHERE fieldsCombined.fieldName = 'title'
                """,
            ]

            for query in queries:
                try:
                    cursor.execute(query)
                except sqlite3.Error:
                    continue
                for key, value in cursor.fetchall():
                    item_key = str(key or "").strip().upper()
                    title = str(value or "").strip()
                    if item_key and title and item_key not in title_map:
                        title_map[item_key] = title
        finally:
            conn.close()
    except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError):
        return {}

    return title_map

def _resolve_scan_workers(requested_workers: int | None) -> int:
    """Resolve scan worker count for I/O-bound extraction tasks.

    Uses a conservative upper bound to avoid exhausting descriptors/memory when
    indexing very large Zotero folders.
    """
    process_cpu_count = getattr(os, "process_cpu_count", None)
    process_cpu = process_cpu_count() if callable(process_cpu_count) else None
    default_workers = min(32, (process_cpu or os.cpu_count() or 1) + 4)
    if requested_workers is None:
        return default_workers
    return max(1, min(int(requested_workers), 64))


def _iter_scan_batches(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    """Split scan workload into fixed-size batches."""
    if batch_size <= 0:
        return [items]
    return [items[idx: idx + batch_size] for idx in range(0, len(items), batch_size)]


def _extract_scan_candidate_content(file_path: Path) -> tuple[str | None, str | None]:
    """Extract candidate text for scan-folder ingestion.

    Returns:
        (content, None) on success, or (None, reason) on failure.
    """
    try:
        raw = file_path.read_bytes()
        content = _truncate_document_content(_extract_document_content(file_path.name, raw))
        normalized = str(content or "").strip()
        if not normalized or _is_extraction_failure_placeholder(normalized):
            return None, "无法提取文本"
        return content, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)



def _score_pending_candidate_for_query(
    query_tokens: set[str],
    relative_posix: str,
    zotero_title: str,
) -> float:
    """Score an unindexed file candidate using filename/path/title signals."""
    query_text = " ".join(sorted(query_tokens))
    normalized_path = re.sub(r"[_\-./\\]+", " ", relative_posix.lower())
    relative_tokens = _tokenize_search_text(normalized_path)
    title_tokens = _tokenize_search_text(zotero_title.lower()) if zotero_title else set()
    matched = query_tokens & (relative_tokens | title_tokens)

    score = float(len(matched) * 3)
    if query_text and query_text in normalized_path:
        score += 6.0
    if query_text and zotero_title and query_text in zotero_title.lower():
        score += 8.0

    if query_tokens:
        score += (len(matched) / len(query_tokens)) * 5.0

    return score


def _select_query_pending_candidates(
    pending_candidates: list[dict[str, Any]],
    query: str,
    zotero_title_map: dict[str, str],
    ingest_limit: int,
) -> list[dict[str, Any]]:
    """Select query-relevant subset from pending candidates."""
    query_tokens = _tokenize_search_text(str(query or "").lower())
    if not query_tokens:
        return pending_candidates[:ingest_limit]

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in pending_candidates:
        relative_path = item["relative_path"]
        zotero_key = _extract_zotero_item_key(relative_path)
        zotero_title = zotero_title_map.get(zotero_key, "") if zotero_key else ""
        score = _score_pending_candidate_for_query(query_tokens, str(item["relative_posix"]), zotero_title)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:ingest_limit]]


def _normalize_project_title_for_cleanup(title: str) -> str:
    """Normalize project title for duplicate detection in maintenance cleanup."""
    normalized = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    return normalized


def _is_extraction_failure_placeholder(content: str) -> bool:
    """Check whether a stored document content is an extraction placeholder."""
    normalized = str(content or "").strip()
    if not normalized:
        return True
    return any(
        normalized.startswith(prefix)
        for prefix in (
            "[PDF 文件:",
            "[PDF 解析失败:",
            "[DOCX 文件:",
            "[DOCX 解析失败:",
            "[未知格式文件:",
        )
    )


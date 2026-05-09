from __future__ import annotations

from pathlib import Path
from typing import Sequence

from literature_assistant.core.wiki.connectors.base import (
    ConnectorScanReport,
    ConnectorSource,
    ensure_path_within_allowed_roots,
    path_to_safe_relative_string,
    sanitize_connector_error,
    unique_connector_source_id,
)

DEFAULT_MARKDOWN_EXCLUDE_DIRS: frozenset[str] = frozenset({".obsidian", ".git", ".trash", "templates"})
DEFAULT_MARKDOWN_EXCLUDE_SUFFIXES: tuple[str, ...] = (".excalidraw.md",)


def _read_markdown_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return path.stem


def _has_excluded_part(path: Path, root: Path, exclude_dirs: frozenset[str]) -> bool:
    relative_parts = path.relative_to(root).parts[:-1]
    return bool({part.lower() for part in relative_parts} & exclude_dirs)


def _has_excluded_suffix(path: Path, excluded_suffixes: tuple[str, ...]) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in excluded_suffixes)


class MarkdownConnector:
    """Read-only connector for Obsidian-like markdown folders.

    Args:
        root: Markdown vault or folder root to scan.
        allowed_roots: Explicit parent roots that are permitted for local reads.
        namespace: Source ID namespace, defaults to ``obsidian``.
    """

    def __init__(
        self,
        root: Path,
        *,
        allowed_roots: Sequence[Path],
        namespace: str = "obsidian",
        exclude_dirs: frozenset[str] = DEFAULT_MARKDOWN_EXCLUDE_DIRS,
        exclude_suffixes: tuple[str, ...] = DEFAULT_MARKDOWN_EXCLUDE_SUFFIXES,
    ) -> None:
        self.root = ensure_path_within_allowed_roots(Path(root), allowed_roots)
        self.namespace = namespace
        self.exclude_dirs = frozenset(part.lower() for part in exclude_dirs)
        self.exclude_suffixes = tuple(suffix.lower() for suffix in exclude_suffixes)

    def list_sources(self) -> list[ConnectorSource]:
        """List readable markdown notes without writing registry state."""

        if not self.root.exists():
            return []

        sources: list[ConnectorSource] = []
        seen_source_ids: set[str] = set()
        for path in sorted(self.root.rglob("*.md")):
            if _has_excluded_part(path, self.root, self.exclude_dirs):
                continue
            if _has_excluded_suffix(path, self.exclude_suffixes):
                continue
            text = path.read_text(encoding="utf-8")
            relative_path = path_to_safe_relative_string(path, self.root)
            title = _read_markdown_title(path, text)
            sources.append(
                ConnectorSource(
                    source_id=unique_connector_source_id(
                        self.namespace,
                        _remove_suffix(relative_path, ".md"),
                        seen_source_ids,
                    ),
                    source_type="markdown",
                    title=title,
                    path=path,
                    metadata={"relative_path": relative_path},
                )
            )
        return sources

    def _get_source(self, source_id: str) -> ConnectorSource:
        for source in self.list_sources():
            if source.source_id == source_id:
                return source
        raise KeyError(f"markdown source not found: {source_id}")

    def read_source(self, source_id: str) -> str:
        """Read one markdown source body by source ID."""

        source = self._get_source(source_id)
        return source.path.read_text(encoding="utf-8")

    def extract_metadata(self, source_id: str) -> dict[str, object]:
        """Return local metadata for one markdown source."""

        source = self._get_source(source_id)
        return {
            "source_id": source.source_id,
            "source_type": source.source_type,
            "title": source.title,
            **source.metadata,
        }

    def dry_run_scan(self) -> ConnectorScanReport:
        """Return a no-write scan summary with sanitized warnings."""

        warnings: list[str] = []
        try:
            sources = self.list_sources()
        except Exception as exc:
            sources = []
            warnings.append(sanitize_connector_error(exc))
        return ConnectorScanReport(
            connector=self.namespace,
            root=self.root.name,
            source_count=len(sources),
            source_ids=tuple(source.source_id for source in sources),
            warnings=tuple(warnings),
            would_write=False,
        )


def _remove_suffix(value: str, suffix: str) -> str:
    if value.endswith(suffix):
        return value[: -len(suffix)]
    return value

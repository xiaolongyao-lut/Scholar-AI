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


class PdfFolderConnector:
    """Read-only PDF folder connector skeleton.

    This connector intentionally lists PDF metadata only. Text extraction remains
    outside this Wave 13 skeleton so external files are not parsed or persisted
    without a later explicit design decision.
    """

    def __init__(self, root: Path, *, allowed_roots: Sequence[Path], namespace: str = "pdf") -> None:
        self.root = ensure_path_within_allowed_roots(Path(root), allowed_roots)
        self.namespace = namespace

    def list_sources(self) -> list[ConnectorSource]:
        """List PDF paths and filesystem metadata without extracting content."""

        if not self.root.exists():
            return []

        sources: list[ConnectorSource] = []
        seen_source_ids: set[str] = set()
        for path in sorted(self.root.rglob("*.pdf")):
            relative_path = path_to_safe_relative_string(path, self.root)
            sources.append(
                ConnectorSource(
                    source_id=unique_connector_source_id(
                        self.namespace,
                        _remove_suffix(relative_path, ".pdf"),
                        seen_source_ids,
                    ),
                    source_type="pdf",
                    title=path.stem,
                    path=path,
                    metadata={"relative_path": relative_path, "size_bytes": path.stat().st_size},
                )
            )
        return sources

    def _get_source(self, source_id: str) -> ConnectorSource:
        for source in self.list_sources():
            if source.source_id == source_id:
                return source
        raise KeyError(f"pdf source not found: {source_id}")

    def read_source(self, source_id: str) -> str:
        """Reject PDF text extraction until a later explicit parser design exists."""

        self._get_source(source_id)
        raise NotImplementedError("PDF text extraction is not implemented in the read-only PDF connector skeleton.")

    def extract_metadata(self, source_id: str) -> dict[str, object]:
        """Return filesystem metadata for one PDF source."""

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

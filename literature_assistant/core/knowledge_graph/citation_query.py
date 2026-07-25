"""Read-only query adapter for an existing project citation candidate store."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from literature_assistant.core.knowledge_graph.citation_models import (
    CitationMention,
    CitesCandidate,
)
from literature_assistant.core.knowledge_graph.citation_store import (
    CITATION_STORE_SCHEMA_VERSION,
    CitationBatchWriteResult,
    CitationCandidateStore,
    CitationStoreError,
)

_REQUIRED_TABLES = frozenset(
    {"citation_capture_receipts", "citation_mentions", "cites_candidates"}
)


class ReadOnlyCitationCandidateStore(CitationCandidateStore):
    """Reuse bounded store queries without schema, WAL, or candidate writes.

    The write-oriented store initializes its schema on construction. Graph GET
    controllers must not do that, so this adapter opens only an existing SQLite
    file with URI ``mode=ro`` and validates its version/tables using queries.
    Inherited ``get_*`` and ``list_*`` methods retain the original allowlisted
    filters, pagination, row validation, and corruption errors.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Open and validate one existing citation DB without modifying it.

        Args:
            db_path: Existing project-level ``citation_graph.db`` path.

        Raises:
            ValueError: If the path is empty, missing, or not a regular file.
            CitationStoreError: If the schema cannot be read or is incompatible.
        """

        if not str(db_path).strip():
            raise ValueError("db_path must be non-empty")
        resolved = Path(db_path).expanduser().resolve()
        if not resolved.is_file():
            raise ValueError("read-only citation store requires an existing SQLite file")
        self.db_path = resolved
        self._validate_existing_schema()

    def save_batch(
        self,
        mentions: Sequence[CitationMention],
        candidates: Sequence[CitesCandidate],
    ) -> CitationBatchWriteResult:
        """Reject writes so a read controller cannot mutate citation state."""

        del mentions, candidates
        raise CitationStoreError("read-only citation store does not accept writes")

    def _open(self) -> sqlite3.Connection:
        # SQLite ignores a live WAL under ``immutable=1``. Use ordinary
        # read-only mode when a WAL exists so concurrent commits stay visible;
        # otherwise immutable mode avoids creating empty WAL/SHM sidecars for
        # a pure GET. A writer starting after this snapshot is opened belongs
        # to the next read transaction, so the existence check is sufficient.
        wal_path = Path(f"{self.db_path}-wal")
        query = "mode=ro" if wal_path.is_file() else "mode=ro&immutable=1"
        uri = f"{self.db_path.as_uri()}?{query}"
        connection = sqlite3.connect(uri, uri=True, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _validate_existing_schema(self) -> None:
        connection = self._open_or_raise()
        try:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version != CITATION_STORE_SCHEMA_VERSION:
                raise CitationStoreError(
                    "citation store schema version is incompatible with read-only projection"
                )
            required_tables = tuple(sorted(_REQUIRED_TABLES))
            placeholders = ", ".join("?" for _ in required_tables)
            rows = connection.execute(
                "SELECT name FROM sqlite_master "
                f"WHERE type = 'table' AND name IN ({placeholders})",
                required_tables,
            ).fetchall()
            available = {str(row["name"]) for row in rows}
            if available != _REQUIRED_TABLES:
                raise CitationStoreError("citation store is missing required tables")
        except CitationStoreError:
            raise
        except sqlite3.Error as exc:
            raise CitationStoreError("failed to validate citation store schema") from exc
        finally:
            connection.close()


__all__ = ["ReadOnlyCitationCandidateStore"]

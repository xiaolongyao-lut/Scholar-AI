from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from literature_assistant.core.project_paths import ensure_directory, wiki_trace_path
from literature_assistant.core.wiki.evidence_adapter import build_synthesis_body, coerce_evidence_refs
from literature_assistant.core.wiki.models import WikiPageKind, WikiPageStatus
from literature_assistant.core.wiki.observability import WikiObservabilitySink
from literature_assistant.core.wiki.page_store import AUTO_END, AUTO_START, WikiPageStore, render_page, stable_slug
from literature_assistant.core.wiki.source_registry import derive_chunk_id

_MANIFEST_DRILLDOWN_LIMIT = 10
_SOURCE_MANIFEST_ENTRIES_KEY = "source_manifest_entries_json"


@dataclass(frozen=True)
class WikiManifestDiffItem:
    """One bounded source-manifest delta for page-level integrity diagnostics."""

    kind: str
    page_path: str
    source_hash: str | None = None
    indexed_hash: str | None = None
    redacted: bool = False

    def to_dict(self, *, redacted: bool | None = None) -> dict[str, Any]:
        should_redact = self.redacted if redacted is None else redacted
        return {
            "kind": self.kind,
            "page_path": "<redacted>" if should_redact else self.page_path,
            "source_hash": None if should_redact else self.source_hash,
            "indexed_hash": None if should_redact else self.indexed_hash,
            "redacted": should_redact,
        }


@dataclass(frozen=True)
class WikiManifestDrilldown:
    """Bounded page-level manifest diff for source-to-index traceability."""

    status: str
    missing_count: int = 0
    extra_count: int = 0
    mismatched_count: int = 0
    missing_pages: tuple[WikiManifestDiffItem, ...] = ()
    extra_pages: tuple[WikiManifestDiffItem, ...] = ()
    mismatched_pages: tuple[WikiManifestDiffItem, ...] = ()
    truncated: bool = False
    limit: int = 10
    schema_version: str = "scholar-ai-wiki-manifest-drilldown/v1"
    hash_algorithm: str = "sha256"

    def to_dict(self, *, redact_extra_pages: bool = False) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "hash_algorithm": self.hash_algorithm,
            "limit": self.limit,
            "missing_count": self.missing_count,
            "extra_count": self.extra_count,
            "mismatched_count": self.mismatched_count,
            "truncated": self.truncated,
            "missing_pages": [item.to_dict() for item in self.missing_pages],
            "extra_pages": [item.to_dict(redacted=redact_extra_pages) for item in self.extra_pages],
            "mismatched_pages": [item.to_dict() for item in self.mismatched_pages],
        }


@dataclass(frozen=True)
class WikiRetrievalStatus:
    index_hash: str
    page_count: int
    stale: bool
    last_indexed: str
    integrity_status: str = "unknown"
    source_manifest_hash: str = "unknown"
    indexed_source_manifest_hash: str = "unknown"
    source_page_count: int | None = None
    indexed_source_page_count: int | None = None
    warnings: tuple[str, ...] = ()
    manifest_drilldown: WikiManifestDrilldown = WikiManifestDrilldown(status="unknown")


@dataclass(frozen=True)
class WikiSourceManifest:
    """Hash summary for the authoritative generated wiki Markdown source set."""

    source_manifest_hash: str
    page_count: int
    entries: tuple[str, ...]


@dataclass(frozen=True)
class WikiSearchResult:
    page_path: Path
    title: str
    score: float
    snippet: str
    source: str = "wiki_fts"


@dataclass(frozen=True)
class WikiKnowledgeRef:
    """Bounded, machine-readable knowledge ref for a generated wiki page.

    The ref keeps the agent-readable page resource separate from the
    hash-derived chunk id so QA and agent callers can share one retrieval
    contract without copying wiki page bodies into project chunk stores.
    """

    schema_version: str
    ref_id: str
    chunk_id: str
    title: str
    source_type: str
    source: str
    source_path: str
    page_path: str
    source_hash: str
    content_hash: str
    span_start: int
    span_end: int
    content: str
    summary: str
    read_endpoint: str
    score: float
    rank: int
    truncated: bool

    def to_hit(self, *, include_content: bool = False) -> dict[str, Any]:
        """Return a retrieval-hit payload safe for fusion diagnostics."""

        metadata: dict[str, Any] = {
            "knowledge_ref_schema_version": self.schema_version,
            "ref_id": self.ref_id,
            "chunk_id": self.chunk_id,
            "resource_kind": "chunk",
            "page_path": self.page_path,
            "source_path": self.source_path,
            "source": self.source_type,
            "source_type": self.source_type,
            "retrieval_source": self.source,
            "source_hash": self.source_hash,
            "content_hash": self.content_hash,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "read_endpoint": self.read_endpoint,
            "bounded": True,
            "truncated": self.truncated,
        }
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "doc_id": self.ref_id,
            "ref_id": self.ref_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "summary": self.summary,
            "page_path": self.page_path,
            "source_path": self.source_path,
            "read_endpoint": self.read_endpoint,
            "source_type": self.source_type,
            "source": self.source,
            "source_hash": self.source_hash,
            "content_hash": self.content_hash,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "score": self.score,
            "rank": self.rank,
            "truncated": self.truncated,
            "metadata": metadata,
        }
        if include_content:
            payload["content"] = self.content
        return payload


class WikiQueryIndex:
    def __init__(self, db_path: Path, *, observability_sink: WikiObservabilitySink | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._warmup_done = False
        self.observability_sink = observability_sink

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def initialize(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS wiki_pages_fts
            USING fts5(page_path, title, body, tokenize='unicode61')
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wiki_index_status (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    def warmup_common_queries(self, common_patterns: list[str] | None = None) -> None:
        """Pre-load FTS index for common query patterns to reduce first-query latency.

        Tier 1 optimization: Cache warmup (0.5-1s savings on first query).
        Runs once per index instance; subsequent calls are no-ops.

        Args:
            common_patterns: List of common search patterns. If None, uses defaults.
        """
        if self._warmup_done:
            return

        if common_patterns is None:
            common_patterns = ["research", "study", "analysis", "method", "data"]

        conn = self._get_conn()
        try:
            for pattern in common_patterns:
                if pattern and pattern.strip():
                    conn.execute(
                        "SELECT COUNT(*) FROM wiki_pages_fts WHERE wiki_pages_fts MATCH ?",
                        (pattern,),
                    )
            self._warmup_done = True
        except Exception:
            pass

    def index_page(self, page_path: Path, title: str, body: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO wiki_pages_fts (page_path, title, body) VALUES (?, ?, ?)",
            (str(page_path), title, body),
        )
        digest = hashlib.sha256(
            f"{Path(page_path).as_posix()}:{title}:{body}".encode("utf-8")
        ).hexdigest()
        conn.execute(
            "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
            ("index_hash", digest),
        )
        conn.execute(
            "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
            ("last_indexed", datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
        )
        conn.commit()

    def search(self, query: str, limit: int = 10) -> list[WikiSearchResult]:
        if not query or not query.strip():
            return []
        if limit <= 0:
            return []
        span = (
            self.observability_sink.start_span("wiki.query.index.search", {"limit": limit})
            if self.observability_sink is not None
            else None
        )
        if span is not None:
            span.__enter__()
        conn = self._get_conn()
        span_error: BaseException | None = None
        try:
            cursor = conn.execute(
                """
                SELECT page_path, title, snippet(wiki_pages_fts, 2, '<b>', '</b>', '...', 64) as snippet, rank
                FROM wiki_pages_fts
                WHERE wiki_pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            results: list[WikiSearchResult] = []
            for row in cursor:
                results.append(
                    WikiSearchResult(
                        page_path=Path(row["page_path"]),
                        title=row["title"],
                        score=-row["rank"],
                        snippet=row["snippet"],
                        source="wiki_fts",
                    )
                )
            if self.observability_sink is not None:
                self.observability_sink.record_metric(
                    "wiki.query.index.hit_count",
                    len(results),
                    {"limit": limit, "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]},
                    unit="hits",
            )
            return results
        except Exception as exc:
            span_error = exc
            raise
        finally:
            if span is not None:
                if span_error is None:
                    span.__exit__(None, None, None)
                else:
                    span.__exit__(type(span_error), span_error, span_error.__traceback__)

    def get_status(self, page_store: WikiPageStore | None = None) -> WikiRetrievalStatus:
        """Return retrieval index state, optionally checked against source pages.

        Args:
            page_store: Optional authoritative wiki page store. When supplied,
                the returned status proves whether the current source manifest
                still matches the manifest recorded when the FTS index was built.
        """

        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) as count FROM wiki_pages_fts")
        page_count = cursor.fetchone()["count"]
        cursor = conn.execute("SELECT value FROM wiki_index_status WHERE key = 'index_hash'")
        row = cursor.fetchone()
        index_hash = row["value"] if row else "none"
        cursor = conn.execute("SELECT value FROM wiki_index_status WHERE key = 'last_indexed'")
        row = cursor.fetchone()
        last_indexed = row["value"] if row else "never"
        indexed_source_manifest_hash = self._status_value("source_manifest_hash", default="unknown")
        indexed_source_page_count = _parse_optional_int(self._status_value("source_page_count", default=""))
        indexed_manifest_entries = self._status_manifest_entries()
        source_manifest_hash = indexed_source_manifest_hash
        source_page_count = indexed_source_page_count
        integrity_status = "unknown"
        stale = False
        warnings: list[str] = []
        manifest_drilldown = WikiManifestDrilldown(status=integrity_status)

        if indexed_source_page_count is not None and indexed_source_page_count != page_count:
            stale = True
            integrity_status = "index_count_mismatch"
            warnings.append(
                "Wiki query index row count differs from the source page count recorded during indexing."
            )

        if page_store is not None:
            manifest = build_source_manifest(page_store)
            source_manifest_entries = _manifest_entries_to_map(manifest.entries)
            source_manifest_hash = manifest.source_manifest_hash
            source_page_count = manifest.page_count
            if indexed_source_manifest_hash in {"", "none", "unknown"}:
                stale = manifest.page_count > 0 or page_count > 0
                integrity_status = "missing_manifest" if stale else "empty_unproven"
                warnings.append(
                    "Wiki query index does not record a source manifest hash; rebuild before treating it as current."
                )
            elif manifest.page_count != page_count:
                stale = True
                integrity_status = "page_count_mismatch"
                warnings.append(
                    "Wiki query index page count differs from the current generated wiki page count."
                )
            elif manifest.source_manifest_hash != indexed_source_manifest_hash:
                stale = True
                integrity_status = "source_hash_mismatch"
                warnings.append(
                    "Wiki query index source manifest hash differs from the current generated wiki pages."
                )
            elif not stale:
                integrity_status = "aligned"

            if indexed_manifest_entries is None:
                drilldown_status = (
                    "missing_indexed_entries"
                    if indexed_source_manifest_hash not in {"", "none", "unknown"}
                    else integrity_status
                )
                if stale and drilldown_status == "missing_indexed_entries":
                    warnings.append(
                        "Wiki query index does not record page-level source manifest entries; rebuild for page-level drift details."
                    )
                manifest_drilldown = WikiManifestDrilldown(status=drilldown_status)
            else:
                manifest_drilldown = _build_manifest_drilldown(
                    source_manifest_entries,
                    indexed_manifest_entries,
                    status=integrity_status,
                    limit=_MANIFEST_DRILLDOWN_LIMIT,
                )
        elif not stale and indexed_source_manifest_hash not in {"", "none", "unknown"}:
            integrity_status = "indexed_manifest_recorded"
            manifest_drilldown = WikiManifestDrilldown(status=integrity_status)
        else:
            manifest_drilldown = WikiManifestDrilldown(status=integrity_status)

        return WikiRetrievalStatus(
            index_hash=index_hash,
            page_count=page_count,
            stale=stale,
            last_indexed=last_indexed,
            integrity_status=integrity_status,
            source_manifest_hash=source_manifest_hash,
            indexed_source_manifest_hash=indexed_source_manifest_hash,
            source_page_count=source_page_count,
            indexed_source_page_count=indexed_source_page_count,
            warnings=tuple(dict.fromkeys(warnings)),
            manifest_drilldown=manifest_drilldown,
        )

    def _status_value(self, key: str, *, default: str) -> str:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be non-empty")
        conn = self._get_conn()
        cursor = conn.execute("SELECT value FROM wiki_index_status WHERE key = ?", (key,))
        row = cursor.fetchone()
        return str(row["value"]) if row else default

    def _status_manifest_entries(self) -> dict[str, str] | None:
        raw_entries = self._status_value(_SOURCE_MANIFEST_ENTRIES_KEY, default="")
        return _decode_manifest_entries(raw_entries)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def build_wiki_index(self, page_store: WikiPageStore) -> None:
        """Build this index from a page store for legacy method callers."""

        build_wiki_index(page_store, self)


def build_wiki_index(page_store: WikiPageStore, index: WikiQueryIndex) -> None:
    if not isinstance(page_store, WikiPageStore):
        raise TypeError("page_store must be a WikiPageStore")
    if not isinstance(index, WikiQueryIndex):
        raise TypeError("index must be a WikiQueryIndex")
    index.initialize()
    conn = index._get_conn()
    conn.execute("DELETE FROM wiki_pages_fts")
    conn.commit()
    manifest = build_source_manifest(page_store)
    indexed_payload: list[str] = []
    for page_path in page_store.list_pages():
        content = page_store.read_page(page_path)
        if content:
            title, body = _extract_indexable_page(content)
            index.index_page(page_path, title, body)
            indexed_payload.append(f"{page_path.as_posix()}:{title}:{hashlib.sha256(body.encode('utf-8')).hexdigest()}")
    index_hash = hashlib.sha256("\n".join(sorted(indexed_payload)).encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
        ("index_hash", index_hash),
    )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, datetime('now'))",
        ("last_indexed",),
    )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
        ("source_manifest_hash", manifest.source_manifest_hash),
    )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
        ("source_page_count", str(manifest.page_count)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
        ("source_manifest_schema", "scholar-ai-wiki-source-manifest/v1"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO wiki_index_status (key, value) VALUES (?, ?)",
        (_SOURCE_MANIFEST_ENTRIES_KEY, _encode_manifest_entries(manifest)),
    )
    conn.commit()


def build_source_manifest(page_store: WikiPageStore) -> WikiSourceManifest:
    """Build a deterministic manifest for generated wiki Markdown pages.

    Args:
        page_store: Authoritative generated wiki page store.

    Returns:
        Manifest hash over relative page paths and raw Markdown content hashes.
    """

    if not isinstance(page_store, WikiPageStore):
        raise TypeError("page_store must be a WikiPageStore")
    entries: list[str] = []
    for page_path in page_store.list_pages():
        content = page_store.read_page(page_path)
        if content is None:
            continue
        content_hash = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
        entries.append(f"{page_path.as_posix()}:{content_hash}")
    sorted_entries = tuple(sorted(entries))
    source_manifest_hash = hashlib.sha256("\n".join(sorted_entries).encode("utf-8")).hexdigest()
    return WikiSourceManifest(
        source_manifest_hash=source_manifest_hash,
        page_count=len(sorted_entries),
        entries=sorted_entries,
    )


def _parse_optional_int(value: str) -> int | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _encode_manifest_entries(manifest: WikiSourceManifest) -> str:
    if not isinstance(manifest, WikiSourceManifest):
        raise TypeError("manifest must be a WikiSourceManifest")
    entries = [
        {"page_path": page_path, "source_hash": source_hash}
        for page_path, source_hash in _manifest_entries_to_map(manifest.entries).items()
    ]
    return json.dumps(
        {
            "schema_version": "scholar-ai-wiki-source-manifest-entries/v1",
            "hash_algorithm": "sha256",
            "entries": entries,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_manifest_entries(raw_entries: str) -> dict[str, str] | None:
    if not str(raw_entries or "").strip():
        return None
    try:
        payload = json.loads(raw_entries)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return None
    decoded: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        page_path = _safe_manifest_page_path(item.get("page_path"))
        source_hash = item.get("source_hash")
        if page_path is None or not _is_sha256_hex(source_hash):
            continue
        decoded[page_path] = str(source_hash)
    return decoded


def _manifest_entries_to_map(entries: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(entries, tuple):
        raise TypeError("entries must be a tuple")
    mapped: dict[str, str] = {}
    for entry in entries:
        page_path_raw, separator, content_hash = str(entry).rpartition(":")
        page_path = _safe_manifest_page_path(page_path_raw)
        if separator != ":" or page_path is None or not _is_sha256_hex(content_hash):
            continue
        mapped[page_path] = content_hash
    return dict(sorted(mapped.items()))


def _build_manifest_drilldown(
    source_entries: dict[str, str],
    indexed_entries: dict[str, str],
    *,
    status: str,
    limit: int,
) -> WikiManifestDrilldown:
    if limit < 0:
        raise ValueError("limit must be non-negative")
    missing_paths = sorted(set(source_entries) - set(indexed_entries))
    extra_paths = sorted(set(indexed_entries) - set(source_entries))
    mismatched_paths = sorted(
        page_path
        for page_path in set(source_entries).intersection(indexed_entries)
        if source_entries[page_path] != indexed_entries[page_path]
    )
    return WikiManifestDrilldown(
        status=status,
        missing_count=len(missing_paths),
        extra_count=len(extra_paths),
        mismatched_count=len(mismatched_paths),
        missing_pages=tuple(
            WikiManifestDiffItem(
                kind="missing",
                page_path=page_path,
                source_hash=source_entries[page_path],
            )
            for page_path in missing_paths[:limit]
        ),
        extra_pages=tuple(
            WikiManifestDiffItem(
                kind="extra",
                page_path=page_path,
                indexed_hash=indexed_entries[page_path],
            )
            for page_path in extra_paths[:limit]
        ),
        mismatched_pages=tuple(
            WikiManifestDiffItem(
                kind="mismatched",
                page_path=page_path,
                source_hash=source_entries[page_path],
                indexed_hash=indexed_entries[page_path],
            )
            for page_path in mismatched_paths[:limit]
        ),
        truncated=(
            len(missing_paths) > limit
            or len(extra_paths) > limit
            or len(mismatched_paths) > limit
        ),
        limit=limit,
    )


def _safe_manifest_page_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in normalized
        or any(ord(character) < 32 for character in normalized)
    ):
        return None
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdefABCDEF" for character in value)


def _extract_indexable_page(content: str) -> tuple[str, str]:
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    lines = content.split("\n")
    title = "Untitled"
    body_start = 0
    in_frontmatter = False
    frontmatter_lines: list[str] = []
    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---json":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() == "---":
                in_frontmatter = False
                body_start = i + 1
                try:
                    fm = json.loads("\n".join(frontmatter_lines))
                    if isinstance(fm, dict) and isinstance(fm.get("title"), str):
                        title = fm["title"]
                except json.JSONDecodeError:
                    pass
                continue
            frontmatter_lines.append(line)
        if not in_frontmatter and line.startswith("# "):
            if title == "Untitled":
                title = line[2:].strip()
            body_start = i + 1
            break
    return title, "\n".join(lines[body_start:])


def wiki_first_search(
    query: str,
    index: WikiQueryIndex,
    *,
    enabled: bool = False,
    limit: int = 5,
) -> tuple[list[WikiSearchResult], bool]:
    if not enabled:
        return [], False
    results = index.search(query, limit=limit)
    return results, len(results) > 0


def expand_linked_pages(
    primary_results: list[WikiSearchResult],
    page_store: WikiPageStore,
    *,
    max_linked: int = 3,
) -> list[WikiSearchResult]:
    import re

    if max_linked <= 0:
        return []
    linked_pages: dict[Path, float] = {}
    linked_sources: dict[Path, set[Path]] = {}
    primary_paths = {r.page_path for r in primary_results}

    def _candidate_paths(raw_link: str, source_path: Path) -> list[Path]:
        link_text = raw_link.strip()
        if not link_text:
            return []
        link_target = link_text.split("|", 1)[0].split("#", 1)[0].strip()
        if not link_target:
            return []
        normalized = Path(link_target)
        candidates: list[Path] = []
        if normalized.suffix.lower() != ".md":
            candidates.append(normalized.with_suffix(".md"))
        candidates.append(normalized)
        if len(normalized.parts) == 1:
            parent = source_path.parent
            for candidate in list(candidates):
                if parent != Path("."):
                    candidates.append(parent / candidate)
        unique: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate.is_absolute() or ".." in candidate.parts:
                continue
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique

    def _first_existing_link(raw_link: str, source_path: Path) -> Path | None:
        for candidate in _candidate_paths(raw_link, source_path):
            if page_store.read_page(candidate):
                return candidate
        return None

    for result in primary_results:
        content = page_store.read_page(result.page_path)
        if not content:
            continue
        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
        for link in wikilinks:
            link_path = _first_existing_link(link, result.page_path)
            if link_path is None:
                continue
            if link_path in primary_paths:
                continue
            if link_path not in linked_pages:
                linked_pages[link_path] = 0.0
                linked_sources[link_path] = set()
            linked_pages[link_path] += result.score * 0.5
            linked_sources[link_path].add(result.page_path)

    sorted_linked = sorted(
        linked_pages.items(),
        key=lambda x: (x[1], len(linked_sources.get(x[0], set())), x[0].as_posix()),
        reverse=True,
    )
    expanded: list[WikiSearchResult] = []
    for link_path, score in sorted_linked[:max_linked]:
        content = page_store.read_page(link_path)
        if content:
            lines = content.split("\n")
            title = "Untitled"
            in_frontmatter = False
            frontmatter_lines: list[str] = []
            for i, line in enumerate(lines):
                if i == 0 and line.strip() == "---json":
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    if line.strip() == "---":
                        in_frontmatter = False
                        try:
                            fm = json.loads("\n".join(frontmatter_lines))
                            if "title" in fm:
                                title = fm["title"]
                        except json.JSONDecodeError:
                            pass
                        break
                    frontmatter_lines.append(line)
            snippet = content[:100].replace("\n", " ")
            expanded.append(
                WikiSearchResult(
                    page_path=link_path,
                    title=title,
                    score=score,
                    snippet=snippet,
                    source="wiki_linked",
                )
            )
    return expanded


@dataclass(frozen=True)
class WikiQueryResult:
    wiki_hits: list[WikiSearchResult]
    linked_hits: list[WikiSearchResult]
    fallback_used: bool
    fallback_reason: str


def wiki_query_with_fallback(
    query: str,
    index: WikiQueryIndex,
    page_store: WikiPageStore,
    *,
    enabled: bool = False,
    limit: int = 5,
    expand_links: bool = True,
    max_linked: int = 3,
) -> WikiQueryResult:
    primary_results, found = wiki_first_search(query, index, enabled=enabled, limit=limit)
    if not found:
        return WikiQueryResult(
            wiki_hits=[],
            linked_hits=[],
            fallback_used=True,
            fallback_reason="no wiki hits",
        )
    linked_results: list[WikiSearchResult] = []
    if expand_links:
        linked_results = expand_linked_pages(primary_results, page_store, max_linked=max_linked)
    return WikiQueryResult(
        wiki_hits=primary_results,
        linked_hits=linked_results,
        fallback_used=False,
        fallback_reason="",
    )


@dataclass(frozen=True)
class WikiContextPack:
    query: str
    primary_pages: list[str]
    linked_pages: list[str]
    total_tokens: int
    truncated: bool
    omitted_pages: list[str] | None = None
    max_tokens: int = 0


@dataclass(frozen=True)
class WikiQueryTrace:
    query: str
    enabled: bool
    fts_hits: int
    linked_hits: int
    fallback_used: bool
    fallback_reason: str
    total_pages: int
    context_tokens: int
    context_max_tokens: int
    context_truncated: bool
    omitted_pages: list[str]


def _strip_frontmatter(content: str) -> str:
    lines = content.split("\n")
    if lines and lines[0].strip() == "---json":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1 :])
    return content


def _strip_runtime_markers(content: str) -> str:
    lines: list[str] = []
    for line in str(content or "").splitlines():
        if line.strip() in {AUTO_START, AUTO_END}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _bounded_ref_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return normalized, False
    return normalized[:max_chars].rstrip(), True


def build_knowledge_refs(
    results: list[WikiSearchResult],
    page_store: WikiPageStore,
    *,
    max_chars: int = 1200,
    max_summary_chars: int = 300,
) -> list[WikiKnowledgeRef]:
    """Project wiki search results into bounded knowledge refs.

    Args:
        results: Ranked wiki search results from FTS or linked-page expansion.
        page_store: Store used to resolve generated wiki Markdown pages.
        max_chars: Maximum body characters embedded in each ref payload.
        max_summary_chars: Maximum summary characters used in evidence packs.

    Returns:
        Wiki refs with stable page resource ids, hash-derived chunk ids,
        source/content hashes, and span bounds into the normalized page body.
    """

    if not isinstance(results, list):
        raise TypeError("results must be a list")
    if not isinstance(page_store, WikiPageStore):
        raise TypeError("page_store must be a WikiPageStore")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if max_summary_chars <= 0:
        raise ValueError("max_summary_chars must be positive")

    refs: list[WikiKnowledgeRef] = []
    for rank, result in enumerate(results, start=1):
        if not isinstance(result, WikiSearchResult):
            raise TypeError(f"results[{rank - 1}] must be a WikiSearchResult")
        raw_content = page_store.read_page(result.page_path)
        if raw_content is None:
            continue
        body = _strip_runtime_markers(_strip_frontmatter(str(raw_content)))
        if not body:
            continue
        content, truncated = _bounded_ref_text(body, max_chars=max_chars)
        summary_source = result.snippet.strip() or content
        summary, _ = _bounded_ref_text(summary_source, max_chars=max_summary_chars)
        source_hash = hashlib.sha256(str(raw_content).encode("utf-8")).hexdigest()
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        page_path = result.page_path.as_posix()
        legacy_chunk = derive_chunk_id(source_hash, 0)
        ref_id = f"wiki:{page_path}"
        refs.append(
            WikiKnowledgeRef(
                schema_version="scholar-ai-wiki-knowledge-ref/v1",
                ref_id=ref_id,
                chunk_id=f"{ref_id}#{legacy_chunk}",
                title=result.title,
                source_type="wiki",
                source=result.source,
                source_path=page_path,
                page_path=page_path,
                source_hash=source_hash,
                content_hash=content_hash,
                span_start=0,
                span_end=len(body),
                content=content,
                summary=summary or content[:max_summary_chars],
                read_endpoint=f"/api/agent-bridge/resource/{ref_id}",
                score=float(result.score),
                rank=rank,
                truncated=truncated,
            )
        )
    return refs


def _fit_context_text(
    target: list[str],
    text: str,
    *,
    total_chars: int,
    max_chars: int,
) -> tuple[int, bool]:
    if not text:
        return total_chars, False
    remaining = max_chars - total_chars
    if remaining <= 0:
        return total_chars, False
    if len(text) <= remaining:
        target.append(text)
        return total_chars + len(text), True
    if remaining >= 80:
        target.append(text[: max(0, remaining - 24)].rstrip() + "\n\n...[truncated]")
        return max_chars, True
    return total_chars, False


def render_context_pack(
    query: str,
    query_result: WikiQueryResult,
    page_store: WikiPageStore,
    *,
    max_tokens: int = 4000,
    tokens_per_char: float = 0.25,
) -> WikiContextPack:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query cannot be empty")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if tokens_per_char <= 0:
        raise ValueError("tokens_per_char must be positive")
    primary_pages: list[str] = []
    linked_pages: list[str] = []
    omitted_pages: list[str] = []
    total_chars = 0
    max_chars = int(max_tokens / tokens_per_char)
    truncated = False

    for result in query_result.wiki_hits:
        content = page_store.read_page(result.page_path)
        if not content:
            omitted_pages.append(result.page_path.as_posix())
            continue
        body = _strip_frontmatter(content)
        header = f"## {result.title}\n\nSource: {result.page_path.as_posix()}\nScore: {result.score:.4f}\n\n"
        page_text = header + body
        next_total, included = _fit_context_text(
            primary_pages,
            page_text,
            total_chars=total_chars,
            max_chars=max_chars,
        )
        if not included:
            truncated = True
            omitted_pages.append(result.page_path.as_posix())
            break
        total_chars = next_total
        if total_chars >= max_chars and len(page_text) > max_chars:
            truncated = True
            omitted_pages.extend(
                hit.page_path.as_posix()
                for hit in query_result.wiki_hits
                if hit.page_path != result.page_path
            )
            break

    for result in query_result.linked_hits:
        if total_chars >= max_chars:
            truncated = True
            omitted_pages.append(result.page_path.as_posix())
            break
        content = page_store.read_page(result.page_path)
        if not content:
            omitted_pages.append(result.page_path.as_posix())
            continue
        body = _strip_frontmatter(content)
        header = f"### {result.title} (linked)\n\nSource: {result.page_path.as_posix()}\nScore: {result.score:.4f}\n\n"
        page_text = header + body
        next_total, included = _fit_context_text(
            linked_pages,
            page_text,
            total_chars=total_chars,
            max_chars=max_chars,
        )
        if not included:
            truncated = True
            omitted_pages.append(result.page_path.as_posix())
            break
        total_chars = next_total

    return WikiContextPack(
        query=query,
        primary_pages=primary_pages,
        linked_pages=linked_pages,
        omitted_pages=omitted_pages,
        total_tokens=int(total_chars * tokens_per_char),
        truncated=truncated,
        max_tokens=max_tokens,
    )


def build_query_trace(
    query: str,
    query_result: WikiQueryResult,
    context_pack: WikiContextPack | None = None,
    *,
    enabled: bool = False,
) -> WikiQueryTrace:
    return WikiQueryTrace(
        query=query,
        enabled=enabled,
        fts_hits=len(query_result.wiki_hits),
        linked_hits=len(query_result.linked_hits),
        fallback_used=query_result.fallback_used,
        fallback_reason=query_result.fallback_reason,
        total_pages=len(query_result.wiki_hits) + len(query_result.linked_hits),
        context_tokens=context_pack.total_tokens if context_pack else 0,
        context_max_tokens=context_pack.max_tokens if context_pack else 0,
        context_truncated=context_pack.truncated if context_pack else False,
        omitted_pages=list(context_pack.omitted_pages or []) if context_pack else [],
    )


def write_query_trace(trace: WikiQueryTrace, *, trace_dir: Path | None = None) -> Path:
    """Persist a sanitized wiki query trace under workspace runtime artifacts."""

    if not isinstance(trace, WikiQueryTrace):
        raise TypeError("trace must be a WikiQueryTrace")
    target_dir = ensure_directory(trace_dir or wiki_trace_path())
    digest = hashlib.sha256(trace.query.encode("utf-8")).hexdigest()[:12]
    target = target_dir / f"wiki-query-{digest}.json"
    payload = {
        "query_hash": digest,
        "enabled": trace.enabled,
        "fts_hits": trace.fts_hits,
        "linked_hits": trace.linked_hits,
        "fallback_used": trace.fallback_used,
        "fallback_reason": trace.fallback_reason,
        "total_pages": trace.total_pages,
        "context_tokens": trace.context_tokens,
        "context_max_tokens": trace.context_max_tokens,
        "context_truncated": trace.context_truncated,
        "omitted_pages": trace.omitted_pages,
    }
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return target


@dataclass(frozen=True)
class ExplorationSaveResult:
    """Result of saving an exploration page (LMWR-353)."""

    success: bool
    relative_path: Path | None
    content_hash: str | None
    error: str | None = None


def save_exploration(
    query: str,
    answer: str,
    evidence_refs: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    page_store: WikiPageStore,
    *,
    source_ids: tuple[str, ...] = (),
) -> ExplorationSaveResult:
    """Save query answer as exploration page (LMWR-353).

    Generates exploration page with:
      - kind=exploration
      - status=draft (requires citation validation before finalization per LMWR-357)
      - frontmatter with id, kind, title, status
      - body with question, answer, and evidence section

    Args:
        query: Query question
        answer: Answer text
        evidence_refs: List of evidence reference dicts
        page_store: WikiPageStore instance for atomic write
        source_ids: Optional tuple of source IDs for frontmatter

    Returns:
        ExplorationSaveResult with success flag, path, and hash or error.

    Raises:
        ValueError: If query/answer empty or no evidence refs.
    """
    try:
        # Coerce and validate evidence refs
        refs = coerce_evidence_refs(evidence_refs)

        # Build body using synthesis pattern
        body = build_synthesis_body(query, answer, refs)

        # Generate stable slug from query
        slug = stable_slug(query)

        # Build page ID and relative path
        page_id = f"{WikiPageKind.exploration.value}/{slug}"
        relative_path = Path(WikiPageKind.exploration.value) / f"{slug}.md"

        # Build frontmatter
        frontmatter = {
            "id": page_id,
            "kind": WikiPageKind.exploration.value,
            "title": query.strip(),
            "status": WikiPageStatus.draft.value,
        }
        if source_ids:
            frontmatter["source_ids"] = list(source_ids)

        # Render page (atomic write pattern from Blueprint C)
        rendered = render_page(relative_path, frontmatter, body)

        # Write atomically
        page_store.write_rendered(rendered, allow_overwrite=True)

        return ExplorationSaveResult(
            success=True,
            relative_path=relative_path,
            content_hash=rendered.content_hash,
        )

    except (ValueError, TypeError) as e:
        return ExplorationSaveResult(
            success=False,
            relative_path=None,
            content_hash=None,
            error=str(e),
        )
    except Exception as e:
        return ExplorationSaveResult(
            success=False,
            relative_path=None,
            content_hash=None,
            error=f"Unexpected error: {str(e)}",
        )

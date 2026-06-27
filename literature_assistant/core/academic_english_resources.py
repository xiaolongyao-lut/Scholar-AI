"""Bounded runtime access to generated academic-English knowledge artifacts."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - package import path used by the running app.
    from literature_assistant.core.project_paths import output_path
except ImportError:  # pragma: no cover - flat import path used by legacy tests.
    from project_paths import output_path


SCHEMA_VERSION = "scholar-ai-academic-english-runtime/v1"
MAX_QUERY_CHARS = 500
MAX_SUMMARY_CHARS = 500
MAX_CONTENT_CHARS = 50000
ALLOWED_ARTIFACTS = {
    "manifest": "manifest.json",
    "chunks_jsonl": "chunks.jsonl",
    "phrases_jsonl": "phrases.jsonl",
    "discourse_frames_json": "discourse_frames.json",
    "academic_english_habits_json": "academic_english_habits.json",
    "sqlite": "academic_english_discourse.sqlite3",
    "report": "build_report.md",
}


@dataclass(frozen=True)
class AcademicEnglishSearchHit:
    """One bounded academic-English retrieval ref."""

    ref_id: str
    resource_kind: str
    title: str
    summary: str
    score: float | None
    rank: int
    metadata: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-safe payload for HTTP and MCP callers."""

        return {
            "schema_version": SCHEMA_VERSION,
            "ref_id": self.ref_id,
            "kind": "academic_english",
            "resource_kind": self.resource_kind,
            "title": self.title,
            "summary": self.summary,
            "score": self.score,
            "rank": self.rank,
            "read_endpoint": f"/api/agent-bridge/resource/{self.ref_id}",
            "metadata": self.metadata,
        }


def academic_english_root() -> Path:
    """Return the canonical generated academic-English artifact directory."""

    return output_path("english_discourse")


def academic_english_status() -> dict[str, Any]:
    """Return redacted status for generated academic-English artifacts."""

    root = academic_english_root()
    manifest = _read_json_object(root / ALLOWED_ARTIFACTS["manifest"])
    artifacts = _artifact_status(root, manifest)
    knowledge_sources = _redacted_knowledge_sources(manifest, root)
    return {
        "schema_version": SCHEMA_VERSION,
        "available": root.exists() and root.is_dir(),
        "manifest_loaded": bool(manifest),
        "builder_version": str(manifest.get("builder_version") or "") if manifest else "",
        "built_at": str(manifest.get("built_at") or "") if manifest else "",
        "counts": _safe_mapping(manifest.get("counts") if manifest else {}),
        "warnings": _safe_string_list(manifest.get("warnings") if manifest else []),
        "errors": _safe_string_list(manifest.get("errors") if manifest else []),
        "knowledge_sources": knowledge_sources,
        "artifacts": artifacts,
    }


def search_academic_english(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Search generated academic-English knowledge and return bounded refs."""

    normalized_query = _require_query(query)
    limit = _require_limit(top_k)
    root = academic_english_root()
    manifest = _read_json_object(root / ALLOWED_ARTIFACTS["manifest"])
    hits = _search_sqlite(root, normalized_query, limit=limit)
    if not hits:
        hits = _search_jsonl(root, normalized_query, limit=limit)
    if not hits:
        hits = _search_habits(root, normalized_query, limit=limit)
    manifest_meta = _manifest_ref_metadata(manifest)
    payloads: list[dict[str, Any]] = []
    for rank, hit in enumerate(hits[:limit], start=1):
        payload = hit.to_payload()
        payload["rank"] = rank
        payload["metadata"] = {**manifest_meta, **dict(payload.get("metadata") or {})}
        payloads.append(payload)
    return payloads


def read_academic_english_resource(raw_ref: str) -> dict[str, Any]:
    """Resolve one academic-English ref into an unpaginated resource body."""

    resource_kind, item_id = _split_academic_ref(raw_ref)
    root = academic_english_root()
    manifest = _read_json_object(root / ALLOWED_ARTIFACTS["manifest"])
    manifest_meta = _manifest_ref_metadata(manifest)
    if resource_kind == "habits":
        return _habits_resource(root, manifest_meta)
    if resource_kind == "chunk":
        record = _find_sqlite_record(root, resource_kind, item_id) or _find_jsonl_record(
            root / ALLOWED_ARTIFACTS["chunks_jsonl"],
            "chunk_id",
            item_id,
        )
        if record is None:
            raise KeyError(f"academic-English chunk not found: {item_id}")
        return _record_resource("chunk", item_id, record, manifest_meta)
    if resource_kind == "phrase":
        record = _find_sqlite_record(root, resource_kind, item_id) or _find_jsonl_record(
            root / ALLOWED_ARTIFACTS["phrases_jsonl"],
            "phrase_id",
            item_id,
        )
        if record is None:
            raise KeyError(f"academic-English phrase not found: {item_id}")
        return _record_resource("phrase", item_id, record, manifest_meta)
    raise KeyError(f"unsupported academic-English resource kind: {resource_kind}")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def _artifact_status(root: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_artifacts = manifest.get("output_artifacts") if isinstance(manifest, Mapping) else {}
    artifacts: dict[str, dict[str, Any]] = {}
    for key, filename in ALLOWED_ARTIFACTS.items():
        raw = manifest_artifacts.get(key) if isinstance(manifest_artifacts, Mapping) else None
        has_manifest_record = isinstance(raw, Mapping) and any(
            field in raw for field in ("exists", "bytes", "sha256", "status", "rows")
        )
        artifact_path = root / filename
        artifacts[key] = {
            "relative_path": f"english_discourse/{filename}",
            "exists": bool(raw.get("exists")) if has_manifest_record else artifact_path.exists(),
            "bytes": _safe_int(raw.get("bytes")) if has_manifest_record else _file_size(artifact_path),
            "sha256": _safe_hash(raw.get("sha256")) if has_manifest_record else _sha256_file(artifact_path),
            "status": _safe_status(raw.get("status")) if has_manifest_record else _derived_status(artifact_path),
        }
        if has_manifest_record and "rows" in raw:
            artifacts[key]["rows"] = _safe_int(raw.get("rows"))
    return artifacts


def _redacted_knowledge_sources(manifest: Mapping[str, Any], root: Path | None = None) -> dict[str, dict[str, Any]]:
    raw_sources = manifest.get("knowledge_sources") if isinstance(manifest, Mapping) else {}
    redacted: dict[str, dict[str, Any]] = {}
    if isinstance(raw_sources, Mapping):
        for key, value in raw_sources.items():
            if not isinstance(value, Mapping):
                continue
            redacted[str(key)] = {
                "source_ref": _safe_source_ref(value),
                "source_label": str(value.get("source_label") or ""),
                "loaded": bool(value.get("loaded", False)),
                "load_status": _safe_status(value.get("load_status")),
                "content_hash": _safe_hash(value.get("content_hash")),
                "char_count": _safe_int(value.get("char_count")),
            }
    if "academic_english_habits" not in redacted:
        fallback = _habits_source_fallback(academic_english_root() if root is None else root)
        if fallback:
            redacted["academic_english_habits"] = fallback
    return redacted


def _habits_source_fallback(root: Path) -> dict[str, Any]:
    """Return source provenance for legacy builds that predate manifest knowledge_sources."""

    habits = _read_json_object(root / ALLOWED_ARTIFACTS["academic_english_habits_json"])
    if not habits:
        return {}
    policy_markdown = str(habits.get("policy_markdown") or "")
    policy_hash = _safe_hash(habits.get("policy_content_hash")) or (
        _sha256_text(policy_markdown) if policy_markdown else ""
    )
    loaded = bool(habits.get("policy_loaded", False)) or bool(policy_markdown)
    load_status = _safe_status(habits.get("policy_load_status"))
    if loaded and load_status == "missing":
        load_status = "loaded"
    return {
        "source_ref": _safe_source_ref(habits),
        "source_label": str(habits.get("policy_source") or ""),
        "loaded": loaded,
        "load_status": load_status,
        "content_hash": policy_hash,
        "char_count": _safe_int(habits.get("policy_char_count")) or len(policy_markdown),
    }


def _manifest_ref_metadata(manifest: Mapping[str, Any]) -> dict[str, Any]:
    root = academic_english_root()
    artifacts = _artifact_status(root, manifest)
    habits_source = _redacted_knowledge_sources(manifest, root).get("academic_english_habits", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "builder_version": str(manifest.get("builder_version") or "") if isinstance(manifest, Mapping) else "",
        "built_at": str(manifest.get("built_at") or "") if isinstance(manifest, Mapping) else "",
        "policy_content_hash": str(habits_source.get("content_hash") or ""),
        "policy_loaded": bool(habits_source.get("loaded", False)),
        "artifact_hashes": {
            key: value["sha256"]
            for key, value in artifacts.items()
            if isinstance(value, Mapping) and str(value.get("sha256") or "")
        },
    }


def _search_sqlite(root: Path, query: str, *, limit: int) -> list[AcademicEnglishSearchHit]:
    db_path = root / ALLOWED_ARTIFACTS["sqlite"]
    fts_query = _fts_query(query)
    if not fts_query or not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            names = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('chunks_fts', 'phrases_fts')"
                )
            }
            hits: list[AcademicEnglishSearchHit] = []
            if "chunks_fts" in names:
                if _sqlite_has_columns(conn, "chunks", ("source_path", "source_hash", "content_hash", "span_start", "span_end")):
                    rows = conn.execute(
                        """
                        SELECT
                            c.chunk_id, c.source_id, c.source_type, c.source_path, c.source_hash,
                            c.title, c.locator, c.section, c.text, c.summary, c.content_hash,
                            c.span_start, c.span_end, c.rhetorical_moves, c.features, c.keywords,
                            bm25(chunks_fts) AS score
                        FROM chunks_fts
                        JOIN chunks AS c ON c.rowid = chunks_fts.rowid
                        WHERE chunks_fts MATCH ?
                        ORDER BY bm25(chunks_fts)
                        LIMIT ?
                        """,
                        (fts_query, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT chunk_id, title, section, text, summary, bm25(chunks_fts) AS score
                        FROM chunks_fts
                        WHERE chunks_fts MATCH ?
                        ORDER BY bm25(chunks_fts)
                        LIMIT ?
                        """,
                        (fts_query, limit),
                    ).fetchall()
                hits.extend(_chunk_hit(dict(row), score=float(row["score"])) for row in rows)
            remaining = max(0, limit - len(hits))
            if remaining and "phrases_fts" in names:
                if _sqlite_has_columns(conn, "phrases", ("source_path", "source_hash", "content_hash", "span_start", "span_end")):
                    rows = conn.execute(
                        """
                        SELECT
                            p.phrase_id, p.source_id, p.source_type, p.source_path, p.source_hash,
                            p.text, p.normalized, p.content_hash, p.span_start, p.span_end,
                            p.move, p.features, p.section, p.locator, p.adaptation_note,
                            bm25(phrases_fts) AS score
                        FROM phrases_fts
                        JOIN phrases AS p ON p.rowid = phrases_fts.rowid
                        WHERE phrases_fts MATCH ?
                        ORDER BY bm25(phrases_fts)
                        LIMIT ?
                        """,
                        (fts_query, remaining),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT phrase_id, text, normalized, move, section, adaptation_note, bm25(phrases_fts) AS score
                        FROM phrases_fts
                        WHERE phrases_fts MATCH ?
                        ORDER BY bm25(phrases_fts)
                        LIMIT ?
                        """,
                        (fts_query, remaining),
                    ).fetchall()
                hits.extend(_phrase_hit(dict(row), score=float(row["score"])) for row in rows)
            return hits[:limit]
    except sqlite3.Error:
        return []


def _search_jsonl(root: Path, query: str, *, limit: int) -> list[AcademicEnglishSearchHit]:
    hits: list[tuple[float, AcademicEnglishSearchHit]] = []
    for record in _iter_jsonl(root / ALLOWED_ARTIFACTS["chunks_jsonl"]):
        score = _record_score(record, query, ("title", "section", "text", "summary", "keywords"))
        if score > 0:
            hits.append((score, _chunk_hit(record, score=score)))
    for record in _iter_jsonl(root / ALLOWED_ARTIFACTS["phrases_jsonl"]):
        score = _record_score(record, query, ("text", "normalized", "move", "section", "adaptation_note"))
        if score > 0:
            hits.append((score, _phrase_hit(record, score=score)))
    hits.sort(key=lambda item: item[0], reverse=True)
    return [hit for _, hit in hits[:limit]]


def _search_habits(root: Path, query: str, *, limit: int) -> list[AcademicEnglishSearchHit]:
    if limit <= 0:
        return []
    habits = _read_json_object(root / ALLOWED_ARTIFACTS["academic_english_habits_json"])
    if not habits:
        return []
    score = _record_score(habits, query, ("policy_markdown", "purpose", "knowledge_type"))
    if score <= 0:
        return []
    summary = _bounded_text(str(habits.get("purpose") or "Academic English discourse habits."))
    return [
        AcademicEnglishSearchHit(
            ref_id="academic_english:habits",
            resource_kind="habits",
            title="Academic English Discourse Habits",
            summary=summary,
            score=score,
            rank=1,
            metadata={
                "knowledge_ref_schema_version": "scholar-ai-academic-english-knowledge-ref/v1",
                "source": "academic_english",
                "source_id": "academic_english_habits",
                "source_type": "markdown_policy",
                "source_path": _safe_source_ref(habits),
                "source_hash": _safe_hash(habits.get("policy_content_hash")),
                "content_hash": _safe_hash(habits.get("policy_content_hash"))
                or _sha256_text(str(habits.get("policy_markdown") or "")),
                "span_start": 0,
                "span_end": _safe_int(habits.get("policy_char_count")),
                "resource_kind": "habits",
            },
        )
    ]


def _find_sqlite_record(root: Path, resource_kind: str, item_id: str) -> dict[str, Any] | None:
    db_path = root / ALLOWED_ARTIFACTS["sqlite"]
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            table_names = {
                str(row["name"])
                for row in conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name IN ('chunks', 'phrases', 'chunks_fts', 'phrases_fts')
                    """
                )
            }
            if resource_kind == "chunk":
                if "chunks" in table_names:
                    if _sqlite_has_columns(
                        conn,
                        "chunks",
                        ("source_path", "source_hash", "content_hash", "span_start", "span_end"),
                    ):
                        row = conn.execute(
                            """
                            SELECT chunk_id, source_id, source_type, source_path, source_hash, title, locator,
                                   section, text, summary, content_hash, span_start, span_end,
                                   rhetorical_moves, features, keywords, char_count, word_count
                            FROM chunks
                            WHERE chunk_id = ?
                            """,
                            (item_id,),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            """
                            SELECT chunk_id, source_id, source_type, title, locator, section, text, summary,
                                   rhetorical_moves, features, keywords, char_count, word_count
                            FROM chunks
                            WHERE chunk_id = ?
                            """,
                            (item_id,),
                        ).fetchone()
                elif "chunks_fts" in table_names:
                    row = conn.execute(
                        """
                        SELECT chunk_id, title, section, text, summary, keywords
                        FROM chunks_fts
                        WHERE chunk_id = ?
                        """,
                        (item_id,),
                    ).fetchone()
                else:
                    row = None
            elif resource_kind == "phrase":
                if "phrases" in table_names:
                    if _sqlite_has_columns(
                        conn,
                        "phrases",
                        ("source_path", "source_hash", "content_hash", "span_start", "span_end"),
                    ):
                        row = conn.execute(
                            """
                            SELECT phrase_id, source_id, source_type, source_path, source_hash,
                                   text, normalized, content_hash, span_start, span_end, move, features,
                                   section, locator, adaptation_note
                            FROM phrases
                            WHERE phrase_id = ?
                            """,
                            (item_id,),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            """
                            SELECT phrase_id, source_id, source_type, text, normalized, move, features,
                                   section, locator, adaptation_note
                            FROM phrases
                            WHERE phrase_id = ?
                            """,
                            (item_id,),
                        ).fetchone()
                elif "phrases_fts" in table_names:
                    row = conn.execute(
                        """
                        SELECT phrase_id, text, normalized, move, section, adaptation_note
                        FROM phrases_fts
                        WHERE phrase_id = ?
                        """,
                        (item_id,),
                    ).fetchone()
                else:
                    row = None
            else:
                return None
            return dict(row) if row is not None else None
    except sqlite3.Error:
        return None


def _find_jsonl_record(path: Path, id_key: str, item_id: str) -> dict[str, Any] | None:
    for record in _iter_jsonl(path):
        if str(record.get(id_key) or "") == item_id:
            return record
    return None


def _sqlite_has_columns(conn: sqlite3.Connection, table_name: str, required_columns: tuple[str, ...]) -> bool:
    if not required_columns:
        return True
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return False
    existing = {str(row[1]) for row in rows if len(row) > 1}
    return all(column in existing for column in required_columns)


def _record_ref_metadata(
    resource_kind: str,
    item_id: str,
    record: Mapping[str, Any],
    *,
    content: str,
) -> dict[str, Any]:
    source_id = str(record.get("source_id") or "").strip()
    source_type = str(record.get("source_type") or "").strip()[:80]
    source_path = _safe_record_source_path(record)
    span_start, span_end = _record_span(record, default_end=len(content))
    metadata: dict[str, Any] = {
        "knowledge_ref_schema_version": "scholar-ai-academic-english-knowledge-ref/v1",
        "source": "academic_english",
        "source_id": source_id,
        "source_type": source_type,
        "source_path": source_path,
        "source_hash": _safe_hash(record.get("source_hash")),
        "content_hash": _safe_hash(record.get("content_hash")) or _sha256_text(content),
        "span_start": span_start,
        "span_end": span_end,
        "resource_kind": resource_kind,
    }
    if resource_kind == "chunk":
        metadata["chunk_id"] = item_id
    elif resource_kind == "phrase":
        metadata["phrase_id"] = item_id
    return {key: value for key, value in metadata.items() if value not in ("", None, {})}


def _chunk_hit(record: Mapping[str, Any], *, score: float | None) -> AcademicEnglishSearchHit:
    chunk_id = _require_record_id(record, "chunk_id")
    title = _bounded_text(str(record.get("title") or record.get("section") or "Academic English chunk"), limit=200)
    text = str(record.get("summary") or record.get("text") or "")
    metadata = _record_ref_metadata("chunk", chunk_id, record, content=text)
    metadata["section"] = str(record.get("section") or "")[:200]
    return AcademicEnglishSearchHit(
        ref_id=f"academic_english:chunk:{chunk_id}",
        resource_kind="chunk",
        title=title,
        summary=_bounded_text(text),
        score=score,
        rank=0,
        metadata=metadata,
    )


def _phrase_hit(record: Mapping[str, Any], *, score: float | None) -> AcademicEnglishSearchHit:
    phrase_id = _require_record_id(record, "phrase_id")
    text = str(record.get("text") or record.get("normalized") or "")
    title = f"Academic English phrase: {str(record.get('move') or 'move')[:80]}"
    metadata = _record_ref_metadata("phrase", phrase_id, record, content=text)
    metadata["move"] = str(record.get("move") or "")[:120]
    metadata["section"] = str(record.get("section") or "")[:200]
    return AcademicEnglishSearchHit(
        ref_id=f"academic_english:phrase:{phrase_id}",
        resource_kind="phrase",
        title=title,
        summary=_bounded_text(text),
        score=score,
        rank=0,
        metadata=metadata,
    )


def _habits_resource(root: Path, manifest_meta: Mapping[str, Any]) -> dict[str, Any]:
    habits = _read_json_object(root / ALLOWED_ARTIFACTS["academic_english_habits_json"])
    if not habits:
        raise KeyError("academic-English habits artifact is missing")
    content = _habits_resource_content(habits)
    ref_id = "academic_english:habits"
    return {
        "kind": "academic_english",
        "project_id": None,
        "title": "Academic English Discourse Habits",
        "content": _bounded_resource_content(content),
        "metadata": {
            **dict(manifest_meta),
            "ref_id": ref_id,
            "read_endpoint": f"/api/agent-bridge/resource/{ref_id}",
            "knowledge_ref_schema_version": "scholar-ai-academic-english-knowledge-ref/v1",
            "source": "academic_english",
            "source_id": "academic_english_habits",
            "source_type": "markdown_policy",
            "source_path": _safe_source_ref(habits),
            "source_hash": _safe_hash(habits.get("policy_content_hash")),
            "content_hash": _safe_hash(habits.get("policy_content_hash")) or _sha256_text(content),
            "span_start": 0,
            "span_end": _safe_int(habits.get("policy_char_count")) or len(content),
            "resource_kind": "habits",
            "policy_loaded": bool(habits.get("policy_loaded", False)),
            "policy_content_hash": str(habits.get("policy_content_hash") or ""),
        },
    }


def _habits_resource_content(habits: Mapping[str, Any]) -> str:
    """Return policy-first content so bounded context loads the matched source text."""

    policy_markdown = str(habits.get("policy_markdown") or "").strip()
    metadata = dict(habits)
    metadata.pop("policy_markdown", None)
    metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True)
    if policy_markdown:
        return f"{policy_markdown}\n\n---\n\n{metadata_json}"
    return metadata_json


def _record_resource(
    resource_kind: str,
    item_id: str,
    record: Mapping[str, Any],
    manifest_meta: Mapping[str, Any],
) -> dict[str, Any]:
    if resource_kind == "chunk":
        content = str(record.get("text") or record.get("summary") or "")
        title = str(record.get("title") or record.get("section") or item_id)
    else:
        content = str(record.get("text") or record.get("normalized") or "")
        title = f"Academic English phrase: {str(record.get('move') or item_id)}"
    if not content.strip():
        raise KeyError(f"academic-English {resource_kind} has no readable content: {item_id}")
    metadata = {
        **dict(manifest_meta),
        **_record_ref_metadata(resource_kind, item_id, record, content=content),
        "section": str(record.get("section") or "")[:200],
    }
    ref_id = f"academic_english:{resource_kind}:{item_id}"
    metadata["ref_id"] = ref_id
    metadata["read_endpoint"] = f"/api/agent-bridge/resource/{ref_id}"
    if resource_kind == "phrase":
        metadata["move"] = str(record.get("move") or "")[:120]
    return {
        "kind": "academic_english",
        "project_id": None,
        "title": _bounded_text(title, limit=300),
        "content": _bounded_resource_content(content),
        "metadata": {key: value for key, value in metadata.items() if value not in ("", None, {})},
    }


def _split_academic_ref(raw_ref: str) -> tuple[str, str]:
    normalized = str(raw_ref or "").strip()
    if normalized == "habits":
        return "habits", "habits"
    if ":" not in normalized:
        raise KeyError("academic-English refs must be habits, chunk:<id>, or phrase:<id>")
    resource_kind, item_id = normalized.split(":", 1)
    resource_kind = resource_kind.strip().lower()
    item_id = item_id.strip()
    if resource_kind not in {"chunk", "phrase"}:
        raise KeyError(f"unsupported academic-English resource kind: {resource_kind}")
    if not item_id or len(item_id) > 180 or any(ord(char) < 32 for char in item_id):
        raise KeyError("academic-English resource id is invalid")
    return resource_kind, item_id


def _require_query(query: str) -> str:
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    if len(normalized) > MAX_QUERY_CHARS:
        raise ValueError("query is too long")
    return normalized


def _require_limit(top_k: int) -> int:
    if not isinstance(top_k, int):
        raise TypeError("top_k must be an integer")
    if top_k < 1 or top_k > 50:
        raise ValueError("top_k must be between 1 and 50")
    return top_k


def _require_record_id(record: Mapping[str, Any], key: str) -> str:
    value = str(record.get(key) or "").strip()
    if not value:
        raise KeyError(f"{key} is required")
    return value[:180]


def _record_score(record: Mapping[str, Any], query: str, fields: tuple[str, ...]) -> float:
    terms = _query_terms(query)
    haystack = " ".join(_flatten_text(record.get(field)) for field in fields).lower()
    if not haystack:
        return 0.0
    if not terms:
        return 1.0 if query.lower() in haystack else 0.0
    return float(sum(haystack.count(term) for term in terms))


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return str(value or "")


def _query_terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[A-Za-z0-9_]+", query) if term.strip()]


def _fts_query(query: str) -> str:
    terms = _query_terms(query)
    return " OR ".join(terms[:12])


def _bounded_text(value: str, *, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _bounded_resource_content(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS].rstrip()


def _safe_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_source_ref(value: Mapping[str, Any]) -> str:
    raw = str(value.get("source_label") or value.get("policy_source") or value.get("source_path") or "").strip()
    if raw and not _looks_private_path(raw):
        return raw[:500]
    stem = Path(raw).name if raw else ""
    if stem:
        return f"source:{stem[:200]}"
    return "source:academic_english"


def _safe_record_source_path(record: Mapping[str, Any]) -> str:
    raw = str(record.get("source_path") or record.get("origin_path") or record.get("locator") or "").strip()
    if raw and not _looks_private_path(raw):
        return raw[:500]
    basename = Path(raw).name if raw else ""
    if basename:
        return f"source:{basename[:200]}"
    source_type = str(record.get("source_type") or "source").strip()[:80] or "source"
    source_id = str(record.get("source_id") or "").strip()[:160]
    if source_id:
        return f"{source_type}:{source_id}"
    locator_hash = _sha256_text(raw)[:16] if raw else "unknown"
    return f"{source_type}:{locator_hash}"


def _looks_private_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized):
        return True
    if normalized.startswith(("/", "~")):
        return True
    if ".." in Path(normalized).parts:
        return True
    return False


def _record_span(record: Mapping[str, Any], *, default_end: int) -> tuple[int, int]:
    start = _safe_int(record.get("span_start"))
    end = _safe_int(record.get("span_end"))
    fallback_end = max(0, default_end)
    if end <= start:
        end = start + fallback_end
    return start, end


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:500] for item in value if isinstance(item, (str, int, float))]


def _safe_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _safe_hash(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if re.fullmatch(r"[a-f0-9]{64}", text) else ""


def _safe_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"written", "loaded", "missing", "disabled", "not_file", "unloaded"}:
        return text
    return "missing"


def _derived_status(path: Path) -> str:
    if path.exists() and path.is_file():
        return "written"
    return "missing"


def _file_size(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return path.stat().st_size

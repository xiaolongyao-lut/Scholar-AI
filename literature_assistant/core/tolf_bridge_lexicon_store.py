"""Runtime store for the CJK bridge lexicon used by TOLF query expansion.

The bridge lexicon is a durable knowledge asset, not just a convenience JSON
file. This store gives it an explicit runtime contract with provenance and
bounded failure states so selector code can consume it safely.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from literature_assistant.core.project_paths import runtime_state_path
except ImportError:  # pragma: no cover - legacy flat import path
    from project_paths import runtime_state_path

_DEFAULT_LEXICON_PATH = Path(__file__).resolve().parent / "config" / "cjk_bridge_lexicon.json"
_LEXICON_SCHEMA_VERSION = "scholar-ai-cjk-bridge-lexicon/v1"
_RUNTIME_CONSUMERS: tuple[tuple[str, str], ...] = (
    ("literature_assistant.core.tolf_text_selector", "selector_query_expansion"),
    ("literature_assistant.core.routers.knowledge_router", "entry_ref_search_and_context_receipt"),
    ("literature_assistant.core.routers.agent_bridge_router", "bounded_entry_resource_read"),
    ("literature.bridge_lexicon_search", "mcp_ref_search"),
    ("literature.agent_resource_read", "mcp_bounded_entry_read"),
    ("literature.knowledge_context_receipt", "mcp_prompt_context_receipt"),
)
_REF_SCHEMA_VERSION = "scholar-ai-bridge-lexicon-knowledge-ref/v1"
_PACKAGE_ID = "bridge_lexicon"
_MAX_SEARCH_RESULTS = 50


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_entries(raw: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, list):
            continue
        entries = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in value
                    if isinstance(item, str) and str(item).strip()
                }
            )
        )
        if entries:
            normalized[key.strip()] = entries
    return dict(sorted(normalized.items(), key=lambda item: item[0]))


def _entry_content_hash(term: str, values: tuple[str, ...]) -> str:
    payload = json.dumps(
        {"term": term, "values": list(values)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(payload)


def _entry_id(term: str, values: tuple[str, ...]) -> str:
    ascii_hint = re.sub(r"[^a-z0-9]+", "-", " ".join(values).lower()).strip("-")
    prefix = ascii_hint[:40].strip("-") or "entry"
    return f"{prefix}-{_entry_content_hash(term, values)[:16]}"


def _entry_ref_id(entry_id: str) -> str:
    return f"{_PACKAGE_ID}:entry:{entry_id}"


def _entry_read_endpoint(entry_id: str) -> str:
    return f"/api/agent-bridge/resource/{_entry_ref_id(entry_id)}"


def _entry_text(term: str, values: tuple[str, ...]) -> str:
    lines = [
        "Bridge Lexicon Entry",
        f"Term: {term}",
        "Bridge terms:",
    ]
    lines.extend(f"- {value}" for value in values)
    return "\n".join(lines)


def _query_terms(query: str) -> list[str]:
    return [
        token
        for token in re.split(r"\s+", str(query or "").strip().lower())
        if token
    ]


def _entry_score(term: str, values: tuple[str, ...], terms: list[str], query: str) -> int:
    haystack = " ".join([term, *values]).lower()
    score = 0
    if query and query.lower() in haystack:
        score += 4
    for token in terms:
        if token in haystack:
            score += 2
    return score


@dataclass(frozen=True, slots=True)
class BridgeLexiconSnapshot:
    """One immutable view of the loaded bridge lexicon."""

    source_path: str
    source_hash: str
    content_hash: str
    loaded: bool
    load_status: str
    entry_count: int
    updated_at: str
    schema_version: str
    runtime_consumers: tuple[tuple[str, str], ...]
    entries: dict[str, tuple[str, ...]]

    def to_status_payload(self) -> dict[str, Any]:
        """Return a redacted status payload for runtime consumers."""

        return {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "source_hash": self.source_hash,
            "content_hash": self.content_hash,
            "loaded": self.loaded,
            "load_status": self.load_status,
            "entry_count": self.entry_count,
            "updated_at": self.updated_at,
            "runtime_consumers": [
                {"consumer": consumer, "usage": usage}
                for consumer, usage in self.runtime_consumers
            ],
        }


class BridgeLexiconStore:
    """Load and cache the runtime CJK bridge lexicon with provenance."""

    __slots__ = ("_lexicon_path", "_status_path")

    def __init__(self, lexicon_path: str | Path | None = None) -> None:
        self._lexicon_path = Path(lexicon_path).expanduser().resolve() if lexicon_path else _DEFAULT_LEXICON_PATH.resolve()
        self._status_path = runtime_state_path("tolf_bridge_lexicon_status.json")

    @property
    def path(self) -> Path:
        return self._lexicon_path

    @property
    def status_path(self) -> Path:
        return self._status_path

    def load(self) -> BridgeLexiconSnapshot:
        """Load the lexicon and persist a small status record."""

        raw_text = ""
        load_status = "missing"
        entries: dict[str, tuple[str, ...]] = {}
        source_hash = ""
        content_hash = ""
        if self._lexicon_path.exists() and self._lexicon_path.is_file():
            try:
                raw_text = self._lexicon_path.read_text(encoding="utf-8")
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    entries = _normalize_entries(parsed)
                    source_hash = _sha256_text(raw_text)
                    content_hash = _sha256_text(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                    load_status = "loaded"
                else:
                    load_status = "invalid_schema"
            except json.JSONDecodeError:
                load_status = "invalid_json"
            except OSError:
                load_status = "unreadable"
        snapshot = BridgeLexiconSnapshot(
            source_path=str(self._lexicon_path),
            source_hash=source_hash,
            content_hash=content_hash,
            loaded=load_status == "loaded",
            load_status=load_status,
            entry_count=len(entries),
            updated_at=_now_iso(),
            schema_version=_LEXICON_SCHEMA_VERSION,
            runtime_consumers=_RUNTIME_CONSUMERS,
            entries=entries,
        )
        self._write_status(snapshot)
        return snapshot

    def get_snapshot(self) -> BridgeLexiconSnapshot:
        """Return the cached snapshot, loading on first access."""

        return self.load()

    def get_entries(self) -> dict[str, tuple[str, ...]]:
        """Return normalized bridge terms keyed by Chinese source term."""

        return dict(self.get_snapshot().entries)

    def search(self, query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
        """Search bridge lexicon entries and return bounded agent-readable refs."""

        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        if top_k < 1 or top_k > _MAX_SEARCH_RESULTS:
            raise ValueError(f"top_k must be between 1 and {_MAX_SEARCH_RESULTS}")
        snapshot = self.get_snapshot()
        terms = _query_terms(normalized_query)
        hits: list[tuple[int, str, tuple[str, ...]]] = []
        for term, values in snapshot.entries.items():
            score = _entry_score(term, values, terms, normalized_query)
            if score > 0:
                hits.append((score, term, values))
        hits.sort(key=lambda item: (-item[0], item[1]))
        return [
            _entry_search_hit(snapshot, term, values, score=score, rank=index)
            for index, (score, term, values) in enumerate(hits[:top_k], start=1)
        ]

    def read_resource(self, raw_ref: str) -> dict[str, Any]:
        """Resolve one ``bridge_lexicon:entry:<entry_id>`` resource ref."""

        entry_id = _parse_entry_raw_ref(raw_ref)
        snapshot = self.get_snapshot()
        for term, values in snapshot.entries.items():
            current_entry_id = _entry_id(term, values)
            if current_entry_id != entry_id:
                continue
            content = _entry_text(term, values)
            metadata = _entry_metadata(snapshot, term, values, content)
            return {
                "kind": _PACKAGE_ID,
                "project_id": None,
                "title": f"Bridge lexicon: {term}",
                "content": content,
                "metadata": metadata,
                "ref_id": metadata["ref_id"],
            }
        raise KeyError(f"Bridge lexicon entry not found: {entry_id}")

    def _write_status(self, snapshot: BridgeLexiconSnapshot) -> None:
        self._status_path.parent.mkdir(parents=True, exist_ok=True)
        payload = snapshot.to_status_payload()
        fd, tmp_name = tempfile.mkstemp(prefix=f"{self._status_path.name}.", suffix=".tmp", dir=str(self._status_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp_name).replace(self._status_path)
        except Exception:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass


_DEFAULT_STORE = BridgeLexiconStore()


def load_bridge_lexicon_store() -> BridgeLexiconStore:
    """Return the singleton bridge lexicon store."""

    return _DEFAULT_STORE


def get_bridge_lexicon_status() -> dict[str, Any]:
    """Return the current bridge lexicon status payload."""

    return load_bridge_lexicon_store().get_snapshot().to_status_payload()


def get_bridge_lexicon_entries() -> dict[str, tuple[str, ...]]:
    """Return normalized bridge terms for runtime consumers."""

    return load_bridge_lexicon_store().get_entries()


def search_bridge_lexicon(query: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Search bridge lexicon entries and return bounded resource refs."""

    return load_bridge_lexicon_store().search(query, top_k=top_k)


def read_bridge_lexicon_resource(raw_ref: str) -> dict[str, Any]:
    """Resolve one bridge-lexicon entry ref for agent-resource loading."""

    return load_bridge_lexicon_store().read_resource(raw_ref)


def _entry_metadata(
    snapshot: BridgeLexiconSnapshot,
    term: str,
    values: tuple[str, ...],
    content: str,
) -> dict[str, Any]:
    entry_id = _entry_id(term, values)
    content_hash = _sha256_text(content)
    return {
        "knowledge_ref_schema_version": _REF_SCHEMA_VERSION,
        "ref_id": _entry_ref_id(entry_id),
        "package_id": _PACKAGE_ID,
        "resource_kind": "entry",
        "entry_id": entry_id,
        "source": _PACKAGE_ID,
        "source_type": "json",
        "source_path": snapshot.source_path,
        "source_hash": snapshot.source_hash,
        "content_hash": content_hash,
        "entry_content_hash": _entry_content_hash(term, values),
        "package_content_hash": snapshot.content_hash,
        "term": term,
        "values": list(values),
        "span_start": 0,
        "span_end": len(content),
        "read_endpoint": _entry_read_endpoint(entry_id),
        "runtime_consumers": [
            {"consumer": consumer, "usage": usage}
            for consumer, usage in snapshot.runtime_consumers
        ],
    }


def _entry_search_hit(
    snapshot: BridgeLexiconSnapshot,
    term: str,
    values: tuple[str, ...],
    *,
    score: int,
    rank: int,
) -> dict[str, Any]:
    content = _entry_text(term, values)
    metadata = _entry_metadata(snapshot, term, values, content)
    return {
        "schema_version": _REF_SCHEMA_VERSION,
        "ref_id": metadata["ref_id"],
        "kind": _PACKAGE_ID,
        "resource_kind": "entry",
        "title": f"Bridge lexicon: {term}",
        "summary": f"{term}: {', '.join(values)}",
        "score": float(score),
        "rank": rank,
        "read_endpoint": metadata["read_endpoint"],
        "metadata": metadata,
    }


def _parse_entry_raw_ref(raw_ref: str) -> str:
    normalized = str(raw_ref or "").strip()
    parts = normalized.split(":")
    if len(parts) != 2 or parts[0] != "entry":
        raise ValueError("bridge_lexicon refs must use entry:<entry_id>")
    entry_id = parts[1].strip()
    if not entry_id:
        raise ValueError("entry_id must not be empty")
    if any(ord(char) < 32 for char in entry_id):
        raise ValueError("entry_id must not contain control characters")
    if "/" in entry_id or "\\" in entry_id or ".." in entry_id:
        raise ValueError("entry_id must be a stable id, not a path")
    return entry_id


__all__ = [
    "BridgeLexiconSnapshot",
    "BridgeLexiconStore",
    "get_bridge_lexicon_entries",
    "get_bridge_lexicon_status",
    "load_bridge_lexicon_store",
    "read_bridge_lexicon_resource",
    "search_bridge_lexicon",
]

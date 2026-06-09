"""Compatibility facade for the unified smart-read chat pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4
from typing import Final, Literal, NotRequired, Protocol, TypedDict, cast


LegacyChatMode = Literal["direct", "literature_qa", "inspiration"]
ProductSurface = Literal["smart_read"]
EvidenceSourceKind = Literal["local", "web", "mcp"]

UNIFIED_SMART_READ_MODE: Final[LegacyChatMode] = "literature_qa"
DISCUSSION_SESSION_SOURCE: Final[str] = "multi_agent_discussion"
LEGACY_CHAT_MODES: Final[frozenset[LegacyChatMode]] = frozenset(
    ("direct", "literature_qa", "inspiration")
)


@dataclass(frozen=True, slots=True)
class SmartReadModeDecision:
    """Resolved execution mode for the unified smart-read surface.

    Args:
        execution_mode: Internal legacy-compatible mode used by existing
            routers and persisted sessions.
        storage_mode: Mode value to persist for this turn.
        product_surface: Public product surface; new UI must stay unified.
        legacy_mode_requested: True when a caller explicitly requested a
            non-unified legacy mode or sent the old ``direct_mode`` hint.
        ignored_direct_mode_hint: True when old ``direct_mode`` was ignored so
            new writes do not split smart-read conversations.
    """

    execution_mode: LegacyChatMode
    storage_mode: LegacyChatMode
    product_surface: ProductSurface
    legacy_mode_requested: bool
    ignored_direct_mode_hint: bool


@dataclass(frozen=True, slots=True)
class SmartReadModeConflict:
    """Legacy session-mode conflict returned before any LLM work starts.

    Args:
        current_mode: Mode already attached to the persisted session.
        requested_mode: Mode requested for the next turn.
    """

    current_mode: LegacyChatMode
    requested_mode: LegacyChatMode


@dataclass(frozen=True, slots=True)
class SmartReadTurnPlan:
    """Pure request plan for one smart-read turn.

    Args:
        session_id: Normalized existing id or generated id for a new session.
        requested_existing_session: True when the client supplied a session id.
        mode_decision: Resolved legacy-compatible execution mode.
        conflict: Session-mode conflict, if the turn must stop before LLM work.
    """

    session_id: str
    requested_existing_session: bool
    mode_decision: SmartReadModeDecision
    conflict: SmartReadModeConflict | None = None


class ContextChunkLike(Protocol):
    """Minimum context chunk shape needed for SmartRead context rendering."""

    index: int
    source: str
    content: str
    relevance_score: float | None
    chunk_id: str | None
    material_id: str | None
    section_title: str | None
    source_labels: list[str]
    page: int | str | None
    source_hint: str | None


class EvidenceReferenceRecord(TypedDict):
    """Serializable evidence reference record consumed by API response models."""

    chunk_id: str
    material_id: str | None
    source: str
    text: str
    quote: str
    label: str
    score: float | None
    source_labels: list[str]
    page: int | str | None
    source_hint: str | None
    rank: int | None
    query_overlap_tokens: list[str]
    source_kind: EvidenceSourceKind
    bbox: NotRequired[list[float]]
    bbox_unit: NotRequired[str | None]


class SessionSummaryRecord(TypedDict):
    """Serializable chat session summary for history drawers."""

    session_id: str
    project_id: str | None
    title: str
    total_turns: int
    total_tokens: int
    created_at: str | None
    updated_at: str | None
    preview: str
    mode: LegacyChatMode
    legacy_mode_inferred: bool
    source: str | None
    agent_count: int | None
    synthesis_preview: str | None
    fork: dict[str, str] | None
    archived: bool
    archived_at: str | None


class AssistantTurnRecord(TypedDict, total=False):
    """Assistant message fields persisted after a SmartRead response."""

    content: str
    tier_used: str
    context_metadata: Mapping[str, object] | None
    tokens_used: Mapping[str, object]
    evidence_refs: list[Mapping[str, object]]
    analysis_chain: Mapping[str, object]
    inspiration_context: Mapping[str, object]


class SessionCompressionRecord(TypedDict):
    """Serializable long-session compression snapshot."""

    version: int
    strategy: str
    created_at: str
    covered_message_count: int
    covered_until_message_id: str | None
    original_estimated_tokens: int
    target_tokens: int
    keep_recent_turns: int
    summary: str


def build_session_context_messages(
    *,
    session: Mapping[str, object] | None,
    keep_recent_turns: int,
    max_chars_per_message: int = 1200,
) -> list[str]:
    """Build provider-facing context blocks from compressed session history.

    Args:
        session: Persisted session mapping. Missing sessions return no context.
        keep_recent_turns: Number of latest user/assistant turns to retain as
            raw history after any compression snapshot.
        max_chars_per_message: Character cap for each raw recent message.

    Returns:
        Context strings containing at most one compression summary plus recent
        raw messages. Original persisted messages are never modified.

    Raises:
        ValueError: If numeric bounds are invalid.
    """

    if session is not None and not isinstance(session, Mapping):
        raise TypeError("session must be a mapping or None")
    if not isinstance(keep_recent_turns, int) or keep_recent_turns < 1:
        raise ValueError("keep_recent_turns must be a positive integer")
    if not isinstance(max_chars_per_message, int) or max_chars_per_message < 80:
        raise ValueError("max_chars_per_message must be an integer >= 80")
    if session is None:
        return []

    raw_messages = session.get("messages")
    messages = raw_messages if isinstance(raw_messages, list) else []
    if not messages:
        return []

    context: list[str] = []
    compression = session.get("compression")
    covered_until_id: str | None = None
    if isinstance(compression, Mapping):
        summary = str(compression.get("summary") or "").strip()
        if summary:
            covered_until = compression.get("covered_until_message_id")
            covered_until_id = str(covered_until).strip() if covered_until is not None else None
            context.append(
                "[历史摘要]\n"
                f"strategy={compression.get('strategy')}; "
                f"covered_until_message_id={covered_until_id or ''}\n"
                f"{summary}"
            )

    recent_limit = keep_recent_turns * 2
    start_index = max(0, len(messages) - recent_limit)
    if covered_until_id:
        for index, message in enumerate(messages):
            if isinstance(message, Mapping) and str(message.get("id") or "") == covered_until_id:
                start_index = max(start_index, index + 1)
                break

    recent_blocks: list[str] = []
    for message in messages[start_index:]:
        if not isinstance(message, Mapping):
            continue
        role = str(message.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = _trim_summary_text(message.get("content"), limit=max_chars_per_message)
        if not content:
            continue
        message_id = str(message.get("id") or "").strip()
        prefix = f"{role}"
        if message_id:
            prefix = f"{prefix} id={message_id}"
        recent_blocks.append(f"{prefix}: {content}")
    if recent_blocks:
        context.append("[最近对话]\n" + "\n".join(recent_blocks))
    return context


@dataclass(frozen=True, slots=True)
class ChatPipelineFacade:
    """Stable B7 facade for the unified SmartRead chat pipeline.

    Args:
        mode: Unified SmartRead execution mode used for new chat turns.
        product_surface: Public product surface name; callers should not split
            new SmartRead sessions by legacy modes.
    """

    mode: LegacyChatMode
    product_surface: ProductSurface

    def resolve_mode(self, *, mode: object | None, direct_mode: bool) -> SmartReadModeDecision:
        """Resolve one request's legacy mode fields through the unified boundary."""
        return resolve_smart_read_mode(mode=mode, direct_mode=direct_mode)

    def plan_turn(
        self,
        *,
        requested_session_id: str | None,
        generated_session_id: str,
        mode: object | None,
        direct_mode: bool,
        existing_session: Mapping[str, object] | None,
    ) -> SmartReadTurnPlan:
        """Plan one SmartRead turn before retrieval, persistence, or provider calls."""
        return plan_smart_read_turn(
            requested_session_id=requested_session_id,
            generated_session_id=generated_session_id,
            mode=mode,
            direct_mode=direct_mode,
            existing_session=existing_session,
        )

    def build_evidence_records(
        self,
        sources: Sequence[object],
        *,
        kind: EvidenceSourceKind = "local",
        fallback_label: str = "local_context",
        skip_invalid: bool = False,
        assign_rank: bool = True,
    ) -> list[EvidenceReferenceRecord]:
        """Build normalized evidence records through the single evidence interface."""
        return build_evidence_reference_records(
            sources,
            kind=kind,
            fallback_label=fallback_label,
            skip_invalid=skip_invalid,
            assign_rank=assign_rank,
        )


def build_chat_pipeline() -> ChatPipelineFacade:
    """Return the stable B7 entrypoint for SmartRead session/evidence helpers."""
    return ChatPipelineFacade(
        mode=UNIFIED_SMART_READ_MODE,
        product_surface="smart_read",
    )


def _coerce_legacy_mode(value: object | None) -> LegacyChatMode | None:
    if value is None:
        return None
    raw_value = getattr(value, "value", value)
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise TypeError("mode must be a string, enum value, or None")
    normalized = raw_value.strip()
    if not normalized:
        return None
    if normalized not in LEGACY_CHAT_MODES:
        raise ValueError(f"unsupported legacy chat mode: {normalized}")
    return cast(LegacyChatMode, normalized)


def _session_has_messages(existing_session: Mapping[str, object] | None) -> bool:
    if existing_session is None:
        return False
    messages = existing_session.get("messages")
    return isinstance(messages, list) and len(messages) > 0


def _existing_session_mode(existing_session: Mapping[str, object] | None) -> LegacyChatMode:
    if existing_session is None:
        return UNIFIED_SMART_READ_MODE
    return _coerce_legacy_mode(existing_session.get("mode")) or UNIFIED_SMART_READ_MODE


def _coerce_persisted_mode(value: object | None) -> LegacyChatMode | None:
    try:
        return _coerce_legacy_mode(value)
    except (TypeError, ValueError):
        return None


def resolve_smart_read_mode(*, mode: object | None, direct_mode: bool) -> SmartReadModeDecision:
    """Resolve legacy request fields without creating new product modes.

    Args:
        mode: Optional legacy enum/string mode from older API callers.
        direct_mode: Deprecated boolean hint from the pre-unification Dialog.

    Returns:
        A mode decision that defaults all new smart-read requests to the
        unified evidence-enhanced path.

    Raises:
        TypeError: If ``direct_mode`` is not boolean or ``mode`` has an
            unsupported shape.
        ValueError: If ``mode`` is a string outside the legacy compatibility
            set.
    """

    if not isinstance(direct_mode, bool):
        raise TypeError("direct_mode must be a boolean")

    explicit_mode = _coerce_legacy_mode(mode)
    if explicit_mode is not None:
        return SmartReadModeDecision(
            execution_mode=explicit_mode,
            storage_mode=explicit_mode,
            product_surface="smart_read",
            legacy_mode_requested=explicit_mode != UNIFIED_SMART_READ_MODE,
            ignored_direct_mode_hint=False,
        )

    return SmartReadModeDecision(
        execution_mode=UNIFIED_SMART_READ_MODE,
        storage_mode=UNIFIED_SMART_READ_MODE,
        product_surface="smart_read",
        legacy_mode_requested=direct_mode,
        ignored_direct_mode_hint=direct_mode,
    )


def plan_smart_read_turn(
    *,
    requested_session_id: str | None,
    generated_session_id: str,
    mode: object | None,
    direct_mode: bool,
    existing_session: Mapping[str, object] | None,
) -> SmartReadTurnPlan:
    """Plan session and legacy-mode handling before retrieval or LLM calls.

    Args:
        requested_session_id: Client-provided session id, if any.
        generated_session_id: Server-generated fallback id for new sessions.
        mode: Optional explicit legacy mode.
        direct_mode: Deprecated boolean hint from the old Dialog UI.
        existing_session: Persisted session payload for ``requested_session_id``.

    Returns:
        A deterministic turn plan. ``conflict`` is populated when an existing
        non-empty session is being resumed with a different explicit legacy
        mode.

    Raises:
        ValueError: If both session ids normalize to empty or legacy mode is
            unsupported.
        TypeError: If ``direct_mode`` has an invalid shape.
    """

    if not isinstance(requested_session_id, str | None):
        raise TypeError("requested_session_id must be a string or None")
    if not isinstance(generated_session_id, str):
        raise TypeError("generated_session_id must be a string")

    normalized_requested = (requested_session_id or "").strip()
    normalized_generated = generated_session_id.strip()
    session_id = normalized_requested or normalized_generated
    if not session_id:
        raise ValueError("session_id must not be empty")

    decision = resolve_smart_read_mode(mode=mode, direct_mode=direct_mode)
    conflict: SmartReadModeConflict | None = None
    if normalized_requested and _session_has_messages(existing_session):
        current_mode = _existing_session_mode(existing_session)
        if current_mode != decision.execution_mode:
            conflict = SmartReadModeConflict(
                current_mode=current_mode,
                requested_mode=decision.execution_mode,
            )

    return SmartReadTurnPlan(
        session_id=session_id,
        requested_existing_session=bool(normalized_requested),
        mode_decision=decision,
        conflict=conflict,
    )


def clean_optional_text(value: object | None) -> str | None:
    """Return stripped text or None for optional persisted/provider fields."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_source_labels(payload: Mapping[str, object], fallback: str) -> list[str]:
    """Normalize source labels from legacy singular/plural evidence fields.

    Args:
        payload: Raw evidence or chunk metadata mapping.
        fallback: Non-empty label used when no metadata label exists.

    Returns:
        A non-empty list of unique-ish labels preserving input order.

    Raises:
        ValueError: If ``fallback`` is empty.
    """

    normalized_fallback = fallback.strip()
    if not normalized_fallback:
        raise ValueError("fallback must not be empty")

    raw_labels = payload.get("source_labels")
    labels: list[str] = []
    if isinstance(raw_labels, list):
        labels.extend(str(label).strip() for label in raw_labels if str(label).strip())

    raw_label = payload.get("source_label")
    if raw_label is not None and str(raw_label).strip():
        label_str = str(raw_label).strip()
        if label_str not in labels:
            labels.append(label_str)

    return labels or [normalized_fallback]


def render_context_strings(chunks: Sequence[ContextChunkLike]) -> list[str]:
    """Render retrieved chunks into provider-facing context strings.

    Args:
        chunks: Ordered retrieved chunks with provenance fields.

    Returns:
        Plain context blocks whose first line contains stable provenance
        metadata and whose body contains the chunk text.

    Raises:
        TypeError: If ``chunks`` is not a sequence.
    """

    if not isinstance(chunks, Sequence) or isinstance(chunks, str | bytes):
        raise TypeError("chunks must be a sequence of context chunks")

    context_strings: list[str] = []
    for chunk in chunks:
        meta_parts = [f"source={chunk.source}"]
        if chunk.chunk_id:
            meta_parts.append(f"chunk_id={chunk.chunk_id}")
        if chunk.material_id:
            meta_parts.append(f"material_id={chunk.material_id}")
        if chunk.section_title:
            meta_parts.append(f"section={chunk.section_title}")
        if chunk.page is not None:
            meta_parts.append(f"page={chunk.page}")
        context_strings.append(f"[{chunk.index}] {'; '.join(meta_parts)}\n{chunk.content}")
    return context_strings


def _coerce_source_kind(value: object) -> EvidenceSourceKind:
    if value in ("local", "web", "mcp"):
        return cast(EvidenceSourceKind, value)
    return "local"


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_optional_page(value: object) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(normalized)
        except ValueError:
            return normalized
    return None


def _coerce_optional_bbox(value: object) -> list[float] | None:
    """Return a finite four-number PDF bbox, or None when absent."""

    if not isinstance(value, list) or len(value) != 4:
        return None
    bbox: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            return None
        number = float(item)
        if not (number == number) or number in (float("inf"), float("-inf")):
            return None
        bbox.append(number)
    return bbox


def _coerce_optional_bbox_unit(value: object) -> str | None:
    """Return a known PDF bbox unit string, or None for legacy refs."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized in {"normalized_ratio", "normalized_1000", "pdf_points", "css_pixels"}:
        return normalized
    return None


def _coerce_overlap_tokens(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(token) for token in value if isinstance(token, str) and token.strip()]


def _source_mapping(source: object) -> Mapping[str, object]:
    if isinstance(source, Mapping):
        return source
    return {
        "index": getattr(source, "index", None),
        "source": getattr(source, "source", None),
        "content": getattr(source, "content", None),
        "score": getattr(source, "relevance_score", None),
        "chunk_id": getattr(source, "chunk_id", None),
        "material_id": getattr(source, "material_id", None),
        "source_labels": getattr(source, "source_labels", None),
        "page": getattr(source, "page", None),
        "source_hint": getattr(source, "source_hint", None),
        "bbox": getattr(source, "bbox", None),
        "bbox_unit": getattr(source, "bbox_unit", None),
    }


def build_evidence_reference_record(
    source: object,
    *,
    kind: EvidenceSourceKind = "local",
    rank: int | None = None,
    fallback_label: str = "local_context",
    require_identity: bool = False,
) -> EvidenceReferenceRecord:
    """Normalize one context chunk, RAG hit, web hit, or MCP hit.

    Args:
        source: Source object or mapping carrying chunk/evidence fields.
        kind: Provenance class for UI source-kind rendering.
        rank: Optional stable rank for ordered local context chunks.
        fallback_label: Non-empty label/source label when source metadata omits one.
        require_identity: When true, missing chunk/source/text rejects the record.

    Returns:
        A normalized evidence record ready for API-model validation.

    Raises:
        ValueError: If required identity fields are missing or fallback_label is empty.
    """

    normalized_label = fallback_label.strip()
    if not normalized_label:
        raise ValueError("fallback_label must not be empty")

    raw = _source_mapping(source)
    index = raw.get("index")
    chunk_id = clean_optional_text(raw.get("chunk_id"))
    material_id = clean_optional_text(raw.get("material_id"))
    text = str(
        raw.get("text")
        or raw.get("compressed_text")
        or raw.get("quote")
        or raw.get("content")
        or raw.get("source_text")
        or ""
    ).strip()
    source_label = str(
        raw.get("source")
        or raw.get("title")
        or raw.get("source_hint")
        or material_id
        or chunk_id
        or ""
    ).strip()

    if not chunk_id:
        chunk_id = f"{kind}-{index}" if index is not None else f"{kind}-{rank if rank is not None else 0}"
    if not source_label:
        source_label = chunk_id

    if require_identity and (not chunk_id or not source_label or not text):
        raise ValueError("evidence record requires chunk_id, source, and text")
    if not text:
        raise ValueError("evidence record text must not be empty")

    label = str(raw.get("label") or "").strip()
    if not label:
        if kind == "local":
            label = "project_chunk" if material_id else "local_context"
        else:
            label = normalized_label

    raw_rank = raw.get("rank")
    record_rank = raw_rank if isinstance(raw_rank, int) else rank
    record: EvidenceReferenceRecord = {
        "chunk_id": chunk_id,
        "material_id": material_id,
        "source": source_label,
        "text": text,
        "quote": str(raw.get("quote") or text[:300]).strip(),
        "label": label,
        "score": _coerce_optional_float(raw.get("score")),
        "source_labels": extract_source_labels(raw, normalized_label),
        "page": _coerce_optional_page(raw.get("page")),
        "source_hint": clean_optional_text(raw.get("source_hint")),
        "rank": record_rank,
        "query_overlap_tokens": _coerce_overlap_tokens(raw.get("query_overlap_tokens")),
        "source_kind": kind,
    }
    bbox = _coerce_optional_bbox(raw.get("bbox"))
    if bbox is not None:
        record["bbox"] = bbox
        record["bbox_unit"] = _coerce_optional_bbox_unit(raw.get("bbox_unit")) or "normalized_ratio"
    return record


def build_evidence_reference_records(
    sources: Sequence[object],
    *,
    kind: EvidenceSourceKind = "local",
    fallback_label: str = "local_context",
    skip_invalid: bool = False,
    assign_rank: bool = True,
) -> list[EvidenceReferenceRecord]:
    """Build normalized evidence records through the single evidence interface.

    Args:
        sources: Ordered source objects or mappings.
        kind: Provenance class shared by every source in this batch.
        fallback_label: Label/source-label fallback for missing metadata.
        skip_invalid: Skip malformed sources instead of raising.
        assign_rank: Assign sequential ranks when source records omit one.

    Returns:
        Valid evidence records preserving input order.

    Raises:
        TypeError: If sources is not a non-string sequence.
        ValueError: If a source is malformed and skip_invalid is false.
    """

    if not isinstance(sources, Sequence) or isinstance(sources, str | bytes | bytearray):
        raise TypeError("sources must be a sequence of evidence sources")

    records: list[EvidenceReferenceRecord] = []
    for index, source in enumerate(sources):
        try:
            records.append(
                build_evidence_reference_record(
                    source,
                    kind=kind,
                    rank=index if assign_rank else None,
                    fallback_label=fallback_label,
                    require_identity=skip_invalid,
                )
            )
        except (TypeError, ValueError):
            if not skip_invalid:
                raise
    return records


def coerce_evidence_reference_records(raw_refs: object) -> list[EvidenceReferenceRecord]:
    """Coerce raw RAG/tool evidence mappings into normalized records.

    Args:
        raw_refs: Provider/workflow output, expected to be a list of mappings.

    Returns:
        Valid records; malformed refs are skipped rather than failing the chat
        response after an answer has already been generated.
    """

    if not isinstance(raw_refs, list):
        return []
    records: list[EvidenceReferenceRecord] = []
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, Mapping):
            continue
        try:
            records.append(
                build_evidence_reference_record(
                    raw_ref,
                    kind=_coerce_source_kind(raw_ref.get("source_kind")),
                    fallback_label="rag_workflow",
                    require_identity=True,
                )
            )
        except (TypeError, ValueError):
            continue
    return records


def load_session_store(path: Path) -> dict[str, object]:
    """Load the local SmartRead JSON session store defensively.

    Args:
        path: JSON store path. Missing or malformed files degrade to an empty
            session store so a corrupt history file does not break chat.

    Returns:
        A mapping with a ``sessions`` dictionary.
    """

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if not path.exists():
        return {"sessions": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"sessions": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), dict):
        return {"sessions": {}}
    return payload


def save_session_store(path: Path, payload: Mapping[str, object]) -> None:
    """Atomically write the local SmartRead JSON session store.

    Args:
        path: JSON store path to replace.
        payload: Serializable store mapping containing a ``sessions`` object.

    Raises:
        TypeError: If inputs have invalid shapes.
        ValueError: If ``payload`` does not contain a sessions mapping.
    """

    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path")
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")
    if not isinstance(payload.get("sessions"), Mapping):
        raise ValueError("payload.sessions must be a mapping")

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_path = Path(handle.name)
        handle.write(serialized)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def title_from_session_messages(messages: list[object], *, session_id: str) -> str:
    """Return a compact non-empty drawer title from the first user message."""

    if not isinstance(messages, list):
        raise TypeError("messages must be a list")
    if not isinstance(session_id, str):
        raise TypeError("session_id must be a string")
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        if str(message.get("role")) != "user":
            continue
        text = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if text:
            return text[:30]
    suffix = session_id[-6:] if session_id else "new"
    return f"会话 #{suffix}"


def _compact_summary_text(value: object, *, max_length: int = 160) -> str:
    """Return one-line summary text for drawer metadata fields."""

    if max_length <= 0:
        raise ValueError("max_length must be positive")
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text.startswith("### 综合结论"):
        text = text.removeprefix("### 综合结论").strip()
    return text[:max_length]


def _session_summary_source(metadata: Mapping[str, object]) -> str | None:
    """Return a non-empty summary source marker from session metadata."""

    source = str(metadata.get("source") or "").strip()
    return source or None


def _session_summary_agent_count(metadata: Mapping[str, object]) -> int | None:
    """Return a bounded agent count stored in session metadata."""

    raw_count = metadata.get("agent_count")
    if isinstance(raw_count, bool) or raw_count is None:
        return None
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _discussion_synthesis_preview(messages: Sequence[object]) -> str | None:
    """Return the final synthesis text for a discussion-backed session."""

    if not isinstance(messages, Sequence):
        raise TypeError("messages must be a sequence")
    for message in reversed(messages):
        if not isinstance(message, Mapping):
            continue
        if str(message.get("role")) != "assistant":
            continue
        raw_discussion = message.get("discussion")
        if isinstance(raw_discussion, Mapping) and str(raw_discussion.get("node_kind")) != "synthesis":
            continue
        preview = _compact_summary_text(message.get("content"), max_length=180)
        if preview:
            return preview
    return None


def estimate_text_tokens(text: str) -> int:
    """Estimate token count for mixed CJK/Latin text.

    Args:
        text: Raw text to estimate.

    Returns:
        A non-negative approximate token count. The estimate intentionally
        over-counts short strings so compression triggers before provider
        context windows are exhausted.

    Raises:
        TypeError: If ``text`` is not a string.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_message_tokens(message: Mapping[str, object]) -> int:
    """Estimate token cost for a persisted chat message."""

    if not isinstance(message, Mapping):
        raise TypeError("message must be a mapping")
    content_tokens = estimate_text_tokens(str(message.get("content") or ""))
    evidence_refs = message.get("evidence_refs")
    evidence_cost = 0
    if isinstance(evidence_refs, list):
        for evidence in evidence_refs:
            if isinstance(evidence, Mapping):
                evidence_cost += estimate_text_tokens(str(evidence.get("quote") or evidence.get("text") or ""))
    return content_tokens + evidence_cost


def estimate_messages_tokens(messages: list[object]) -> int:
    """Estimate token cost for a persisted message list."""

    if not isinstance(messages, list):
        raise TypeError("messages must be a list")
    total = 0
    for message in messages:
        if isinstance(message, Mapping):
            total += estimate_message_tokens(message)
    return total


def _trim_summary_text(value: object, *, limit: int) -> str:
    if limit <= 0:
        raise ValueError("limit must be positive")
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def build_session_compression_record(
    *,
    messages: list[object],
    now_iso: str,
    target_tokens: int,
    keep_recent_turns: int,
) -> SessionCompressionRecord | None:
    """Build a deterministic compression snapshot without dropping history.

    Args:
        messages: Persisted user/assistant message list.
        now_iso: Snapshot timestamp.
        target_tokens: Approximate token target for the summary text.
        keep_recent_turns: Number of latest user/assistant turns excluded from
            the covered range so live context can retain fresh details.

    Returns:
        A compression record covering older messages, or ``None`` when there
        are too few messages to compress.

    Raises:
        TypeError: If inputs have invalid shapes.
        ValueError: If numeric bounds are invalid.
    """

    if not isinstance(messages, list):
        raise TypeError("messages must be a list")
    if not isinstance(now_iso, str) or not now_iso.strip():
        raise ValueError("now_iso must be a non-empty string")
    if not isinstance(target_tokens, int) or target_tokens < 128:
        raise ValueError("target_tokens must be an integer >= 128")
    if not isinstance(keep_recent_turns, int) or keep_recent_turns < 1:
        raise ValueError("keep_recent_turns must be a positive integer")

    keep_recent_messages = keep_recent_turns * 2
    covered_count = len(messages) - keep_recent_messages
    if covered_count <= 0:
        return None

    covered = [message for message in messages[:covered_count] if isinstance(message, Mapping)]
    if not covered:
        return None

    user_snippets = [
        _trim_summary_text(message.get("content"), limit=180)
        for message in covered
        if str(message.get("role") or "") == "user" and str(message.get("content") or "").strip()
    ]
    assistant_count = sum(1 for message in covered if str(message.get("role") or "") == "assistant")
    evidence_ids: list[str] = []
    for message in covered:
        raw_refs = message.get("evidence_refs")
        if not isinstance(raw_refs, list):
            continue
        for ref in raw_refs:
            if not isinstance(ref, Mapping):
                continue
            identifier = str(ref.get("chunk_id") or ref.get("material_id") or "").strip()
            if identifier and identifier not in evidence_ids:
                evidence_ids.append(identifier)

    lines = [
        "Long-session compression snapshot.",
        f"Covered messages: {len(covered)}.",
        f"Covered user turns: {len(user_snippets)}.",
        f"Covered assistant turns: {assistant_count}.",
    ]
    if user_snippets:
        lines.append(f"First user request: {user_snippets[0]}.")
        recent_requests = user_snippets[-5:]
        lines.append("Recent covered user requests: " + " | ".join(recent_requests) + ".")
    if evidence_ids:
        lines.append("Evidence ids referenced: " + ", ".join(evidence_ids[:20]) + ".")

    max_summary_chars = target_tokens * 4
    summary = _trim_summary_text("\n".join(lines), limit=max_summary_chars)
    covered_until = covered[-1].get("id") if covered else None
    return {
        "version": 1,
        "strategy": "deterministic_extractive_v1",
        "created_at": now_iso,
        "covered_message_count": len(covered),
        "covered_until_message_id": str(covered_until) if covered_until is not None else None,
        "original_estimated_tokens": estimate_messages_tokens(covered),
        "target_tokens": target_tokens,
        "keep_recent_turns": keep_recent_turns,
        "summary": summary,
    }


def apply_session_auto_compression(
    *,
    session: dict[str, object],
    trigger_tokens: int,
    target_tokens: int,
    keep_recent_turns: int,
    now_iso: str,
) -> bool:
    """Attach or refresh a compression snapshot when a session crosses budget.

    Args:
        session: Mutable persisted session mapping.
        trigger_tokens: Estimated full-session token threshold.
        target_tokens: Approximate summary size target.
        keep_recent_turns: Number of latest turns left uncompressed.
        now_iso: Snapshot timestamp.

    Returns:
        True when ``session["compression"]`` was updated.

    Raises:
        TypeError: If ``session`` is not mutable.
        ValueError: If policy values are invalid.
    """

    if not isinstance(session, dict):
        raise TypeError("session must be a mutable dict")
    if not isinstance(trigger_tokens, int) or trigger_tokens < 512:
        raise ValueError("trigger_tokens must be an integer >= 512")
    if not isinstance(target_tokens, int) or target_tokens < 128:
        raise ValueError("target_tokens must be an integer >= 128")
    if target_tokens >= trigger_tokens:
        raise ValueError("target_tokens must be smaller than trigger_tokens")

    raw_messages = session.get("messages")
    messages = raw_messages if isinstance(raw_messages, list) else []
    estimated_tokens = estimate_messages_tokens(messages)
    if estimated_tokens < trigger_tokens:
        return False

    record = build_session_compression_record(
        messages=messages,
        now_iso=now_iso,
        target_tokens=target_tokens,
        keep_recent_turns=keep_recent_turns,
    )
    if record is None:
        return False
    session["compression"] = record
    session["compression_updated_at"] = now_iso
    return True


def summarize_session_record(session: Mapping[str, object]) -> SessionSummaryRecord:
    """Summarize one persisted SmartRead session for a history drawer row.

    Args:
        session: Persisted session mapping from the JSON store.

    Returns:
        A serializable summary with legacy mode inference preserved.

    Raises:
        TypeError: If ``session`` is not a mapping.
    """

    if not isinstance(session, Mapping):
        raise TypeError("session must be a mapping")

    raw_messages = session.get("messages")
    messages = raw_messages if isinstance(raw_messages, list) else []
    preview = ""
    for message in reversed(messages):
        if isinstance(message, Mapping) and str(message.get("role")) == "user":
            preview = str(message.get("content") or "")[:160]
            break

    raw_metadata = session.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
    source = _session_summary_source(metadata)
    agent_count = _session_summary_agent_count(metadata)
    synthesis_preview = (
        _discussion_synthesis_preview(messages)
        if source == DISCUSSION_SESSION_SOURCE
        else None
    )

    raw_mode = session.get("mode")
    mode = _coerce_persisted_mode(raw_mode)
    legacy = mode is None
    normalized_mode = mode or UNIFIED_SMART_READ_MODE
    session_id = str(session.get("session_id") or "")
    raw_project_id = session.get("project_id")
    project_id = str(raw_project_id).strip() if raw_project_id is not None else ""
    raw_fork = session.get("fork")
    fork: dict[str, str] | None = None
    if isinstance(raw_fork, Mapping):
        source_session_id = str(raw_fork.get("source_session_id") or "").strip()
        base_node_id = str(raw_fork.get("base_node_id") or "").strip()
        branch_id = str(raw_fork.get("branch_id") or "").strip()
        created_at = str(raw_fork.get("created_at") or "").strip()
        if source_session_id and base_node_id and branch_id:
            fork = {
                "source_session_id": source_session_id,
                "base_node_id": base_node_id,
                "branch_id": branch_id,
            }
            if created_at:
                fork["created_at"] = created_at

    return {
        "session_id": session_id,
        "project_id": project_id or None,
        "title": title_from_session_messages(messages, session_id=session_id),
        "total_turns": len(messages),
        "total_tokens": int(session.get("total_tokens") or 0),
        "created_at": str(session.get("created_at")) if session.get("created_at") is not None else None,
        "updated_at": str(session.get("updated_at")) if session.get("updated_at") is not None else None,
        "preview": preview,
        "mode": normalized_mode,
        "legacy_mode_inferred": legacy,
        "source": source,
        "agent_count": agent_count,
        "synthesis_preview": synthesis_preview,
        "fork": fork,
        "archived": bool(session.get("archived")),
        "archived_at": str(session.get("archived_at")) if session.get("archived_at") is not None else None,
    }


def append_session_turns(
    *,
    store: dict[str, object],
    session_id: str,
    query: str,
    assistant_turn: AssistantTurnRecord,
    mode: LegacyChatMode,
    now_iso: str,
    project_id: str | None = None,
    id_factory: Callable[[], str] | None = None,
) -> None:
    """Append one user/assistant exchange to an in-memory session store.

    Args:
        store: Mutable session store with a ``sessions`` mapping.
        session_id: Non-empty session id to create or update.
        query: User message text.
        assistant_turn: Serializable assistant fields already adapted from
            response models by the router layer.
        mode: Legacy-compatible internal mode to persist for this session.
        now_iso: Timestamp string assigned to both messages and session update.
        project_id: Optional project id that scopes the conversation history.
        id_factory: Optional deterministic id suffix factory for tests.

    Raises:
        TypeError: If inputs have invalid shapes.
        ValueError: If required string fields are empty or mode is unsupported.
    """

    if not isinstance(store, dict):
        raise TypeError("store must be a mutable dict")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if not isinstance(now_iso, str) or not now_iso.strip():
        raise ValueError("now_iso must be a non-empty string")
    normalized_project_id = str(project_id or "").strip()
    normalized_mode = _coerce_legacy_mode(mode)
    if normalized_mode is None:
        raise ValueError("mode must not be empty")

    raw_sessions = store.setdefault("sessions", {})
    if not isinstance(raw_sessions, dict):
        raise ValueError("store.sessions must be a mutable dict")
    suffix = id_factory or (lambda: uuid4().hex[:12])
    session = raw_sessions.setdefault(
        session_id,
        {
            "session_id": session_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "mode": normalized_mode,
            "messages": [],
        },
    )
    if not isinstance(session, dict):
        raise ValueError("session entry must be a mutable dict")

    if not session.get("mode"):
        session["mode"] = normalized_mode
    if normalized_project_id:
        session["project_id"] = normalized_project_id
    messages = session.setdefault("messages", [])
    if not isinstance(messages, list):
        raise ValueError("session.messages must be a list")

    messages.append(
        {
            "id": f"user-{suffix()}",
            "role": "user",
            "content": query,
            "timestamp": now_iso,
        }
    )
    assistant_message: dict[str, object] = {
        "id": f"assistant-{suffix()}",
        "role": "assistant",
        "content": str(assistant_turn.get("content") or ""),
        "timestamp": now_iso,
        "tier_used": assistant_turn.get("tier_used"),
        "context_metadata": assistant_turn.get("context_metadata"),
        "tokens_used": assistant_turn.get("tokens_used") or {},
        "evidence_refs": assistant_turn.get("evidence_refs") or [],
    }
    analysis_chain = assistant_turn.get("analysis_chain")
    if isinstance(analysis_chain, Mapping):
        assistant_message["analysis_chain"] = dict(analysis_chain)
    inspiration_context = assistant_turn.get("inspiration_context")
    if normalized_mode == "inspiration" and inspiration_context is not None:
        assistant_message["inspiration_context"] = inspiration_context
    messages.append(assistant_message)

    session["updated_at"] = now_iso
    session["total_tokens"] = sum(
        int((message.get("tokens_used") or {}).get("total") or 0)
        for message in messages
        if isinstance(message, Mapping)
    )

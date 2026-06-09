"""Persist discussion runs into the unified SmartRead history surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
from typing import Any

from project_paths import runtime_state_path

from .history_store import ChatHistoryStore, default_chat_history_db_path
from .pipeline import load_session_store, save_session_store
from models.discussion import (
    DiscussionAgentConfig,
    DiscussionAgentTrace,
    DiscussionEvidencePackPayload,
    DiscussionRunConfig,
    DiscussionRunResult,
)


SMART_READ_DISCUSSION_MODE = "literature_qa"
DISCUSSION_SESSION_SOURCE = "multi_agent_discussion"
_SESSION_STORE_PATH = runtime_state_path("intelligent_chat_sessions.json")
_SESSION_LOCK = threading.Lock()
_NODE_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id_part(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    cleaned = _NODE_SAFE_RE.sub("_", text).strip("_")
    return cleaned or fallback


def _trace_label(trace: DiscussionAgentTrace) -> str:
    label = trace.role_label.strip() if isinstance(trace.role_label, str) else ""
    if label:
        return label
    role = trace.role.strip() if isinstance(trace.role, str) else ""
    if role:
        return role
    return trace.agent_id


def _agent_config_by_id(config: DiscussionRunConfig | None) -> dict[str, DiscussionAgentConfig]:
    if config is None:
        return {}
    return {agent.agent_id: agent for agent in config.agent_configs}


def _evidence_refs_by_id(
    evidence: DiscussionEvidencePackPayload | None,
) -> dict[str, dict[str, object]]:
    if evidence is None:
        return {}
    refs: dict[str, dict[str, object]] = {}
    for index, snippet in enumerate(evidence.snippets):
        if not isinstance(snippet, Mapping):
            continue
        evidence_id = (
            evidence.evidence_ids[index]
            if index < len(evidence.evidence_ids)
            else f"E{index + 1}"
        )
        content = str(snippet.get("content") or snippet.get("text") or "").strip()
        chunk_id = str(snippet.get("chunk_id") or evidence_id).strip()
        if not chunk_id:
            chunk_id = evidence_id
        source = str(snippet.get("source") or "discussion_evidence").strip()
        raw_score = snippet.get("score")
        score = float(raw_score) if isinstance(raw_score, int | float) else None
        source_labels = snippet.get("source_labels")
        refs[evidence_id] = {
            "chunk_id": chunk_id,
            "material_id": str(snippet.get("material_id") or "").strip() or None,
            "source": source,
            "text": content,
            "quote": content,
            "label": evidence_id,
            "score": score,
            "source_labels": (
                [str(label) for label in source_labels if str(label).strip()]
                if isinstance(source_labels, list)
                else ["discussion_evidence"]
            ),
            "page": None,
            "rank": index + 1,
            "query_overlap_tokens": [],
            "source_kind": "local",
            "discussion_evidence_id": evidence_id,
        }
    return refs


def _refs_for_ids(
    evidence_by_id: Mapping[str, Mapping[str, object]],
    evidence_ids: Sequence[str],
) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    seen: set[str] = set()
    for evidence_id in evidence_ids:
        normalized = str(evidence_id or "").strip()
        if not normalized or normalized in seen:
            continue
        raw_ref = evidence_by_id.get(normalized)
        if raw_ref is None:
            continue
        refs.append(dict(raw_ref))
        seen.add(normalized)
    return refs


def _fallback_refs(
    evidence_by_id: Mapping[str, Mapping[str, object]],
    *,
    limit: int = 8,
) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for evidence_id in sorted(evidence_by_id.keys(), key=lambda item: int(item[1:]) if item[1:].isdigit() else 10_000):
        refs.append(dict(evidence_by_id[evidence_id]))
        if len(refs) >= limit:
            break
    return refs


def _agent_metadata(trace: DiscussionAgentTrace, *, turn_index: int, result: DiscussionRunResult) -> dict[str, object]:
    payload = trace.model_dump(mode="json")
    payload.pop("answer", None)
    payload.pop("credential_id", None)
    return {
        "source": DISCUSSION_SESSION_SOURCE,
        "discussion_run_id": result.run_id,
        "turn_index": turn_index,
        "agent_id": trace.agent_id,
        "agent_role": trace.role,
        "role_label": trace.role_label,
        "trace": payload,
    }


def _message_for_trace(
    trace: DiscussionAgentTrace,
    *,
    result: DiscussionRunResult,
    turn_index: int,
    evidence_refs: list[dict[str, object]],
    timestamp: str,
) -> dict[str, object]:
    label = _trace_label(trace)
    status = "" if trace.success else "\n\n[讨论角色执行失败]"
    return {
        "id": f"{result.run_id}_turn_{turn_index}_{_safe_id_part(trace.agent_id, fallback='agent')}",
        "role": "assistant",
        "content": f"### {label} · 第 {turn_index + 1} 轮\n\n{trace.answer}{status}".strip(),
        "timestamp": timestamp,
        "tokens_used": {},
        "evidence_refs": evidence_refs,
        "discussion": _agent_metadata(trace, turn_index=turn_index, result=result),
    }


def build_discussion_smart_read_session(
    result: DiscussionRunResult,
    *,
    config: DiscussionRunConfig | None = None,
    now_iso: str | None = None,
    existing_session: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the SmartRead JSON-session row for one completed discussion.

    Args:
        result: Completed discussion result from the orchestrator.
        config: Original run config, when available.
        now_iso: Optional deterministic timestamp for tests.
        existing_session: Previous session row; archive flags are preserved.

    Returns:
        JSON-serializable session mapping stored in the SmartRead session file.

    Raises:
        TypeError: If objects have invalid shapes.
        ValueError: If ``result.run_id`` is empty.
    """

    if not isinstance(result, DiscussionRunResult):
        raise TypeError("result must be a DiscussionRunResult")
    if config is not None and not isinstance(config, DiscussionRunConfig):
        raise TypeError("config must be a DiscussionRunConfig or None")
    run_id = result.run_id.strip()
    if not run_id:
        raise ValueError("result.run_id must not be empty")
    timestamp = now_iso or _now_iso()
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("now_iso must be a non-empty string")

    evidence_by_id = _evidence_refs_by_id(result.evidence)
    messages: list[dict[str, object]] = [
        {
            "id": f"{run_id}_query",
            "role": "user",
            "content": result.query,
            "timestamp": timestamp,
            "discussion": {
                "source": DISCUSSION_SESSION_SOURCE,
                "discussion_run_id": run_id,
                "node_kind": "query",
            },
        }
    ]

    cited_ids: list[str] = []
    for turn in result.turns:
        for trace in turn.agent_traces:
            refs = _refs_for_ids(evidence_by_id, trace.cited_evidence_ids)
            cited_ids.extend(str(ref.get("discussion_evidence_id") or "") for ref in refs)
            messages.append(
                _message_for_trace(
                    trace,
                    result=result,
                    turn_index=turn.turn_index,
                    evidence_refs=refs,
                    timestamp=timestamp,
                )
            )

    synthesis_refs = _refs_for_ids(evidence_by_id, cited_ids)
    if not synthesis_refs and evidence_by_id:
        synthesis_refs = _fallback_refs(evidence_by_id)
    if result.synthesis.text.strip():
        messages.append(
            {
                "id": f"{run_id}_synthesis",
                "role": "assistant",
                "content": f"### 综合结论\n\n{result.synthesis.text}".strip(),
                "timestamp": timestamp,
                "tokens_used": {},
                "evidence_refs": synthesis_refs,
                "discussion": {
                    "source": DISCUSSION_SESSION_SOURCE,
                    "discussion_run_id": run_id,
                    "node_kind": "synthesis",
                    "synthesizer_agent_id": result.synthesis.synthesizer_agent_id,
                    "strategy": result.synthesis.strategy,
                    "success": result.synthesis.success,
                },
            }
        )

    existing_created = None
    archived = False
    archived_at = None
    if isinstance(existing_session, Mapping):
        existing_created = existing_session.get("created_at")
        archived = bool(existing_session.get("archived"))
        archived_at = existing_session.get("archived_at")

    session: dict[str, object] = {
        "session_id": run_id,
        "created_at": str(existing_created or timestamp),
        "updated_at": timestamp,
        "mode": SMART_READ_DISCUSSION_MODE,
        "project_id": result.project_id,
        "messages": messages,
        "total_tokens": 0,
        "metadata": {
            "source": DISCUSSION_SESSION_SOURCE,
            "discussion_run_id": run_id,
            "agent_count": len(_agent_config_by_id(config)) if config else len({trace.agent_id for turn in result.turns for trace in turn.agent_traces}),
            "turn_count": len(result.turns),
            "stop_reason": result.stop_reason,
            "stopped_early": result.stopped_early,
        },
    }
    if archived:
        session["archived"] = True
        if archived_at is not None:
            session["archived_at"] = archived_at
    return session


def _write_session_store(
    *,
    session: Mapping[str, object],
    session_store_path: Path,
) -> None:
    with _SESSION_LOCK:
        store = load_session_store(session_store_path)
        sessions = store.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            raise ValueError("session store sessions must be a mapping")
        sessions[str(session["session_id"])] = dict(session)
        save_session_store(session_store_path, store)


def _persist_history_store(
    result: DiscussionRunResult,
    *,
    config: DiscussionRunConfig | None,
    history_db_path: Path,
    now_iso: str,
) -> int:
    store = ChatHistoryStore(history_db_path)
    run_id = result.run_id
    store.create_conversation(
        conversation_id=run_id,
        created_at=now_iso,
        project_id=result.project_id,
        title=result.query[:80],
        mode=SMART_READ_DISCUSSION_MODE,
        metadata={
            "source": DISCUSSION_SESSION_SOURCE,
            "discussion_run_id": run_id,
            "turn_count": len(result.turns),
        },
    )
    store.upsert_agent(
        conversation_id=run_id,
        agent_id="user",
        agent_role="user",
        display_name="用户",
        created_at=now_iso,
        metadata={"source": DISCUSSION_SESSION_SOURCE},
    )
    agent_configs = _agent_config_by_id(config)
    for turn in result.turns:
        for trace in turn.agent_traces:
            agent_config = agent_configs.get(trace.agent_id)
            store.upsert_agent(
                conversation_id=run_id,
                agent_id=trace.agent_id,
                agent_role=trace.role,
                display_name=_trace_label(trace),
                provider=trace.provider,
                model=trace.model,
                created_at=now_iso,
                metadata={
                    "source": DISCUSSION_SESSION_SOURCE,
                    "strict_pin": bool(agent_config.strict_pin) if agent_config else False,
                    "priority": int(agent_config.priority) if agent_config else 0,
                },
            )

    parent_node_id: str | None = f"{run_id}_query"
    store.append_node(
        conversation_id=run_id,
        node_id=parent_node_id,
        role="user",
        node_type="message",
        created_at=now_iso,
        content_text=result.query,
        metadata={"source": DISCUSSION_SESSION_SOURCE, "discussion_run_id": run_id, "node_kind": "query"},
        agent_id="user",
        agent_role="user",
    )

    evidence_by_id = _evidence_refs_by_id(result.evidence)
    node_count = 1
    cited_ids: list[str] = []
    for turn in result.turns:
        for trace in turn.agent_traces:
            safe_agent_id = _safe_id_part(trace.agent_id, fallback="agent")
            agent_run_id = f"{run_id}_{safe_agent_id}"
            store.create_agent_run(
                conversation_id=run_id,
                agent_id=trace.agent_id,
                run_id=agent_run_id,
                created_at=now_iso,
                task_text=result.query,
                status="completed" if trace.success else "error",
                metadata={"source": DISCUSSION_SESSION_SOURCE, "discussion_run_id": run_id},
            )
            refs = _refs_for_ids(evidence_by_id, trace.cited_evidence_ids)
            cited_ids.extend(str(ref.get("discussion_evidence_id") or "") for ref in refs)
            node_id = f"{run_id}_turn_{turn.turn_index}_{safe_agent_id}"
            store.append_node(
                conversation_id=run_id,
                node_id=node_id,
                parent_node_id=parent_node_id,
                role="assistant",
                node_type="message",
                created_at=now_iso,
                content_text=f"{_trace_label(trace)} · 第 {turn.turn_index + 1} 轮\n\n{trace.answer}".strip(),
                raw=trace.model_dump(mode="json"),
                metadata=_agent_metadata(trace, turn_index=turn.turn_index, result=result),
                evidence_refs=refs,
                agent_id=trace.agent_id,
                agent_role=trace.role,
                run_id=agent_run_id,
            )
            parent_node_id = node_id
            node_count += 1

    if result.synthesis.text.strip():
        synthesis_agent_id = result.synthesis.synthesizer_agent_id or "discussion_synthesizer"
        synthesis_run_id = f"{run_id}_synthesis"
        if synthesis_agent_id not in {trace.agent_id for turn in result.turns for trace in turn.agent_traces}:
            store.upsert_agent(
                conversation_id=run_id,
                agent_id=synthesis_agent_id,
                agent_role="synthesizer",
                display_name="综合裁判",
                provider=result.synthesis.synthesizer_provider or None,
                model=result.synthesis.synthesizer_model or None,
                created_at=now_iso,
                metadata={"source": DISCUSSION_SESSION_SOURCE},
            )
        store.create_agent_run(
            conversation_id=run_id,
            agent_id=synthesis_agent_id,
            run_id=synthesis_run_id,
            created_at=now_iso,
            task_text=result.query,
            status="completed" if result.synthesis.success else "error",
            metadata={"source": DISCUSSION_SESSION_SOURCE, "discussion_run_id": run_id},
        )
        refs = _refs_for_ids(evidence_by_id, cited_ids)
        if not refs and evidence_by_id:
            refs = _fallback_refs(evidence_by_id)
        store.append_node(
            conversation_id=run_id,
            node_id=f"{run_id}_synthesis",
            parent_node_id=parent_node_id,
            role="assistant",
            node_type="summary",
            created_at=now_iso,
            content_text=f"综合结论\n\n{result.synthesis.text}".strip(),
            raw=result.synthesis.model_dump(mode="json"),
            metadata={
                "source": DISCUSSION_SESSION_SOURCE,
                "discussion_run_id": run_id,
                "node_kind": "synthesis",
            },
            evidence_refs=refs,
            agent_id=synthesis_agent_id,
            agent_role="synthesizer",
            run_id=synthesis_run_id,
        )
        node_count += 1
    return node_count


def persist_discussion_result_to_smart_read(
    result: DiscussionRunResult,
    *,
    config: DiscussionRunConfig | None = None,
    session_store_path: Path | None = None,
    history_db_path: Path | None = None,
    now_iso: str | None = None,
) -> dict[str, object]:
    """Persist one discussion run into SmartRead JSON and durable history.

    Returns:
        Counts and identifiers useful for deterministic tests and run logs.

    Raises:
        TypeError: If input shapes are invalid.
        ValueError: If required identifiers are empty.
    """

    if not isinstance(result, DiscussionRunResult):
        raise TypeError("result must be a DiscussionRunResult")
    if config is not None and not isinstance(config, DiscussionRunConfig):
        raise TypeError("config must be a DiscussionRunConfig or None")
    resolved_session_path = session_store_path or _SESSION_STORE_PATH
    resolved_history_path = history_db_path or default_chat_history_db_path()
    if not isinstance(resolved_session_path, Path):
        raise TypeError("session_store_path must be a pathlib.Path")
    if not isinstance(resolved_history_path, Path):
        raise TypeError("history_db_path must be a pathlib.Path")
    timestamp = now_iso or _now_iso()

    existing_session: Mapping[str, object] | None = None
    store_payload = load_session_store(resolved_session_path)
    raw_sessions = store_payload.get("sessions")
    if isinstance(raw_sessions, Mapping):
        raw_existing = raw_sessions.get(result.run_id)
        if isinstance(raw_existing, Mapping):
            existing_session = raw_existing

    session = build_discussion_smart_read_session(
        result,
        config=config,
        now_iso=timestamp,
        existing_session=existing_session,
    )
    _write_session_store(session=session, session_store_path=resolved_session_path)
    node_count = _persist_history_store(
        result,
        config=config,
        history_db_path=resolved_history_path,
        now_iso=timestamp,
    )
    if bool(session.get("archived")):
        ChatHistoryStore(resolved_history_path).set_conversation_archived(
            result.run_id,
            archived=True,
            archived_at=str(session.get("archived_at") or "").strip() or None,
        )
    return {
        "session_id": result.run_id,
        "message_count": len(session.get("messages", [])) if isinstance(session.get("messages"), list) else 0,
        "node_count": node_count,
    }


def set_discussion_smart_read_archived(
    run_id: str,
    *,
    archived: bool,
    archived_at: str | None = None,
    session_store_path: Path | None = None,
    history_db_path: Path | None = None,
) -> bool:
    """Mirror discussion archive state into SmartRead session and search stores."""

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(archived, bool):
        raise TypeError("archived must be a boolean")
    resolved_session_path = session_store_path or _SESSION_STORE_PATH
    resolved_history_path = history_db_path or default_chat_history_db_path()
    if not isinstance(resolved_session_path, Path):
        raise TypeError("session_store_path must be a pathlib.Path")
    if not isinstance(resolved_history_path, Path):
        raise TypeError("history_db_path must be a pathlib.Path")
    normalized_run_id = run_id.strip()
    resolved_archived_at = archived_at or _now_iso() if archived else None
    session_updated = False
    with _SESSION_LOCK:
        store = load_session_store(resolved_session_path)
        sessions = store.get("sessions")
        if isinstance(sessions, dict):
            session = sessions.get(normalized_run_id)
            if isinstance(session, dict):
                session["archived"] = archived
                if archived:
                    session["archived_at"] = resolved_archived_at
                else:
                    session.pop("archived_at", None)
                save_session_store(resolved_session_path, store)
                session_updated = True
    history_updated = ChatHistoryStore(resolved_history_path).set_conversation_archived(
        normalized_run_id,
        archived=archived,
        archived_at=resolved_archived_at,
    )
    return session_updated or history_updated


def delete_discussion_smart_read_session(
    run_id: str,
    *,
    session_store_path: Path | None = None,
    history_db_path: Path | None = None,
) -> bool:
    """Remove one discussion mirror from SmartRead session and search stores."""

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    resolved_session_path = session_store_path or _SESSION_STORE_PATH
    resolved_history_path = history_db_path or default_chat_history_db_path()
    if not isinstance(resolved_session_path, Path):
        raise TypeError("session_store_path must be a pathlib.Path")
    if not isinstance(resolved_history_path, Path):
        raise TypeError("history_db_path must be a pathlib.Path")
    normalized_run_id = run_id.strip()
    session_removed = False
    with _SESSION_LOCK:
        store = load_session_store(resolved_session_path)
        sessions = store.get("sessions")
        if isinstance(sessions, dict) and normalized_run_id in sessions:
            del sessions[normalized_run_id]
            save_session_store(resolved_session_path, store)
            session_removed = True
    history_removed = ChatHistoryStore(resolved_history_path).delete_conversation(normalized_run_id)
    return session_removed or history_removed


def mirror_discussion_snapshots_to_smart_read(
    snapshots: Sequence[Mapping[str, object]],
    *,
    session_store_path: Path | None = None,
    history_db_path: Path | None = None,
    now_iso: str | None = None,
) -> dict[str, int]:
    """Mirror completed discussion task snapshots into SmartRead history.

    Args:
        snapshots: Discussion task-store snapshots. Only completed snapshots
            with a valid ``final_result`` are mirrored.
        session_store_path: Optional test seam for the SmartRead JSON store.
        history_db_path: Optional test seam for the durable history SQLite DB.
        now_iso: Optional deterministic timestamp for tests.

    Returns:
        Counts for inspected, mirrored, skipped, and failed snapshots.

    Raises:
        TypeError: If ``snapshots`` has an invalid shape.
    """

    if not isinstance(snapshots, Sequence) or isinstance(snapshots, str | bytes):
        raise TypeError("snapshots must be a sequence of mappings")
    counts = {"inspected": 0, "mirrored": 0, "skipped": 0, "failed": 0}
    timestamp = now_iso or _now_iso()
    for snapshot in snapshots:
        counts["inspected"] += 1
        if not isinstance(snapshot, Mapping):
            counts["skipped"] += 1
            continue
        if str(snapshot.get("state") or "") != "completed":
            counts["skipped"] += 1
            continue
        raw_result = snapshot.get("final_result")
        if not isinstance(raw_result, Mapping):
            counts["skipped"] += 1
            continue
        try:
            result = DiscussionRunResult.model_validate(raw_result)
            raw_config = snapshot.get("config")
            config = (
                DiscussionRunConfig.model_validate(raw_config)
                if isinstance(raw_config, Mapping)
                else None
            )
            persist_discussion_result_to_smart_read(
                result,
                config=config,
                session_store_path=session_store_path,
                history_db_path=history_db_path,
                now_iso=timestamp,
            )
            if bool(snapshot.get("archived")):
                archived_value = snapshot.get("archived_at")
                set_discussion_smart_read_archived(
                    result.run_id,
                    archived=True,
                    archived_at=str(archived_value) if archived_value is not None else None,
                    session_store_path=session_store_path,
                    history_db_path=history_db_path,
                )
            counts["mirrored"] += 1
        except Exception:
            counts["failed"] += 1
    return counts


def mirror_completed_discussion_runs_to_smart_read(
    *,
    session_store_path: Path | None = None,
    history_db_path: Path | None = None,
) -> dict[str, int]:
    """Mirror completed runs from the process-wide discussion task store."""

    from discussion_task_store import get_discussion_task_store

    snapshots = get_discussion_task_store().list_runs(include_archived=True)
    return mirror_discussion_snapshots_to_smart_read(
        snapshots,
        session_store_path=session_store_path,
        history_db_path=history_db_path,
    )


__all__ = [
    "DISCUSSION_SESSION_SOURCE",
    "SMART_READ_DISCUSSION_MODE",
    "build_discussion_smart_read_session",
    "delete_discussion_smart_read_session",
    "mirror_completed_discussion_runs_to_smart_read",
    "mirror_discussion_snapshots_to_smart_read",
    "persist_discussion_result_to_smart_read",
    "set_discussion_smart_read_archived",
]

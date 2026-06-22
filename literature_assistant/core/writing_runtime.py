# -*- coding: utf-8 -*-
"""
WritingRuntime - Long-lived backend runtime for session and job management.

Manages WritingSession, WritingJob, WritingEvent, and WritingArtifact.
Provides stable in-memory state management with clean interfaces for future persistence.
Maintains backward compatibility with legacy run_action flows.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from datetime_utils import utc_now_iso_z
from repositories.writing_runtime_repository import WritingRuntimeRepository
from harness_protocols import (
    WritingSession,
    WritingJob,
    WritingEvent,
    WritingArtifact,
    WritingApprovalRequest,
    SessionMode,
    JobKind,
    JobStatus,
    EventType,
    ArtifactType,
    ApprovalStatus,
)
from skills.runtime import SkillRunResult

logger = logging.getLogger("WritingRuntime")

_RUNTIME_RECOVERABLE_EXCEPTIONS = (
    AssertionError,
    AttributeError,
    BufferError,
    EOFError,
    ExceptionGroup,
    ImportError,
    IndexError,
    KeyError,
    LookupError,
    MemoryError,
    NameError,
    NotImplementedError,
    OSError,
    ReferenceError,
    RuntimeError,
    TypeError,
    ValueError,
)
_WRITING_WORKFLOW_STATE_KEY = "writing_workflow_state"
_MATERIAL_PROCESSING_TASK_KEY = "material_processing_task"
_MATERIAL_PROCESSING_SCHEMA_VERSION = "material_processing_task_v1"
_MATERIAL_PROCESSING_ALLOWED_MODES = {
    "fast_text",
    "layout_aware",
    "ocr_fallback",
    "translation_sidecar",
}
_MATERIAL_PROCESSING_CACHE_POLICIES = {"use", "refresh", "bypass"}
_MATERIAL_PROCESSING_CACHE_DECISIONS = {"pending", "hit", "miss", "bypass", "refresh", "invalidated"}
_MATERIAL_PROCESSING_TASK_STATUSES = {
    "created",
    "queued",
    "started",
    "running",
    "in_progress",
    "paused",
    "completed",
    "failed",
    "cancelled",
}
_MATERIAL_PROCESSING_OUTPUT_TARGETS = {
    "chunks",
    "locators",
    "figures",
    "tables",
    "layout_sidecar",
    "text_sidecar",
    "bilingual_sidecar",
    "docx",
    "evidence_refs",
}
_RESEARCH_PROJECTION_SCHEMA_VERSION = "research_object_projection_v1"
_RESEARCH_EVENT_SOURCE = "scholar-ai.runtime"
_RESEARCH_PROJECT_OBJECT_TYPE = "research_project"
_MATERIAL_PROCESSING_CACHE_DECISION_SCHEMA_VERSION = "material_processing_cache_decision_v1"
_WORKFLOW_PASSPORT_SCHEMA_VERSION = "scholar_ai_workflow_passport_v1"
_EVIDENCE_INTEGRITY_GATE_SCHEMA_VERSION = "scholar_ai_evidence_integrity_gate_v1"
_AGENT_HANDOFF_CARD_SCHEMA_VERSION = "scholar_ai_agent_handoff_card_v1"
_ACTION_PREFLIGHT_SCHEMA_VERSION = "scholar_ai_action_preflight_v1"
_BLOCKING_ACTION_BOUNDARY_SCHEMA_VERSION = "scholar_ai_blocking_action_boundary_v1"
_ACTION_PREFLIGHT_FRESHNESS_SCHEMA_VERSION = "scholar_ai_action_preflight_freshness_v1"
_PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION = "scholar_ai_preflight_refresh_receipt_v1"
_WORKFLOW_REPLAY_LINEAGE_SCHEMA_VERSION = "scholar_ai_workflow_replay_lineage_v1"
_WORKFLOW_REPLAY_INDEX_SCHEMA_VERSION = "scholar_ai_workflow_replay_index_v1"
_ACTION_PREFLIGHT_MAX_AGE_SECONDS = 900
_AGENT_HANDOFF_CARD_KEY = "agent_handoff_card"
_PREFLIGHT_REFRESH_RECEIPTS_KEY = "preflight_refresh_receipts"
_WORKFLOW_ENFORCEMENT_SCHEMA_VERSION = "scholar_ai_workflow_enforcement_v1"
_READINESS_CLAIM_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "claim_id": "export_readiness",
        "label": "Export readiness",
        "required_readiness": ("has_export_manifest",),
        "required_signal_categories": ("export_readiness",),
        "blocked_by_categories": (
            "locator",
            "retrieval_quality",
            "citation_verification",
            "citation_overlap",
            "writing_lint",
            "export_readiness",
            "behavior_eval",
            "workflow_stage",
            "approval_boundary",
        ),
    },
    {
        "claim_id": "handoff_readiness",
        "label": "Agent handoff readiness",
        "required_readiness": (),
        "required_signal_categories": (),
        "blocked_by_categories": (
            "locator",
            "retrieval_quality",
            "citation_verification",
            "citation_overlap",
            "writing_lint",
            "export_readiness",
            "behavior_eval",
            "workflow_stage",
            "approval_boundary",
        ),
    },
)
_WORKFLOW_STAGE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "stage_id": "material_ingest",
        "label": "Material ingest",
        "required_artifacts": ["material_processing_task", "chunks", "locators"],
        "object_types": {"research_material"},
        "event_prefixes": ("material.ingest.", "material.parse.", "material.layout."),
        "next_action": "Create or complete a material-processing task for source materials.",
    },
    {
        "stage_id": "material_read",
        "label": "Material read",
        "required_artifacts": ["chunk_refs", "locator_coverage"],
        "object_types": {"figure_table_asset"},
        "event_prefixes": ("figure_table.", "material.read."),
        "next_action": "Review material chunks and locator coverage before evidence reuse.",
    },
    {
        "stage_id": "evidence_pack",
        "label": "Evidence pack",
        "required_artifacts": ["evidence_pack", "locator_coverage", "qrels_status"],
        "object_types": {"evidence_pack"},
        "event_prefixes": ("evidence.pack.",),
        "next_action": "Build an evidence pack with source locators and retrieval diagnostics.",
    },
    {
        "stage_id": "outline",
        "label": "Outline",
        "required_artifacts": ["outline"],
        "object_types": {"writing_job"},
        "workflow_phases": {"outline", "outline_ready", "planned_outline"},
        "next_action": "Create a structured outline linked to evidence refs.",
    },
    {
        "stage_id": "draft",
        "label": "Draft",
        "required_artifacts": ["draft", "writing_workflow_state"],
        "object_types": {"writing_job"},
        "workflow_phases": {"draft", "evidence_bound_draft", "draft_ready"},
        "next_action": "Persist a draft workflow state with evidence refs and change log.",
    },
    {
        "stage_id": "citation_review",
        "label": "Citation review",
        "required_artifacts": ["citation_bank", "lint_report", "integrity_gate"],
        "object_types": {"writing_job"},
        "workflow_phases": {"citation_review", "linted_export_ready", "export_ready"},
        "next_action": "Run citation, overlap, and writing-integrity checks.",
    },
    {
        "stage_id": "export",
        "label": "Export",
        "required_artifacts": ["export_manifest", "export_artifact"],
        "object_types": {"export_artifact"},
        "event_prefixes": ("writing.export.",),
        "workflow_phases": {"export_ready", "exported", "linted_export_ready"},
        "next_action": "Generate an export artifact only after unresolved checks are visible.",
    },
    {
        "stage_id": "agent_handoff",
        "label": "Agent handoff",
        "required_artifacts": ["agent_request", "handoff_card"],
        "object_types": {"agent_request"},
        "event_prefixes": ("agent.", "approval."),
        "next_action": "Create a bounded handoff card for the next agent session.",
    },
)
_RESEARCH_PRIVATE_PROJECTION_KEYS = {
    "api_key",
    "authorization",
    "content",
    "input_text",
    "messages",
    "prompt",
    "provider_payload",
    "raw_content",
    "response",
    "result",
    "secret",
    "text",
    "token",
    "trace",
}
_RESEARCH_STATE_KEYS = (
    "agent_request_id",
    "cache_policy",
    "chat_session_id",
    "discussion_run_id",
    "evidence_pack_id",
    "export_artifact_id",
    "figure_asset_id",
    "input_ref",
    "language_in",
    "language_out",
    "material_id",
    "mode",
    "output_targets",
    "page_range",
    "preserve",
    "processing_mode",
    "project_id",
    "request_id",
    "runtime_session_id",
    "scan_mode",
    "source",
    "source_path",
    "source_paths",
    "task_manifest_id",
    "task_type",
    "title",
)
_RESEARCH_EVENT_TYPE_BY_RUNTIME_EVENT = {
    EventType.JOB_CREATED.value: "research.object.created",
    EventType.JOB_STARTED.value: "research.object.started",
    EventType.JOB_PROGRESS.value: "research.object.progressed",
    EventType.TOOL_REQUESTED.value: "tool.requested",
    EventType.TOOL_BLOCKED.value: "tool.blocked",
    EventType.APPROVAL_REQUIRED.value: "approval.required",
    EventType.APPROVAL_GRANTED.value: "approval.granted",
    EventType.APPROVAL_REJECTED.value: "approval.rejected",
    EventType.ARTIFACT_CREATED.value: "artifact.created",
    EventType.ARTIFACT_UPDATED.value: "artifact.updated",
    EventType.JOB_PAUSED.value: "research.object.paused",
    EventType.JOB_RESUMED.value: "research.object.resumed",
    EventType.JOB_COMPLETED.value: "research.object.completed",
    EventType.JOB_FAILED.value: "research.object.failed",
    EventType.JOB_CANCELLED.value: "research.object.cancelled",
}
_RESEARCH_JOB_KIND_OBJECT_TYPES = {
    JobKind.RESOURCE_INGEST.value: "research_material",
    JobKind.FIGURE_LOAD.value: "figure_table_asset",
    JobKind.SMART_READ.value: "evidence_pack",
    JobKind.AGENT_REQUEST.value: "agent_request",
    JobKind.ARTIFACT_EXPORT.value: "export_artifact",
    JobKind.AI_REVIEW.value: "writing_job",
    JobKind.DISCUSSION.value: "writing_job",
    JobKind.PIPELINE_RUN.value: "writing_job",
    JobKind.PROMPT_ACTION.value: "writing_job",
    JobKind.SKILL_ACTION.value: "writing_job",
    JobKind.APPROVAL.value: "approval_gate",
}
_RESEARCH_JOB_EVENT_TYPES = {
    (JobKind.RESOURCE_INGEST.value, EventType.JOB_CREATED.value): "material.ingest.requested",
    (JobKind.RESOURCE_INGEST.value, EventType.JOB_STARTED.value): "material.ingest.started",
    (JobKind.RESOURCE_INGEST.value, EventType.JOB_PROGRESS.value): "material.ingest.progressed",
    (JobKind.RESOURCE_INGEST.value, EventType.JOB_COMPLETED.value): "material.ingest.completed",
    (JobKind.FIGURE_LOAD.value, EventType.JOB_COMPLETED.value): "figure_table.assets.loaded",
    (JobKind.SMART_READ.value, EventType.JOB_COMPLETED.value): "evidence.pack.created",
    (JobKind.AGENT_REQUEST.value, EventType.JOB_CREATED.value): "agent.request.created",
    (JobKind.AGENT_REQUEST.value, EventType.JOB_COMPLETED.value): "agent.result.accepted",
    (JobKind.ARTIFACT_EXPORT.value, EventType.JOB_COMPLETED.value): "writing.export.created",
}
_RESEARCH_OBJECT_ID_KEYS = {
    "agent_request": ("agent_request_id", "request_id", "runtime_request_id"),
    "approval_gate": ("approval_id",),
    "evidence_pack": ("evidence_pack_id", "evidence_pack_ref", "pack_id"),
    "export_artifact": ("export_artifact_id", "artifact_id", "export_id"),
    "figure_table_asset": ("figure_asset_id", "asset_id", "candidate_id"),
    "research_material": ("material_id", "source_material_id", "input_ref"),
    "research_project": ("project_id",),
    "runtime_artifact": ("artifact_id",),
    "writing_job": ("writing_job_id", "writing_task_id", "draft_id", "task_manifest_id"),
}


def _json_safe_copy(value: Any) -> Any:
    """Return a detached JSON-compatible copy of a runtime value."""

    try:
        return json.loads(json.dumps(copy.deepcopy(value), ensure_ascii=False))
    except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
        raise ValueError(f"value is not JSON serializable: {type(exc).__name__}") from exc


def _require_object(value: Any, *, field_name: str) -> dict[str, Any]:
    """Return a detached object for workflow-state object fields."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(_json_safe_copy(value))


def _require_object_list(value: Any, *, field_name: str) -> list[dict[str, Any]]:
    """Return detached object rows for workflow-state list fields."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{index}] must be an object")
        rows.append(dict(_json_safe_copy(item)))
    return rows


def _workflow_readiness(state: dict[str, Any]) -> dict[str, bool]:
    """Return deterministic readiness flags for writing workflow gates."""

    return {
        "has_intake": bool(state.get("intake")),
        "has_evidence_refs": bool(state.get("evidence_refs")),
        "has_citation_bank": bool(state.get("citation_bank")),
        "has_lint_report": bool(state.get("lint_report")),
        "has_export_manifest": bool(state.get("export_manifest")),
        "has_change_log": bool(state.get("change_log")),
    }


def _digest_json_payload(value: Any) -> str:
    """Return a stable digest for JSON-shaped runtime contract values."""

    safe_value = _json_safe_copy(value)
    encoded = json.dumps(
        safe_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_non_empty_string(value: Any, *, field_name: str, max_length: int | None = None) -> str:
    """Return a stripped non-empty string for contract identity fields."""

    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return normalized


def _optional_string(value: Any, *, field_name: str, max_length: int | None = None) -> str | None:
    """Return a stripped optional string while preserving empty as missing."""

    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if max_length is not None and len(normalized) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return normalized


def _coerce_non_negative_int(value: Any, *, field_name: str) -> int | None:
    """Return a non-negative integer for bounded artifact/task counters."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _coerce_positive_int(value: Any, *, field_name: str) -> int:
    """Return a positive 1-based integer for page ranges."""

    parsed = _coerce_non_negative_int(value, field_name=field_name)
    if parsed is None or parsed < 1:
        raise ValueError(f"{field_name} must be a positive 1-based integer")
    return parsed


def _coerce_contract_bool(value: Any, *, field_name: str) -> bool:
    """Return a boolean for explicit material-processing preserve flags."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


def _normalize_contract_choice(
    value: Any,
    *,
    field_name: str,
    allowed: set[str],
    default: str | None = None,
) -> str:
    """Return a lower-case enum-like string for local runtime contracts."""

    raw = default if value is None or value == "" else value
    normalized = _require_non_empty_string(raw, field_name=field_name).lower()
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return normalized


def _normalize_material_processing_page_range(value: Any) -> dict[str, Any]:
    """Return a validated page-selection object for material processing."""

    payload = _require_object(value, field_name="page_range")
    mode = _normalize_contract_choice(
        payload.get("mode"),
        field_name="page_range.mode",
        allowed={"all", "range", "pages"},
        default="all",
    )
    pages_raw = payload.get("pages") or []
    if not isinstance(pages_raw, list):
        raise ValueError("page_range.pages must be a list")
    pages = sorted(dict.fromkeys(_coerce_positive_int(page, field_name="page_range.pages[]") for page in pages_raw))
    start_page = (
        _coerce_positive_int(payload.get("start_page"), field_name="page_range.start_page")
        if payload.get("start_page") is not None
        else None
    )
    end_page = (
        _coerce_positive_int(payload.get("end_page"), field_name="page_range.end_page")
        if payload.get("end_page") is not None
        else None
    )
    if mode == "range":
        if start_page is None or end_page is None:
            raise ValueError("page_range range mode requires start_page and end_page")
        if end_page < start_page:
            raise ValueError("page_range.end_page must be greater than or equal to start_page")
    if mode == "pages" and not pages:
        raise ValueError("page_range pages mode requires at least one page")
    return {
        "mode": mode,
        "start_page": start_page,
        "end_page": end_page,
        "pages": pages,
    }


def _normalize_material_processing_preserve(value: Any) -> dict[str, bool]:
    """Return explicit preservation flags for document features."""

    payload = _require_object(value, field_name="preserve")
    return {
        key: _coerce_contract_bool(payload.get(key, True), field_name=f"preserve.{key}")
        for key in ("formulas", "tables", "figures", "citations", "annotations")
    }


def _normalize_material_processing_input_ref(value: Any, *, material_id: str) -> dict[str, Any]:
    """Return a bounded local input reference for a material-processing task."""

    payload = _require_object(value, field_name="input_ref")
    ref_material_id = _require_non_empty_string(
        payload.get("material_id"),
        field_name="input_ref.material_id",
        max_length=200,
    )
    if ref_material_id != material_id:
        raise ValueError("input_ref.material_id must match material_id")
    return {
        "ref_type": _require_non_empty_string(payload.get("ref_type", "material"), field_name="input_ref.ref_type", max_length=80),
        "material_id": ref_material_id,
        "source_path_label": _optional_string(payload.get("source_path_label"), field_name="input_ref.source_path_label", max_length=500),
        "content_digest": _optional_string(payload.get("content_digest"), field_name="input_ref.content_digest", max_length=160),
        "size_bytes": _coerce_non_negative_int(payload.get("size_bytes"), field_name="input_ref.size_bytes"),
    }


def _normalize_material_processing_output_targets(value: Any) -> list[str]:
    """Return unique output target names supported by the local task contract."""

    raw_targets = value if value is not None else ["chunks"]
    if not isinstance(raw_targets, list):
        raise ValueError("output_targets must be a list")
    targets = [
        _normalize_contract_choice(target, field_name="output_targets[]", allowed=_MATERIAL_PROCESSING_OUTPUT_TARGETS)
        for target in raw_targets
    ]
    if not targets:
        raise ValueError("output_targets must contain at least one target")
    return list(dict.fromkeys(targets))


def _normalize_material_processing_cache(
    value: Any,
    *,
    content_digest: str | None,
    parameter_digest: str,
) -> dict[str, Any]:
    """Return cache identity and decision metadata for replay diagnostics."""

    payload = _require_object(value, field_name="cache")
    policy = _normalize_contract_choice(
        payload.get("policy"),
        field_name="cache.policy",
        allowed=_MATERIAL_PROCESSING_CACHE_POLICIES,
        default="use",
    )
    decision = _normalize_contract_choice(
        payload.get("decision"),
        field_name="cache.decision",
        allowed=_MATERIAL_PROCESSING_CACHE_DECISIONS,
        default="pending",
    )
    digest = _optional_string(payload.get("content_digest"), field_name="cache.content_digest", max_length=160) or content_digest
    cache_key = _optional_string(payload.get("cache_key"), field_name="cache.cache_key", max_length=240)
    if cache_key is None:
        cache_key = f"material_processing:{digest or 'unknown-content'}:{parameter_digest}"
    return {
        "policy": policy,
        "content_digest": digest,
        "parameter_digest": parameter_digest,
        "cache_key": cache_key,
        "decision": decision,
    }


def _material_processing_artifact_family_summary(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return reproducible artifact-family facts without exposing local paths."""

    rows: list[dict[str, Any]] = []
    for artifact in artifacts[:16]:
        artifact_type = _safe_projection_string(artifact.get("artifact_type"))
        output_target = _safe_projection_string(artifact.get("output_target"))
        if artifact_type is None or output_target is None:
            continue
        row: dict[str, Any] = {
            "artifact_type": artifact_type,
            "output_target": output_target,
        }
        if artifact.get("count") is not None:
            row["count"] = _coerce_non_negative_int(artifact.get("count"), field_name="artifact_family.count")
        digest = _optional_string(artifact.get("digest"), field_name="artifact_family.digest", max_length=160)
        if digest:
            row["digest"] = digest
        row.update(_projection_path_summary(artifact.get("path")))
        rows.append(
            {
                key: _projection_value(value)
                for key, value in row.items()
                if not _is_blank_projection_value(value)
            }
        )
    return rows


def _build_material_processing_cache_decision_record(
    *,
    job: WritingJob,
    task_record: dict[str, Any],
    artifacts: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    """Build the cache/replay decision receipt for a material-processing task."""

    request = _require_object(task_record.get("request"), field_name="material_processing_task.request")
    cache = _require_object(task_record.get("cache"), field_name="material_processing_task.cache")
    decision = _normalize_contract_choice(
        cache.get("decision"),
        field_name="material_processing_task.cache.decision",
        allowed=_MATERIAL_PROCESSING_CACHE_DECISIONS,
        default="pending",
    )
    policy = _normalize_contract_choice(
        cache.get("policy"),
        field_name="material_processing_task.cache.policy",
        allowed=_MATERIAL_PROCESSING_CACHE_POLICIES,
        default="use",
    )
    input_ref = _require_object(request.get("input_ref"), field_name="material_processing_task.request.input_ref")
    output_targets = _normalize_material_processing_output_targets(request.get("output_targets"))
    artifact_family = _material_processing_artifact_family_summary(artifacts)
    has_all_requested_outputs = bool(output_targets) and {str(item.get("output_target")) for item in artifact_family} >= set(output_targets)
    reasons = {
        "pending": "Processing has not recorded a cache outcome yet.",
        "hit": "Existing artifacts matched the content and parameter identity.",
        "miss": "No reusable artifact matched the content and parameter identity; new outputs were generated.",
        "bypass": "Cache lookup was skipped by the task policy.",
        "refresh": "The task policy requested regeneration despite a stable cache identity.",
        "invalidated": "A prior cached artifact was invalidated by changed inputs, parameters, or warnings.",
    }
    replayable = bool(cache.get("cache_key") and cache.get("parameter_digest") and decision not in {"pending", "invalidated"})
    receipt_seed = {
        "schema_version": _MATERIAL_PROCESSING_CACHE_DECISION_SCHEMA_VERSION,
        "job_id": job.job_id,
        "cache_key": cache.get("cache_key"),
        "decision": decision,
        "status": task_record.get("status"),
        "artifact_family": artifact_family,
        "warnings": warnings[:12],
    }
    return {
        "schema_version": _MATERIAL_PROCESSING_CACHE_DECISION_SCHEMA_VERSION,
        "decision_id": f"material-cache-decision:{hashlib.sha256(_digest_json_payload(receipt_seed).encode('utf-8')).hexdigest()[:24]}",
        "generated_at": str(task_record.get("updated_at") or utc_now_iso_z()),
        "job_id": job.job_id,
        "session_id": job.session_id,
        "project_id": request.get("project_id"),
        "material_id": request.get("material_id"),
        "policy": policy,
        "decision": decision,
        "reason": reasons.get(decision, "Cache decision was recorded by the material-processing task."),
        "replayable": replayable,
        "content_digest": cache.get("content_digest") or input_ref.get("content_digest"),
        "parameter_digest": cache.get("parameter_digest"),
        "cache_key": cache.get("cache_key"),
        "processing_mode": request.get("processing_mode"),
        "page_range": _json_safe_copy(request.get("page_range") or {}),
        "output_targets": output_targets,
        "artifact_family": artifact_family,
        "artifact_family_digest": _digest_json_payload(artifact_family),
        "warning_count": len(warnings),
        "has_all_requested_outputs": has_all_requested_outputs,
        "provenance": {
            "derived_from": [
                "runtime.job_metadata.material_processing_task",
                "runtime.artifacts.material_processing_task",
            ],
            "runtime_job_id": job.job_id,
            "source_material_mutation": False,
            "external_mutation": False,
            "standard_patterns": [
                "W3C PROV activity/entity generation",
                "Workflow Run RO-Crate workflow outputs",
                "Python json stable serialization with SHA-256 digest",
            ],
        },
    }


def _normalize_material_processing_request(value: Any) -> dict[str, Any]:
    """Return a versioned material-processing request with computed cache identity."""

    payload = _require_object(value, field_name="material_processing_task.request")
    schema_version = _require_non_empty_string(payload.get("schema_version", _MATERIAL_PROCESSING_SCHEMA_VERSION), field_name="schema_version")
    if schema_version != _MATERIAL_PROCESSING_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_MATERIAL_PROCESSING_SCHEMA_VERSION}")
    project_id = _require_non_empty_string(payload.get("project_id"), field_name="project_id", max_length=200)
    material_id = _require_non_empty_string(payload.get("material_id"), field_name="material_id", max_length=200)
    input_ref = _normalize_material_processing_input_ref(payload.get("input_ref"), material_id=material_id)
    page_range = _normalize_material_processing_page_range(payload.get("page_range"))
    preserve = _normalize_material_processing_preserve(payload.get("preserve"))
    cache_seed = _require_object(payload.get("cache"), field_name="cache")
    cache_policy = _normalize_contract_choice(
        cache_seed.get("policy"),
        field_name="cache.policy",
        allowed=_MATERIAL_PROCESSING_CACHE_POLICIES,
        default="use",
    )
    output_targets = _normalize_material_processing_output_targets(payload.get("output_targets"))
    request_without_cache_decisions: dict[str, Any] = {
        "schema_version": schema_version,
        "project_id": project_id,
        "material_id": material_id,
        "input_ref": input_ref,
        "page_range": page_range,
        "processing_mode": _normalize_contract_choice(
            payload.get("processing_mode"),
            field_name="processing_mode",
            allowed=_MATERIAL_PROCESSING_ALLOWED_MODES,
            default="fast_text",
        ),
        "language_in": _optional_string(payload.get("language_in"), field_name="language_in", max_length=40),
        "language_out": _optional_string(payload.get("language_out"), field_name="language_out", max_length=40),
        "preserve": preserve,
        "provider_ref": _optional_string(payload.get("provider_ref"), field_name="provider_ref", max_length=200),
        "cache": {"policy": cache_policy},
        "output_targets": output_targets,
        "metadata": _require_object(payload.get("metadata"), field_name="metadata"),
    }
    parameter_digest = _digest_json_payload(request_without_cache_decisions)
    request_without_cache_decisions["cache"] = _normalize_material_processing_cache(
        cache_seed,
        content_digest=input_ref.get("content_digest"),
        parameter_digest=parameter_digest,
    )
    return request_without_cache_decisions


def _normalize_material_processing_artifacts(value: Any) -> list[dict[str, Any]]:
    """Return typed artifact summaries for a material-processing task."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("artifacts must be a list")
    artifacts: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        payload = _require_object(item, field_name=f"artifacts[{index}]")
        output_target = _normalize_contract_choice(
            payload.get("output_target"),
            field_name=f"artifacts[{index}].output_target",
            allowed=_MATERIAL_PROCESSING_OUTPUT_TARGETS,
        )
        artifacts.append(
            {
                "artifact_type": _require_non_empty_string(
                    payload.get("artifact_type"),
                    field_name=f"artifacts[{index}].artifact_type",
                    max_length=120,
                ),
                "output_target": output_target,
                "count": _coerce_non_negative_int(payload.get("count"), field_name=f"artifacts[{index}].count"),
                "path": _optional_string(payload.get("path"), field_name=f"artifacts[{index}].path", max_length=1000),
                "digest": _optional_string(payload.get("digest"), field_name=f"artifacts[{index}].digest", max_length=160),
                "metadata": _require_object(payload.get("metadata"), field_name=f"artifacts[{index}].metadata"),
            }
        )
    return artifacts


def _normalize_material_processing_warnings(value: Any) -> list[str]:
    """Return bounded warning text rows for a material-processing task."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("warnings must be a list")
    warnings: list[str] = []
    for index, item in enumerate(value):
        warning = _optional_string(item, field_name=f"warnings[{index}]", max_length=1000)
        if warning:
            warnings.append(warning)
    return warnings


def _normalize_material_processing_status(value: Any) -> str:
    """Return a task status compatible with runtime job lifecycle summaries."""

    return _normalize_contract_choice(
        value,
        field_name="material_processing_task.status",
        allowed=_MATERIAL_PROCESSING_TASK_STATUSES,
        default="queued",
    )


def _is_blank_projection_value(value: Any) -> bool:
    """Return True for values that should not become projection facts."""

    return value is None or value == "" or value == [] or value == {}


def _safe_projection_string(value: Any) -> str | None:
    """Return a trimmed string for stable ids and labels."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _projection_path_summary(value: Any) -> dict[str, Any]:
    """Return an irreversible local-path summary for audit projections."""

    text = _safe_projection_string(value)
    if text is None:
        return {}
    return {
        "path_present": True,
        "path_kind": "absolute" if Path(text).is_absolute() else "relative",
        "path_digest": f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
    }


def _metadata_string(metadata: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty string value from runtime metadata."""

    for key in keys:
        value = _safe_projection_string(metadata.get(key))
        if value:
            return value
    return None


def _projection_value(value: Any) -> Any:
    """Return a bounded JSON-safe value for read-only projection metadata."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(key): _projection_value(item)
            for key, item in value.items()
            if str(key).lower() not in _RESEARCH_PRIVATE_PROJECTION_KEYS
        }
    if isinstance(value, list):
        if len(value) <= 8 and all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
            return list(value)
        return {"count": len(value)}
    return str(value)


def _compact_projection_mapping(mapping: dict[str, Any], *, allowed_keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Return a JSON-safe public subset of metadata for audit projection."""

    keys = allowed_keys or tuple(mapping.keys())
    compact: dict[str, Any] = {}
    for key in keys:
        if key not in mapping:
            continue
        normalized_key = str(key)
        if normalized_key.lower() in _RESEARCH_PRIVATE_PROJECTION_KEYS:
            continue
        value = mapping.get(key)
        if _is_blank_projection_value(value):
            continue
        compact[normalized_key] = _projection_value(value)
    return compact


def _increment_projection_count(counter: dict[str, int], key: str) -> None:
    """Increment a deterministic projection counter."""

    normalized = _safe_projection_string(key)
    if normalized is None:
        return
    counter[normalized] = int(counter.get(normalized, 0)) + 1


def _append_unique_text(values: list[str], value: Any, *, max_items: int = 48) -> None:
    """Append a bounded string only once to a stage ledger list."""

    if len(values) >= max_items:
        return
    normalized = _safe_projection_string(value)
    if normalized is None or normalized in values:
        return
    values.append(normalized)


def _append_unique_mapping(values: list[dict[str, Any]], value: dict[str, Any], *, max_items: int = 24) -> None:
    """Append a bounded mapping only once to a stage ledger list."""

    if len(values) >= max_items:
        return
    compact = dict(_json_safe_copy(value))
    if compact in values:
        return
    values.append(compact)


def _passport_status_from_runtime_status(status: Any) -> str:
    """Map runtime/object status values to passport stage progress."""

    normalized = str(status or "").strip().lower()
    if normalized in {"completed", "succeeded", "active", "referenced"}:
        return "complete"
    if normalized in {"failed", "approval_rejected", "cancelled"}:
        return "blocked"
    if normalized in {"queued", "created", "started", "running", "in_progress", "paused", "approval_pending"}:
        return "in_progress"
    return "unresolved"


def _passport_status_from_event(event_type: str, status: Any) -> str:
    """Map domain event facts to passport stage progress."""

    if event_type.endswith(".failed") or event_type.endswith(".rejected"):
        return "blocked"
    if event_type.endswith(".completed") or event_type in {
        "agent.result.accepted",
        "artifact.created",
        "evidence.pack.created",
        "figure_table.assets.loaded",
        "writing.export.created",
    }:
        return "complete"
    if event_type.endswith(".started") or event_type.endswith(".requested") or event_type.endswith(".progressed"):
        return "in_progress"
    return _passport_status_from_runtime_status(status)


def _strongest_passport_status(current: str, candidate: str) -> str:
    """Return the most actionable stage status from two observations."""

    rank = {
        "not_started": 0,
        "in_progress": 1,
        "complete": 2,
        "unresolved": 3,
        "warn": 4,
        "blocked": 5,
    }
    return candidate if rank.get(candidate, 0) > rank.get(current, 0) else current


def _stage_matches_workflow_state(stage: dict[str, Any], state: dict[str, Any]) -> bool:
    """Return true when a writing workflow state belongs to one passport stage."""

    phases = stage.get("workflow_phases")
    if not isinstance(phases, set):
        return False
    phase = _safe_projection_string(state.get("phase"))
    if phase and phase in phases:
        return True
    readiness = state.get("readiness")
    if not isinstance(readiness, dict):
        return False
    stage_id = stage.get("stage_id")
    if stage_id == "draft":
        return bool(readiness.get("has_evidence_refs"))
    if stage_id == "citation_review":
        return bool(readiness.get("has_citation_bank") or readiness.get("has_lint_report"))
    if stage_id == "export":
        return bool(readiness.get("has_export_manifest"))
    return False


def _stage_matches_event(stage: dict[str, Any], event_type: str) -> bool:
    """Return true when an event type belongs to a passport stage."""

    prefixes = stage.get("event_prefixes")
    if not isinstance(prefixes, tuple):
        return False
    return any(event_type.startswith(prefix) for prefix in prefixes)


def _material_processing_artifact_refs(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Return bounded material-processing artifact facts for passport stages."""

    refs: list[dict[str, Any]] = []
    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list):
        return refs
    for artifact in artifacts[:16]:
        if not isinstance(artifact, dict):
            continue
        ref: dict[str, Any] = {
            "artifact_type": artifact.get("artifact_type"),
            "output_target": artifact.get("output_target"),
        }
        for key in ("count", "digest"):
            if artifact.get(key) is not None:
                ref[key] = artifact.get(key)
        ref.update(_projection_path_summary(artifact.get("path")))
        refs.append(
            {
                key: _projection_value(value)
                for key, value in ref.items()
                if not _is_blank_projection_value(value)
            }
        )
    return refs


def _material_processing_target_count(task: dict[str, Any], output_targets: set[str]) -> int:
    """Return how many persisted task artifacts match the requested targets."""

    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list):
        return 0
    count = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        target = _safe_projection_string(artifact.get("output_target"))
        artifact_type = _safe_projection_string(artifact.get("artifact_type"))
        if target in output_targets or artifact_type in output_targets:
            count += 1
    return count


def _passport_gate_for_stage(stage: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Build a gate row for a workflow passport stage."""

    stage_id = str(stage["stage_id"])
    evidence: list[dict[str, Any]] = []
    for object_id in row.get("object_ids", [])[:8]:
        evidence.append({"ref_type": "research_object", "ref_id": object_id})
    for event_type in row.get("event_types", [])[:8]:
        evidence.append({"ref_type": "research_event_type", "ref_id": event_type})
    blockers = list(row.get("blockers", []))[:12]
    unresolved = list(row.get("unresolved", []))[:12]
    requires_user_confirmation = bool(row.get("requires_user_confirmation"))
    diagnostics = row.get("diagnostics") if isinstance(row.get("diagnostics"), dict) else {}
    preflight_receipt_count = int(diagnostics.get("preflight_receipt_count") or 0)
    preflight_blocker_count = int(diagnostics.get("blocker_count") or 0)
    preflight_unresolved_count = int(diagnostics.get("unresolved_count") or 0)
    if preflight_blocker_count > 0:
        blockers.append(
            f"{preflight_blocker_count} preflight blocker(s) remain in the latest gate refresh receipt."
        )
    if preflight_receipt_count > 0 and preflight_unresolved_count > 0:
        unresolved.append(
            f"{preflight_unresolved_count} preflight unresolved check(s) remain in the latest gate refresh receipt."
        )
    status = str(row.get("status") or "not_started")
    if requires_user_confirmation:
        gate_status = "block"
        severity = "block"
        reason = "Pending user confirmation blocks this stage."
    elif blockers:
        gate_status = "block"
        severity = "block"
        reason = blockers[0]
    elif unresolved:
        gate_status = "unresolved"
        severity = "warn"
        reason = unresolved[0]
    elif status == "complete":
        gate_status = "pass"
        severity = "none"
        reason = "Required runtime evidence is present for this stage."
    elif status == "not_started":
        gate_status = "not_applicable"
        severity = "note"
        reason = "No runtime evidence has been recorded for this stage yet."
    else:
        gate_status = "unresolved"
        severity = "note"
        reason = "Stage is in progress and still needs completion evidence."
    return {
        "gate_id": f"{stage_id}.gate",
        "status": gate_status,
        "severity": severity,
        "reason": reason,
        "evidence": evidence[:16],
        "blockers": blockers,
        "unresolved": unresolved,
        "requires_user_confirmation": requires_user_confirmation,
    }


def _new_passport_diagnostics() -> dict[str, Any]:
    """Return empty bounded counters for one workflow-passport stage."""

    return {
        "artifact_count": 0,
        "task_count": 0,
        "event_count": 0,
        "locator_coverage_count": 0,
        "qrels_status_count": 0,
        "preflight_receipt_count": 0,
        "warning_count": 0,
        "status_counts": {},
        "cache_decisions": {},
        "locator_risk_counts": {},
        "unresolved_count": 0,
        "blocker_count": 0,
    }


def _new_passport_reproducibility() -> dict[str, Any]:
    """Return empty replay/cache evidence for one workflow-passport stage."""

    return {
        "read_only": True,
        "source_material_mutation": False,
        "external_mutation": False,
        "task_refs": [],
        "artifact_refs": [],
        "cache_refs": [],
        "cache_decision_refs": [],
        "locator_refs": [],
        "qrels_refs": [],
        "preflight_receipts": [],
        "projection_digest_keys": [],
        "replay_probe_refs": [],
        "parameter_digest_count": 0,
        "cache_key_count": 0,
        "cache_decision_record_count": 0,
    }


def _increment_nested_count(container: dict[str, Any], bucket: str, key: Any) -> None:
    """Increment a nested count in a stage diagnostics mapping."""

    normalized = _safe_projection_string(key)
    if normalized is None:
        return
    target = container.get(bucket)
    if not isinstance(target, dict):
        target = {}
        container[bucket] = target
    target[normalized] = int(target.get(normalized, 0)) + 1


def _trim_passport_stage_projection(row: dict[str, Any]) -> None:
    """Bound optional diagnostics and replay facts before response validation."""

    diagnostics = row.get("diagnostics")
    if isinstance(diagnostics, dict):
        for key in ("status_counts", "cache_decisions", "locator_risk_counts"):
            value = diagnostics.get(key)
            if isinstance(value, dict):
                diagnostics[key] = dict(sorted(value.items(), key=lambda item: str(item[0]))[:16])
        for key in (
            "artifact_count",
            "task_count",
            "event_count",
            "locator_coverage_count",
            "qrels_status_count",
            "preflight_receipt_count",
            "warning_count",
            "unresolved_count",
            "blocker_count",
            "parameter_digest_count",
            "cache_key_count",
            "cache_decision_record_count",
        ):
            if key in diagnostics:
                try:
                    diagnostics[key] = max(0, int(diagnostics[key]))
                except (TypeError, ValueError):
                    diagnostics[key] = 0

    reproducibility = row.get("reproducibility")
    if isinstance(reproducibility, dict):
        for key in (
            "task_refs",
            "artifact_refs",
            "cache_refs",
            "cache_decision_refs",
            "locator_refs",
            "qrels_refs",
            "preflight_receipts",
            "replay_probe_refs",
        ):
            value = reproducibility.get(key)
            if isinstance(value, list):
                reproducibility[key] = value[:16]
            else:
                reproducibility[key] = []
        digest_keys = reproducibility.get("projection_digest_keys")
        if isinstance(digest_keys, list):
            reproducibility["projection_digest_keys"] = sorted(dict.fromkeys(str(item) for item in digest_keys if str(item).strip()))[:16]
        else:
            reproducibility["projection_digest_keys"] = []
        for key in ("parameter_digest_count", "cache_key_count", "cache_decision_record_count"):
            try:
                reproducibility[key] = max(0, int(reproducibility.get(key) or 0))
            except (TypeError, ValueError):
                reproducibility[key] = 0


def _record_passport_stage_event(row: dict[str, Any], event_type: str) -> None:
    """Attach a runtime event type to a stage's diagnostics."""

    diagnostics = row.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return
    diagnostics["event_count"] = int(diagnostics.get("event_count") or 0) + 1
    _increment_nested_count(diagnostics, "status_counts", event_type)


def _record_passport_workflow_state(row: dict[str, Any], job_id: str, workflow_state: dict[str, Any]) -> None:
    """Attach writing-state readiness facts to one passport stage."""

    diagnostics = row.get("diagnostics")
    reproducibility = row.get("reproducibility")
    if not isinstance(diagnostics, dict) or not isinstance(reproducibility, dict):
        return
    readiness = workflow_state.get("readiness") if isinstance(workflow_state.get("readiness"), dict) else {}
    evidence_refs = workflow_state.get("evidence_refs")
    citation_bank = workflow_state.get("citation_bank")
    change_log = workflow_state.get("change_log")
    diagnostics["artifact_count"] = int(diagnostics.get("artifact_count") or 0) + 1
    _append_unique_mapping(
        reproducibility["task_refs"],
        {
            "ref_type": "runtime_job",
            "ref_id": job_id,
            "artifact_type": _WRITING_WORKFLOW_STATE_KEY,
            "phase": workflow_state.get("phase"),
        },
    )
    for key, value in readiness.items():
        if key.startswith("has_"):
            _increment_nested_count(diagnostics, "status_counts", f"{key}:{bool(value)}")
    if isinstance(evidence_refs, list):
        diagnostics["evidence_ref_count"] = int(diagnostics.get("evidence_ref_count") or 0) + len(evidence_refs)
    if isinstance(citation_bank, list):
        diagnostics["citation_count"] = int(diagnostics.get("citation_count") or 0) + len(citation_bank)
    if isinstance(change_log, list):
        diagnostics["change_log_count"] = int(diagnostics.get("change_log_count") or 0) + len(change_log)


def _record_passport_material_task(row: dict[str, Any], job_id: str, task: dict[str, Any]) -> None:
    """Attach task/cache/artifact facts from a material-processing record."""

    diagnostics = row.get("diagnostics")
    reproducibility = row.get("reproducibility")
    if not isinstance(diagnostics, dict) or not isinstance(reproducibility, dict):
        return
    request = task.get("request") if isinstance(task.get("request"), dict) else {}
    cache = task.get("cache") if isinstance(task.get("cache"), dict) else {}
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), list) else []
    warnings = task.get("warnings") if isinstance(task.get("warnings"), list) else []
    status = _safe_projection_string(task.get("status")) or "unknown"
    diagnostics["task_count"] = int(diagnostics.get("task_count") or 0) + 1
    diagnostics["artifact_count"] = int(diagnostics.get("artifact_count") or 0) + len(artifacts)
    diagnostics["warning_count"] = int(diagnostics.get("warning_count") or 0) + len(warnings)
    _increment_nested_count(diagnostics, "status_counts", status)
    _increment_nested_count(diagnostics, "cache_decisions", cache.get("decision"))
    _append_unique_mapping(
        reproducibility["task_refs"],
        {
            "ref_type": "runtime_job",
            "ref_id": job_id,
            "artifact_type": _MATERIAL_PROCESSING_TASK_KEY,
            "status": status,
            "processing_mode": request.get("processing_mode"),
            "material_id": request.get("material_id"),
        },
    )
    cache_ref = {
        "ref_type": "material_processing_cache",
        "ref_id": cache.get("cache_key") or job_id,
        "policy": cache.get("policy"),
        "decision": cache.get("decision"),
        "content_digest": cache.get("content_digest"),
        "parameter_digest": cache.get("parameter_digest"),
    }
    _append_unique_mapping(
        reproducibility["cache_refs"],
        {
            key: _projection_value(value)
            for key, value in cache_ref.items()
            if not _is_blank_projection_value(value)
        },
    )
    decision_record = cache.get("decision_record") if isinstance(cache.get("decision_record"), dict) else {}
    if decision_record:
        _append_unique_mapping(
            reproducibility["cache_decision_refs"],
            {
                key: _projection_value(value)
                for key, value in {
                    "ref_type": "material_processing_cache_decision",
                    "ref_id": decision_record.get("decision_id"),
                    "decision": decision_record.get("decision"),
                    "policy": decision_record.get("policy"),
                    "replayable": decision_record.get("replayable"),
                    "reason": decision_record.get("reason"),
                    "artifact_family_digest": decision_record.get("artifact_family_digest"),
                    "has_all_requested_outputs": decision_record.get("has_all_requested_outputs"),
                }.items()
                if not _is_blank_projection_value(value)
            },
        )
        reproducibility["cache_decision_record_count"] = int(reproducibility.get("cache_decision_record_count") or 0) + 1
    if _safe_projection_string(cache.get("parameter_digest")):
        reproducibility["parameter_digest_count"] = int(reproducibility.get("parameter_digest_count") or 0) + 1
    if _safe_projection_string(cache.get("cache_key")):
        reproducibility["cache_key_count"] = int(reproducibility.get("cache_key_count") or 0) + 1
    for artifact_ref in _material_processing_artifact_refs(task):
        _append_unique_mapping(reproducibility["artifact_refs"], artifact_ref)


def _record_passport_integrity_payload(row: dict[str, Any], source_id: str, payload: dict[str, Any]) -> None:
    """Attach locator and qrels evidence discovered in runtime metadata."""

    diagnostics = row.get("diagnostics")
    reproducibility = row.get("reproducibility")
    if not isinstance(diagnostics, dict) or not isinstance(reproducibility, dict):
        return
    for locator_source_id, locator_payload in _extract_locator_payloads(source_id, payload):
        diagnostics["locator_coverage_count"] = int(diagnostics.get("locator_coverage_count") or 0) + 1
        _increment_nested_count(diagnostics, "locator_risk_counts", locator_payload.get("risk_level"))
        _append_unique_mapping(
            reproducibility["locator_refs"],
            {
                "ref_type": "locator_coverage",
                "ref_id": locator_source_id,
                **_compact_projection_mapping(
                    locator_payload,
                    allowed_keys=(
                        "coverage_state",
                        "risk_level",
                        "project_ref_count",
                        "page_locator_count",
                        "bbox_locator_count",
                        "bbox_unit_counts",
                        "source_label_coverage_ratio",
                        "figure_table_locator_count",
                    ),
                ),
            },
        )
    for qrels_source_id, qrels_payload in _extract_qrels_payloads(source_id, payload):
        diagnostics["qrels_status_count"] = int(diagnostics.get("qrels_status_count") or 0) + 1
        _append_unique_mapping(
            reproducibility["qrels_refs"],
            {
                "ref_type": "qrels_status",
                "ref_id": qrels_source_id,
                **_compact_projection_mapping(
                    qrels_payload,
                    allowed_keys=("status", "quality_claim", "semantic_quality_claim_allowed"),
                ),
            },
        )


def _record_passport_preflight_receipts(
    row: dict[str, Any],
    job: "WritingJob",
    artifacts_by_job: dict[str, list["WritingArtifact"]],
) -> None:
    """Attach replay receipt facts proving prior gate refreshes are recoverable."""

    diagnostics = row.get("diagnostics")
    reproducibility = row.get("reproducibility")
    if not isinstance(diagnostics, dict) or not isinstance(reproducibility, dict):
        return
    receipts, receipt_counts = _collect_job_preflight_receipts(job, artifacts_by_job.get(job.job_id, []))
    if not receipts:
        return
    diagnostics["preflight_receipt_count"] = int(diagnostics.get("preflight_receipt_count") or 0) + len(receipts)
    latest = receipts[-1]
    counts = _receipt_validation_counts(latest)
    diagnostics["blocker_count"] = int(diagnostics.get("blocker_count") or 0) + counts["blocker_count"]
    diagnostics["unresolved_count"] = int(diagnostics.get("unresolved_count") or 0) + counts["unresolved_count"]
    projection_digests = latest.get("projection_digests")
    if isinstance(projection_digests, dict):
        for key in projection_digests:
            _append_unique_text(reproducibility["projection_digest_keys"], key, max_items=16)
    _append_unique_mapping(
        reproducibility["preflight_receipts"],
        {
            "ref_type": "preflight_refresh_receipt",
            "ref_id": latest.get("receipt_id"),
            "status": latest.get("status"),
            "generated_at": latest.get("generated_at"),
            "action_id": latest.get("action_id"),
            "blocker_count": counts["blocker_count"],
            "unresolved_count": counts["unresolved_count"],
            "metadata_receipt_count": receipt_counts.get("metadata_receipt_count"),
            "artifact_receipt_count": receipt_counts.get("artifact_receipt_count"),
        },
    )
    _append_unique_mapping(
        reproducibility["replay_probe_refs"],
        _handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{job.job_id}/workflow-replay-lineage"),
    )


def _integrity_signal(
    *,
    signal_id: str,
    category: str,
    status: str,
    severity: str,
    message: str,
    evidence: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    drilldown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one bounded evidence-integrity signal."""

    normalized_id = _require_non_empty_string(signal_id, field_name="signal_id", max_length=200)
    normalized_message = _require_non_empty_string(message, field_name="message", max_length=600)
    return {
        "signal_id": normalized_id,
        "category": category,
        "status": status,
        "severity": severity,
        "message": normalized_message,
        "evidence": list(evidence or [])[:16],
        "next_actions": list(next_actions or [])[:8],
        "metadata": dict(_json_safe_copy(metadata or {})),
        "drilldown": dict(_json_safe_copy(drilldown or {})),
    }


def _integrity_source_ref(source_id: str, *, source_kind: str) -> dict[str, Any]:
    """Return a bounded, path-safe source reference for drilldown payloads."""

    normalized = _require_non_empty_string(source_id, field_name="source_id", max_length=240)
    return {
        "source_id": normalized,
        "source_kind": _require_non_empty_string(source_kind, field_name="source_kind", max_length=80),
        "source_digest": _digest_json_payload(normalized),
        "raw_path_exposed": False,
    }


def _integrity_payload_drilldown(
    *,
    source_id: str,
    source_kind: str,
    status: str,
    checked_facts: dict[str, Any],
    evidence_refs: list[dict[str, Any]] | None = None,
    replay_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return repeatable facts that explain one integrity signal without raw paths."""

    facts = _compact_projection_mapping(checked_facts)
    return {
        "schema_version": "scholar_ai_integrity_signal_drilldown_v1",
        "status": status,
        "source_ref": _integrity_source_ref(source_id, source_kind=source_kind),
        "checked_facts": facts,
        "evidence_refs": list(evidence_refs or [])[:12],
        "replay_refs": list(replay_refs or [])[:8],
        "requires_human_review": status == "unresolved",
        "blocks_claims": status == "block",
    }


def _workflow_stage_drilldown(stage: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    """Return stage-level facts from the workflow passport for gate explainability."""

    stage_id = _safe_projection_string(stage.get("stage_id")) or "unknown"
    diagnostics = stage.get("diagnostics") if isinstance(stage.get("diagnostics"), dict) else {}
    reproducibility = stage.get("reproducibility") if isinstance(stage.get("reproducibility"), dict) else {}
    evidence_refs = list(gate.get("evidence") or [])[:12]
    replay_refs: list[dict[str, Any]] = []
    for key in ("preflight_receipts", "replay_probe_refs", "locator_refs", "qrels_refs"):
        values = reproducibility.get(key)
        if not isinstance(values, list):
            continue
        for item in values[:6]:
            if isinstance(item, dict):
                _append_unique_mapping(replay_refs, item, max_items=8)
    checked_facts = {
        "stage_id": stage_id,
        "stage_status": stage.get("status"),
        "gate_status": gate.get("status"),
        "gate_severity": gate.get("severity"),
        "required_artifact_count": len(stage.get("required_artifacts") or []),
        "present_artifact_count": len(stage.get("present_artifacts") or []),
        "object_count": len(stage.get("object_ids") or []),
        "event_type_count": len(stage.get("event_types") or []),
        "artifact_count": diagnostics.get("artifact_count"),
        "task_count": diagnostics.get("task_count"),
        "locator_coverage_count": diagnostics.get("locator_coverage_count"),
        "qrels_status_count": diagnostics.get("qrels_status_count"),
        "preflight_receipt_count": diagnostics.get("preflight_receipt_count"),
        "unresolved_count": diagnostics.get("unresolved_count"),
        "blocker_count": diagnostics.get("blocker_count"),
        "parameter_digest_count": reproducibility.get("parameter_digest_count"),
        "cache_key_count": reproducibility.get("cache_key_count"),
        "projection_digest_keys": reproducibility.get("projection_digest_keys"),
        "requires_user_confirmation": gate.get("requires_user_confirmation"),
    }
    return _integrity_payload_drilldown(
        source_id=f"workflow_passport:{stage_id}",
        source_kind="workflow_passport_stage",
        status=str(gate.get("status") or "unresolved"),
        checked_facts=checked_facts,
        evidence_refs=evidence_refs,
        replay_refs=replay_refs,
    )


def _integrity_status_rank(status: str) -> int:
    """Return aggregate severity rank for integrity gate states."""

    return {
        "not_applicable": 0,
        "pass": 1,
        "warn": 2,
        "unresolved": 3,
        "block": 4,
    }.get(status, 0)


def _integrity_gate_status(signals: list[dict[str, Any]]) -> str:
    """Return aggregate gate status without treating unresolved as pass."""

    if not signals:
        return "unresolved"
    statuses = [str(signal.get("status") or "unresolved") for signal in signals]
    if "block" in statuses:
        return "block"
    if "unresolved" in statuses:
        return "unresolved"
    if "warn" in statuses:
        return "warn"
    if any(status == "pass" for status in statuses):
        return "pass"
    return "unresolved"


def _integrity_signal_sort_key(signal: dict[str, Any]) -> tuple[int, str, str]:
    """Sort integrity signals by actionability and stable identity."""

    return (
        -_integrity_status_rank(str(signal.get("status") or "")),
        str(signal.get("category") or ""),
        str(signal.get("signal_id") or ""),
    )


def _bounded_signal_evidence(ref_type: str, ref_id: Any, **metadata: Any) -> list[dict[str, Any]]:
    """Return one compact evidence ref for a gate signal."""

    normalized_ref_id = _safe_projection_string(ref_id)
    if normalized_ref_id is None:
        return []
    row = {
        "ref_type": ref_type,
        "ref_id": normalized_ref_id,
        **{
            str(key): _projection_value(value)
            for key, value in metadata.items()
            if not _is_blank_projection_value(value)
        },
    }
    return [row]


def _signals_for_categories(signals: list[dict[str, Any]], categories: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return integrity signals matching one claim category set."""

    category_set = set(categories)
    return [
        signal
        for signal in signals
        if isinstance(signal, dict) and str(signal.get("category") or "") in category_set
    ]


def _merge_claim_signals(*signal_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a stable union of claim-scoped signals by signal id."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signals in signal_groups:
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            signal_id = str(signal.get("signal_id") or "")
            if not signal_id or signal_id in seen:
                continue
            seen.add(signal_id)
            merged.append(signal)
    return merged


def _claim_signal_status(signals: list[dict[str, Any]]) -> str:
    """Return the strongest gate status for claim-scoped signals."""

    return _integrity_gate_status(signals) if signals else "unresolved"


def _bounded_claim_messages(signals: list[dict[str, Any]], statuses: set[str], *, max_items: int = 8) -> list[str]:
    """Return stable bounded messages for claim blockers or unresolved checks."""

    messages: list[str] = []
    for signal in signals:
        if str(signal.get("status") or "") not in statuses:
            continue
        _append_unique_text(messages, signal.get("message"), max_items=max_items)
    return messages


def _bounded_claim_evidence(signals: list[dict[str, Any]], *, max_items: int = 12) -> list[dict[str, Any]]:
    """Return bounded evidence refs proving why a readiness claim is held back."""

    evidence: list[dict[str, Any]] = []
    for signal in signals:
        signal_id = _safe_projection_string(signal.get("signal_id"))
        category = _safe_projection_string(signal.get("category"))
        status = _safe_projection_string(signal.get("status"))
        if signal_id is None:
            continue
        _append_unique_mapping(
            evidence,
            {
                "ref_type": "evidence_integrity_signal",
                "ref_id": signal_id,
                "category": category,
                "status": status,
            },
            max_items=max_items,
        )
        if len(evidence) >= max_items:
            break
    return evidence


def _blocking_boundary_local_probes(*, action_id: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Return read-only local probes that can refresh a blocked action boundary."""

    normalized_action_id = _require_non_empty_string(action_id, field_name="action_id", max_length=160)
    if not isinstance(scope, dict):
        raise ValueError("scope must be an object")
    probe_params = {
        "session_id": scope.get("session_id"),
        "job_id": scope.get("job_id"),
        "project_id": scope.get("project_id"),
    }
    probes = [
        _handoff_resume_probe("Read Workflow Passport", "/runtime/workflow-passport", probe_params),
        _handoff_resume_probe("Read Evidence Integrity Gate", "/runtime/evidence-integrity-gate", probe_params),
        _handoff_resume_probe("Read Behavior Eval Pack", "/runtime/behavior-eval-pack", {"include_cases": "true"}),
        _handoff_resume_probe("List workflow replay index", "/runtime/workflow-replay-index", probe_params),
    ]
    job_id = _safe_projection_string(scope.get("job_id"))
    if job_id:
        probes.append(_handoff_resume_probe("Read runtime job action preflight metadata", f"/runtime/job/{job_id}"))
        probes.append(_handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{job_id}/workflow-replay-lineage"))
    else:
        probes.append(_handoff_resume_probe("List runtime jobs for action preflight metadata", "/runtime/jobs", probe_params))
    return probes[:8]


def _blocked_signal_summaries(signals: list[dict[str, Any]], *, statuses: set[str], max_items: int = 8) -> list[dict[str, Any]]:
    """Return bounded signal summaries that explain blockers or unresolved checks."""

    rows: list[dict[str, Any]] = []
    for signal in signals:
        if len(rows) >= max_items:
            break
        if not isinstance(signal, dict):
            continue
        status = _safe_projection_string(signal.get("status"))
        if status not in statuses:
            continue
        signal_id = _safe_projection_string(signal.get("signal_id"))
        if signal_id is None:
            continue
        row = {
            "signal_id": signal_id,
            "category": _safe_projection_string(signal.get("category")),
            "status": status,
            "severity": _safe_projection_string(signal.get("severity")),
            "message": _safe_projection_string(signal.get("message")),
            "blocks_claims": False,
        }
        drilldown = signal.get("drilldown")
        if isinstance(drilldown, dict):
            row["blocks_claims"] = bool(drilldown.get("blocks_claims"))
            replay_refs = drilldown.get("replay_refs")
            if isinstance(replay_refs, list):
                row["replay_ref_count"] = len(replay_refs)
        rows.append(_compact_projection_mapping(row))
    return rows


def _signal_linked_stage_id(signal: dict[str, Any], drilldown: dict[str, Any]) -> str | None:
    """Return the Workflow Passport stage id linked to one integrity signal."""

    checked_facts = drilldown.get("checked_facts") if isinstance(drilldown.get("checked_facts"), dict) else {}
    stage_id = _safe_projection_string(checked_facts.get("stage_id"))
    if stage_id is not None:
        return stage_id
    signal_id = _safe_projection_string(signal.get("signal_id"))
    if signal_id and signal_id.startswith("workflow_stage:"):
        return signal_id.removeprefix("workflow_stage:")
    category = _safe_projection_string(signal.get("category"))
    return {
        "locator": "material_read",
        "retrieval_quality": "evidence_pack",
        "citation_verification": "citation_review",
        "citation_overlap": "citation_review",
        "writing_lint": "draft",
        "export_readiness": "export",
        "behavior_eval": "agent_handoff",
        "approval_boundary": "agent_handoff",
    }.get(category or "")


def _recovery_ref_from_evidence_ref(ref: dict[str, Any]) -> dict[str, Any] | None:
    """Return a path-safe recovery ref derived from one compact evidence ref."""

    ref_type = _safe_projection_string(ref.get("ref_type"))
    ref_id = _safe_projection_string(ref.get("ref_id"))
    if ref_type is None and ref_id is None:
        return None
    row = {
        "ref_type": ref_type,
        "ref_id": ref_id,
        "source": "integrity_signal",
    }
    if ref_type == "runtime_job" and ref_id:
        row["probe_endpoint"] = f"/runtime/job/{ref_id}"
    elif ref_type == "preflight_refresh_receipt" and ref_id:
        row["probe_endpoint"] = "/runtime/workflow-replay-index"
    elif ref_type == "workflow_passport" or ref_type == "evidence_integrity_gate":
        row["probe_endpoint"] = f"/runtime/{str(ref_type).replace('_', '-')}"
    elif ref_type == "evidence_integrity_signal" and ref_id:
        row["probe_endpoint"] = "/runtime/evidence-integrity-gate"
    return _compact_projection_mapping(row)


def _boundary_recovery_probe_rows(
    *,
    signal: dict[str, Any],
    drilldown: dict[str, Any],
    gate_scope: dict[str, Any],
    linked_stage_id: str | None,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Return safe local probes that reproduce a boundary signal decision."""

    probe_params = {
        "session_id": gate_scope.get("session_id"),
        "job_id": gate_scope.get("job_id"),
        "project_id": gate_scope.get("project_id"),
    }
    probes: list[dict[str, Any]] = [
        _handoff_resume_probe("Read Workflow Passport", "/runtime/workflow-passport", probe_params),
        _handoff_resume_probe("Read Evidence Integrity Gate", "/runtime/evidence-integrity-gate", probe_params),
    ]
    if _safe_projection_string(signal.get("category")) == "behavior_eval":
        _append_unique_mapping(
            probes,
            _handoff_resume_probe("Read Behavior Eval Pack", "/runtime/behavior-eval-pack", {"include_cases": "true"}),
            max_items=max_items,
        )
    for ref in list(drilldown.get("evidence_refs") or []) + list(drilldown.get("replay_refs") or []):
        if not isinstance(ref, dict):
            continue
        ref_type = _safe_projection_string(ref.get("ref_type"))
        ref_id = _safe_projection_string(ref.get("ref_id"))
        if ref_type == "runtime_job" and ref_id:
            _append_unique_mapping(probes, _handoff_resume_probe("Read runtime job", f"/runtime/job/{ref_id}"), max_items=max_items)
            _append_unique_mapping(
                probes,
                _handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{ref_id}/workflow-replay-lineage"),
                max_items=max_items,
            )
        elif ref_type == "preflight_refresh_receipt":
            scoped_params = dict(probe_params)
            if ref_id:
                scoped_params["receipt_id"] = ref_id
            _append_unique_mapping(
                probes,
                _handoff_resume_probe("List workflow replay index", "/runtime/workflow-replay-index", scoped_params),
                max_items=max_items,
            )
    signal_id = _safe_projection_string(signal.get("signal_id"))
    if signal_id:
        _append_unique_mapping(
            probes,
            _handoff_resume_probe("Refresh boundary signal drilldown", "/runtime/evidence-integrity-gate", {
                **probe_params,
                "signal_id": signal_id,
                "stage_id": linked_stage_id,
            }),
            max_items=max_items,
        )
    return probes[:max_items]


def _boundary_recovery_drilldowns(
    signals: list[dict[str, Any]],
    *,
    statuses: set[str],
    gate_scope: dict[str, Any],
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Return bounded signal-to-record drilldowns for blocked action recovery."""

    rows: list[dict[str, Any]] = []
    for signal in signals:
        if len(rows) >= max_items:
            break
        if not isinstance(signal, dict):
            continue
        status = _safe_projection_string(signal.get("status"))
        if status not in statuses:
            continue
        signal_id = _safe_projection_string(signal.get("signal_id"))
        if signal_id is None:
            continue
        drilldown = signal.get("drilldown") if isinstance(signal.get("drilldown"), dict) else {}
        source_ref = drilldown.get("source_ref") if isinstance(drilldown.get("source_ref"), dict) else {}
        checked_facts = drilldown.get("checked_facts") if isinstance(drilldown.get("checked_facts"), dict) else {}
        evidence_refs = [item for item in drilldown.get("evidence_refs") or [] if isinstance(item, dict)][:12]
        replay_refs = [item for item in drilldown.get("replay_refs") or [] if isinstance(item, dict)][:8]
        linked_stage_id = _signal_linked_stage_id(signal, drilldown)
        recovery_refs: list[dict[str, Any]] = [
            {
                "ref_type": "workflow_passport_stage",
                "ref_id": linked_stage_id,
                "probe_endpoint": "/runtime/workflow-passport",
            },
            {
                "ref_type": "evidence_integrity_signal",
                "ref_id": signal_id,
                "probe_endpoint": "/runtime/evidence-integrity-gate",
            },
        ]
        for ref in evidence_refs + replay_refs:
            recovery_ref = _recovery_ref_from_evidence_ref(ref)
            if recovery_ref:
                _append_unique_mapping(recovery_refs, recovery_ref, max_items=16)
        next_actions: list[str] = []
        for action in signal.get("next_actions") or []:
            _append_unique_text(next_actions, action, max_items=8)
        if not next_actions:
            _append_unique_text(
                next_actions,
                "Refresh this signal through the Evidence Integrity Gate before retrying the blocked action.",
                max_items=8,
            )
        row = {
            "signal_id": signal_id,
            "category": _safe_projection_string(signal.get("category")),
            "status": status,
            "severity": _safe_projection_string(signal.get("severity")),
            "message": _safe_projection_string(signal.get("message")),
            "linked_stage_id": linked_stage_id,
            "source_ref": _compact_projection_mapping(source_ref),
            "checked_facts": _compact_projection_mapping(checked_facts),
            "evidence_refs": [_compact_projection_mapping(item) for item in evidence_refs],
            "replay_refs": [_compact_projection_mapping(item) for item in replay_refs],
            "recovery_refs": [
                _compact_projection_mapping(item)
                for item in recovery_refs
                if isinstance(item, dict)
            ][:16],
            "local_read_only_probes": _boundary_recovery_probe_rows(
                signal=signal,
                drilldown=drilldown,
                gate_scope=gate_scope,
                linked_stage_id=linked_stage_id,
                max_items=8,
            ),
            "next_safe_local_actions": next_actions,
            "requires_human_review": bool(drilldown.get("requires_human_review")),
            "blocks_claims": bool(drilldown.get("blocks_claims")),
            "read_only": True,
            "raw_path_exposed": bool(source_ref.get("raw_path_exposed")),
        }
        rows.append({
            key: _json_safe_copy(value)
            for key, value in row.items()
            if not _is_blank_projection_value(value) and str(key).lower() not in _RESEARCH_PRIVATE_PROJECTION_KEYS
        })
    return rows


def _workflow_blocking_action_boundary(
    *,
    action_id: str,
    required_claim_id: str,
    claim: dict[str, Any] | None,
    gate: dict[str, Any],
    blockers: list[str],
    unresolved: list[str],
    evidence: list[dict[str, Any]],
    status: str,
    can_proceed: bool,
    require_ready: bool,
    refresh_required: bool = False,
) -> dict[str, Any]:
    """Return a bounded, read-only boundary between blocked actions and safe probes."""

    normalized_action_id = _require_non_empty_string(action_id, field_name="action_id", max_length=160)
    normalized_claim_id = _require_non_empty_string(required_claim_id, field_name="required_claim_id", max_length=160)
    if claim is not None and not isinstance(claim, dict):
        raise ValueError("claim must be an object when provided")
    if not isinstance(gate, dict):
        raise ValueError("gate must be an object")
    if not isinstance(blockers, list):
        raise ValueError("blockers must be a list")
    if not isinstance(unresolved, list):
        raise ValueError("unresolved must be a list")
    if not isinstance(evidence, list):
        raise ValueError("evidence must be a list")
    gate_scope = gate.get("scope") if isinstance(gate.get("scope"), dict) else {}
    gate_signals = gate.get("signals") if isinstance(gate.get("signals"), list) else []
    signal_rows = [signal for signal in gate_signals if isinstance(signal, dict)]
    blocked_signal_refs = _blocked_signal_summaries(signal_rows, statuses={"block"}, max_items=8)
    unresolved_signal_refs = _blocked_signal_summaries(signal_rows, statuses={"unresolved"}, max_items=8)
    recovery_drilldowns = _boundary_recovery_drilldowns(
        signal_rows,
        statuses={"block", "unresolved"},
        gate_scope=gate_scope,
        max_items=8,
    )
    normalized_status = _safe_projection_string(status) or "unresolved"
    boundary_blocked = normalized_status == "blocked" or bool(blockers) or (bool(require_ready) and not bool(can_proceed))
    boundary_unresolved = normalized_status in {"unresolved", "stale"} or bool(unresolved) or bool(refresh_required)
    safe_probe_rows = _blocking_boundary_local_probes(action_id=normalized_action_id, scope=gate_scope)
    blocked_claims: list[dict[str, Any]] = []
    if isinstance(claim, dict):
        blocked_claims.append(
            _compact_projection_mapping(
                {
                    "claim_id": claim.get("claim_id"),
                    "label": claim.get("label"),
                    "status": claim.get("status"),
                    "reason": claim.get("reason"),
                    "blocker_count": len(claim.get("blockers") or []),
                    "unresolved_count": len(claim.get("unresolved") or []),
                }
            )
        )
    elif boundary_blocked or boundary_unresolved:
        blocked_claims.append(
            {
                "claim_id": normalized_claim_id,
                "status": "missing",
                "reason": f"Readiness claim {normalized_claim_id} was not found.",
            }
        )

    next_safe_local_actions: list[str] = []
    if refresh_required:
        _append_unique_text(
            next_safe_local_actions,
            "Rebuild the Workflow Passport and Evidence Integrity Gate before executing this action.",
            max_items=8,
        )
    for message in blockers[:3]:
        _append_unique_text(next_safe_local_actions, f"Resolve blocker: {message}", max_items=8)
    for message in unresolved[:3]:
        _append_unique_text(next_safe_local_actions, f"Refresh or review unresolved check: {message}", max_items=8)
    if not next_safe_local_actions:
        _append_unique_text(
            next_safe_local_actions,
            "Run the read-only local probes before making any readiness or handoff claim.",
            max_items=8,
        )

    forbidden_actions = [
        "Do not execute the blocked action until the required readiness claim is ready and fresh.",
        "Do not treat unresolved integrity checks as passed or verified.",
        "Do not bypass explicit user authorization for push, tag, release, publish, deploy, upload, credentials, or external mutation.",
        "Do not add import-to-wiki writes, direct Zotero writes, or github/ reference-repository changes from this boundary.",
    ]
    evidence_refs: list[dict[str, Any]] = []
    for item in evidence:
        if isinstance(item, dict):
            _append_unique_mapping(evidence_refs, _compact_projection_mapping(item), max_items=12)
    return {
        "schema_version": _BLOCKING_ACTION_BOUNDARY_SCHEMA_VERSION,
        "action_id": normalized_action_id,
        "required_claim_id": normalized_claim_id,
        "status": "blocked" if boundary_blocked else "unresolved" if boundary_unresolved else "ready",
        "can_proceed": bool(can_proceed) and not boundary_blocked and not boundary_unresolved,
        "require_ready": bool(require_ready),
        "refresh_required": bool(refresh_required),
        "blocked_claims": blocked_claims[:8],
        "blockers": [str(item) for item in blockers[:12] if _safe_projection_string(item) is not None],
        "unresolved": [str(item) for item in unresolved[:12] if _safe_projection_string(item) is not None],
        "blocked_signal_refs": blocked_signal_refs,
        "unresolved_signal_refs": unresolved_signal_refs,
        "recovery_drilldowns": recovery_drilldowns,
        "evidence_refs": evidence_refs[:12],
        "local_read_only_probes": safe_probe_rows,
        "next_safe_local_actions": next_safe_local_actions[:8],
        "forbidden_actions": forbidden_actions,
        "provenance": {
            "derived_from": [
                "runtime.evidence_integrity_gate",
                "runtime.workflow_readiness_claims",
                "runtime.action_preflight",
                "runtime.integrity_signal_drilldowns",
                "runtime.behavior_eval_pack",
            ],
            "evidence_integrity_gate_schema_version": gate.get("schema_version"),
            "workflow_enforcement_schema_version": _WORKFLOW_ENFORCEMENT_SCHEMA_VERSION,
            "recovery_drilldown_schema": "scholar_ai_blocking_action_boundary_recovery_drilldown_v1",
        },
    }


def _workflow_readiness_claims(
    *,
    workflow_state: dict[str, Any] | None,
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Return read-only enforcement state for export and handoff readiness claims."""

    if workflow_state is not None and not isinstance(workflow_state, dict):
        raise ValueError("workflow_state must be an object when provided")
    if not isinstance(gate, dict):
        raise ValueError("gate must be an object")
    readiness = workflow_state.get("readiness") if isinstance(workflow_state, dict) else {}
    if not isinstance(readiness, dict):
        readiness = {}
    signals = gate.get("signals") if isinstance(gate.get("signals"), list) else []
    signal_rows = [signal for signal in signals if isinstance(signal, dict)]
    claims: list[dict[str, Any]] = []
    for definition in _READINESS_CLAIM_DEFINITIONS:
        claim_id = str(definition["claim_id"])
        required_readiness = tuple(str(item) for item in definition.get("required_readiness", ()))
        missing_readiness = [
            key
            for key in required_readiness
            if not bool(readiness.get(key))
        ]
        required_signals = _signals_for_categories(signal_rows, tuple(definition["required_signal_categories"]))
        blocking_signals = _signals_for_categories(signal_rows, tuple(definition["blocked_by_categories"]))
        relevant_signals = _merge_claim_signals(
            required_signals,
            blocking_signals,
        )
        signal_status = _claim_signal_status(relevant_signals)
        blockers = _bounded_claim_messages(relevant_signals, {"block"})
        unresolved = _bounded_claim_messages(relevant_signals, {"unresolved"})
        if missing_readiness:
            for key in missing_readiness:
                _append_unique_text(unresolved, f"Workflow readiness is missing {key}.", max_items=8)

        if blockers:
            status = "blocked"
            reason = blockers[0]
        elif signal_status == "unresolved" or missing_readiness or unresolved:
            status = "unresolved"
            reason = unresolved[0] if unresolved else "Integrity gate is unresolved for this readiness claim."
        elif signal_status == "warn":
            status = "warning"
            reason = "Integrity gate has warnings for this readiness claim."
        elif signal_status == "pass":
            status = "ready"
            reason = "Required readiness evidence and integrity signals are passing."
        else:
            status = "unresolved"
            reason = "No integrity signal has proven this readiness claim yet."

        claims.append(
            {
                "claim_id": claim_id,
                "label": definition["label"],
                "status": status,
                "reason": reason,
                "required_readiness": list(required_readiness),
                "missing_readiness": missing_readiness,
                "source_gate_status": gate.get("status"),
                "blockers": blockers,
                "unresolved": unresolved,
                "evidence": _bounded_claim_evidence(relevant_signals),
            }
        )

    status_rank = {"ready": 0, "warning": 1, "unresolved": 2, "blocked": 3}
    overall = "ready"
    for claim in claims:
        if status_rank.get(str(claim.get("status") or ""), 0) > status_rank[overall]:
            overall = str(claim["status"])
    boundary_claim = next(
        (claim for claim in claims if isinstance(claim, dict) and claim.get("status") in {"blocked", "unresolved"}),
        claims[0] if claims else None,
    )
    boundary_action_id = (
        "writing.export_project"
        if isinstance(boundary_claim, dict) and boundary_claim.get("claim_id") == "export_readiness"
        else "agent.handoff_card"
    )
    boundary = _workflow_blocking_action_boundary(
        action_id=boundary_action_id,
        required_claim_id=str((boundary_claim or {}).get("claim_id") or "handoff_readiness"),
        claim=boundary_claim if isinstance(boundary_claim, dict) else None,
        gate=gate,
        blockers=[
            message
            for claim in claims
            if isinstance(claim, dict)
            for message in list(claim.get("blockers") or [])[:8]
        ],
        unresolved=[
            message
            for claim in claims
            if isinstance(claim, dict)
            for message in list(claim.get("unresolved") or [])[:8]
        ],
        evidence=[
            item
            for claim in claims
            if isinstance(claim, dict)
            for item in list(claim.get("evidence") or [])[:8]
            if isinstance(item, dict)
        ],
        status="blocked" if overall == "blocked" else "unresolved" if overall == "unresolved" else "ready",
        can_proceed=overall in {"ready", "warning"},
        require_ready=True,
        refresh_required=False,
    )
    return {
        "schema_version": _WORKFLOW_ENFORCEMENT_SCHEMA_VERSION,
        "status": overall,
        "claims": claims,
        "blocking_action_boundary": boundary,
        "summary": {
            "ready": sum(1 for claim in claims if claim["status"] == "ready"),
            "warning": sum(1 for claim in claims if claim["status"] == "warning"),
            "unresolved": sum(1 for claim in claims if claim["status"] == "unresolved"),
            "blocked": sum(1 for claim in claims if claim["status"] == "blocked"),
            "unresolved_is_ready": False,
            "blocking_action_boundary_status": boundary.get("status"),
        },
        "provenance": {
            "derived_from": [
                "runtime.writing_workflow_state",
                "runtime.evidence_integrity_gate",
            ],
            "evidence_integrity_gate_schema_version": gate.get("schema_version"),
        },
    }


def _workflow_claim_by_id(readiness_claims: dict[str, Any], claim_id: str) -> dict[str, Any] | None:
    """Return a readiness claim by id from a workflow enforcement payload."""

    if not isinstance(readiness_claims, dict):
        raise ValueError("readiness_claims must be an object")
    normalized_claim_id = str(claim_id or "").strip()
    if not normalized_claim_id:
        raise ValueError("claim_id must not be empty")
    claims = readiness_claims.get("claims")
    if not isinstance(claims, list):
        return None
    for claim in claims:
        if isinstance(claim, dict) and str(claim.get("claim_id") or "") == normalized_claim_id:
            return claim
    return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse bounded ISO 8601 timestamps used by runtime projections.

    Args:
        value: Candidate timestamp string in UTC ``Z`` or offset form.

    Returns:
        A timezone-aware UTC datetime, or ``None`` when the value is absent or
        malformed. Malformed timestamps are intentionally treated as freshness
        risk instead of raising through export paths.
    """

    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_from_utc(value: datetime) -> str:
    """Return a compact UTC ISO timestamp for freshness diagnostics."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    normalized = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _collect_projection_timestamps(
    *,
    passport: dict[str, Any],
    gate: dict[str, Any],
    readiness_claims: dict[str, Any],
    workflow_state: dict[str, Any] | None,
    generated_at: str,
) -> list[tuple[str, datetime]]:
    """Collect timestamps that bound how fresh an action preflight can be."""

    rows: list[tuple[str, datetime]] = []
    for label, payload in (
        ("action_preflight.generated_at", {"generated_at": generated_at}),
        ("workflow_passport.generated_at", passport),
        ("evidence_integrity_gate.generated_at", gate),
    ):
        parsed = _parse_iso_datetime(payload.get("generated_at") if isinstance(payload, dict) else None)
        if parsed is not None:
            rows.append((label, parsed))
    if isinstance(workflow_state, dict):
        parsed_state = _parse_iso_datetime(workflow_state.get("updated_at"))
        if parsed_state is not None:
            rows.append(("writing_workflow_state.updated_at", parsed_state))
    for index, claim in enumerate(readiness_claims.get("claims") if isinstance(readiness_claims.get("claims"), list) else []):
        if not isinstance(claim, dict):
            continue
        for evidence_index, evidence in enumerate(claim.get("evidence") if isinstance(claim.get("evidence"), list) else []):
            if not isinstance(evidence, dict):
                continue
            for key in ("updated_at", "created_at", "timestamp", "generated_at"):
                parsed_evidence = _parse_iso_datetime(evidence.get(key))
                if parsed_evidence is not None:
                    rows.append((f"readiness_claims.{index}.evidence.{evidence_index}.{key}", parsed_evidence))
                    break
    return rows


def _action_preflight_freshness(
    *,
    passport: dict[str, Any],
    gate: dict[str, Any],
    readiness_claims: dict[str, Any],
    workflow_state: dict[str, Any] | None,
    generated_at: str,
    max_age_seconds: int = _ACTION_PREFLIGHT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Return staleness diagnostics for command preflight projections.

    Args:
        passport: Workflow passport projection used by the action preflight.
        gate: Evidence integrity gate projection used by the action preflight.
        readiness_claims: Gate-derived readiness claims.
        workflow_state: Optional just-built writing state attached to export
            commands.
        generated_at: Action preflight generation timestamp.
        max_age_seconds: Maximum allowed age for command-preflight evidence.

    Returns:
        JSON-safe freshness payload. ``refresh_required`` is true when the
        projection is stale or has no trustworthy timestamp evidence.
    """

    if not isinstance(passport, dict):
        raise ValueError("passport must be an object")
    if not isinstance(gate, dict):
        raise ValueError("gate must be an object")
    if not isinstance(readiness_claims, dict):
        raise ValueError("readiness_claims must be an object")
    if workflow_state is not None and not isinstance(workflow_state, dict):
        raise ValueError("workflow_state must be an object when provided")
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    generated_dt = _parse_iso_datetime(generated_at)
    if generated_dt is None:
        return {
            "schema_version": _ACTION_PREFLIGHT_FRESHNESS_SCHEMA_VERSION,
            "status": "unknown",
            "refresh_required": True,
            "max_age_seconds": int(max_age_seconds),
            "age_seconds": None,
            "oldest_evidence_at": None,
            "expires_at": None,
            "checked_at": generated_at,
            "reasons": ["Action preflight generated_at is missing or invalid."],
            "refresh_actions": [
                "Rebuild the Workflow Passport and Evidence Integrity Gate before executing this command."
            ],
            "sources": [],
        }

    timestamp_rows = _collect_projection_timestamps(
        passport=passport,
        gate=gate,
        readiness_claims=readiness_claims,
        workflow_state=workflow_state,
        generated_at=generated_at,
    )
    if not timestamp_rows:
        return {
            "schema_version": _ACTION_PREFLIGHT_FRESHNESS_SCHEMA_VERSION,
            "status": "unknown",
            "refresh_required": True,
            "max_age_seconds": int(max_age_seconds),
            "age_seconds": None,
            "oldest_evidence_at": None,
            "expires_at": None,
            "checked_at": generated_at,
            "reasons": ["No timestamped workflow evidence was available for command preflight freshness."],
            "refresh_actions": [
                "Rebuild the Workflow Passport and Evidence Integrity Gate before executing this command."
            ],
            "sources": [],
        }

    oldest_label, oldest_dt = min(timestamp_rows, key=lambda item: item[1])
    newest_label, newest_dt = max(timestamp_rows, key=lambda item: item[1])
    age_seconds = max(0, int((generated_dt - oldest_dt).total_seconds()))
    expires_dt = oldest_dt + timedelta(seconds=int(max_age_seconds))
    status = "stale" if age_seconds > max_age_seconds else "fresh"
    refresh_required = status != "fresh"
    reasons: list[str] = []
    if refresh_required:
        reasons.append(
            f"Oldest preflight evidence is {age_seconds} seconds old, exceeding {max_age_seconds} seconds."
        )
    else:
        reasons.append("Action preflight evidence is within the freshness window.")
    return {
        "schema_version": _ACTION_PREFLIGHT_FRESHNESS_SCHEMA_VERSION,
        "status": status,
        "refresh_required": refresh_required,
        "max_age_seconds": int(max_age_seconds),
        "age_seconds": age_seconds,
        "oldest_evidence_at": _iso_from_utc(oldest_dt),
        "newest_evidence_at": _iso_from_utc(newest_dt),
        "expires_at": _iso_from_utc(expires_dt),
        "checked_at": generated_at,
        "reasons": reasons,
        "refresh_actions": [
            "Rebuild the Workflow Passport and Evidence Integrity Gate before executing this command."
        ] if refresh_required else [],
        "sources": [
            {"label": label, "timestamp": _iso_from_utc(timestamp)}
            for label, timestamp in sorted(timestamp_rows, key=lambda item: item[0])[:16]
        ],
        "oldest_source": oldest_label,
        "newest_source": newest_label,
    }


def _workflow_action_preflight_payload(
    *,
    action_id: str,
    required_claim_id: str,
    passport: dict[str, Any],
    gate: dict[str, Any],
    readiness_claims: dict[str, Any],
    require_ready: bool,
    workflow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a read-only action preflight over passport, gate, and readiness claims.

    Args:
        action_id: Stable local action identifier.
        required_claim_id: Claim that must be ready when hard enforcement is on.
        passport: Current workflow passport projection.
        gate: Current evidence integrity gate projection.
        readiness_claims: Current workflow enforcement projection.
        require_ready: Whether non-ready claims should block the action.
        workflow_state: Optional writing workflow state used for provenance only.

    Returns:
        JSON-safe action preflight payload.

    Raises:
        ValueError: If required objects are not mappings or identifiers are blank.
    """

    normalized_action_id = str(action_id or "").strip()
    normalized_claim_id = str(required_claim_id or "").strip()
    if not normalized_action_id:
        raise ValueError("action_id must not be empty")
    if not normalized_claim_id:
        raise ValueError("required_claim_id must not be empty")
    if not isinstance(passport, dict):
        raise ValueError("passport must be an object")
    if not isinstance(gate, dict):
        raise ValueError("gate must be an object")
    if not isinstance(readiness_claims, dict):
        raise ValueError("readiness_claims must be an object")
    if workflow_state is not None and not isinstance(workflow_state, dict):
        raise ValueError("workflow_state must be an object when provided")

    claim = _workflow_claim_by_id(readiness_claims, normalized_claim_id)
    claim_status = str((claim or {}).get("status") or "unresolved").strip() or "unresolved"
    gate_status = str(gate.get("status") or "unresolved").strip() or "unresolved"
    current_stage_id = _safe_projection_string(passport.get("current_stage_id"))
    stage_summary = passport.get("gate_summary") if isinstance(passport.get("gate_summary"), dict) else {}
    readiness_ok = claim_status in {"ready", "warning"}
    generated_at = utc_now_iso_z()
    freshness = _action_preflight_freshness(
        passport=passport,
        gate=gate,
        readiness_claims=readiness_claims,
        workflow_state=workflow_state,
        generated_at=generated_at,
    )
    refresh_required = bool(freshness.get("refresh_required"))
    hard_blocked = bool(require_ready and (not readiness_ok or refresh_required))

    blockers: list[str] = []
    unresolved: list[str] = []
    for message in (claim or {}).get("blockers") or []:
        _append_unique_text(blockers, message, max_items=12)
    for message in (claim or {}).get("unresolved") or []:
        _append_unique_text(unresolved, message, max_items=12)
    for message in gate.get("blockers") or []:
        _append_unique_text(blockers, message, max_items=12)
    for message in gate.get("unresolved") or []:
        _append_unique_text(unresolved, message, max_items=12)
    if claim is None:
        _append_unique_text(unresolved, f"Readiness claim {normalized_claim_id} was not found.", max_items=12)
    if refresh_required:
        refresh_reason = next(
            (str(reason) for reason in freshness.get("reasons", []) if _safe_projection_string(reason) is not None),
            "Action preflight evidence must be refreshed before command execution.",
        )
        _append_unique_text(unresolved, refresh_reason, max_items=12)
    if hard_blocked and not blockers and claim_status == "blocked":
        _append_unique_text(blockers, "Required readiness claim is blocked.", max_items=12)
    if hard_blocked and not unresolved and claim_status != "blocked":
        _append_unique_text(unresolved, "Required readiness claim is not ready.", max_items=12)

    evidence: list[dict[str, Any]] = []
    if isinstance(claim, dict):
        for item in claim.get("evidence") or []:
            if isinstance(item, dict):
                _append_unique_mapping(evidence, _compact_projection_mapping(item), max_items=16)
    _append_unique_mapping(
        evidence,
        {
            "ref_type": "workflow_passport",
            "schema_version": passport.get("schema_version"),
            "current_stage_id": current_stage_id,
        },
        max_items=16,
    )
    _append_unique_mapping(
        evidence,
        {
            "ref_type": "evidence_integrity_gate",
            "schema_version": gate.get("schema_version"),
            "status": gate_status,
        },
        max_items=16,
    )

    if claim_status == "blocked" or blockers:
        status = "blocked"
    elif refresh_required:
        status = "stale"
    elif readiness_ok:
        status = "ready"
    else:
        status = "unresolved"
    blocking_action_boundary = _workflow_blocking_action_boundary(
        action_id=normalized_action_id,
        required_claim_id=normalized_claim_id,
        claim=claim,
        gate=gate,
        blockers=blockers,
        unresolved=unresolved,
        evidence=evidence,
        status=status,
        can_proceed=not hard_blocked,
        require_ready=bool(require_ready),
        refresh_required=refresh_required,
    )

    return {
        "schema_version": _ACTION_PREFLIGHT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "action_id": normalized_action_id,
        "required_claim_id": normalized_claim_id,
        "require_ready": bool(require_ready),
        "status": status,
        "can_proceed": not hard_blocked,
        "claim_status": claim_status,
        "gate_status": gate_status,
        "current_stage_id": current_stage_id,
        "freshness": freshness,
        "refresh_required": refresh_required,
        "blockers": blockers[:12],
        "unresolved": unresolved[:12],
        "evidence": evidence[:16],
        "blocking_action_boundary": blocking_action_boundary,
        "summary": {
            "hard_blocked": hard_blocked,
            "unresolved_is_ready": False,
            "readiness_ok": readiness_ok,
            "refresh_required": refresh_required,
            "freshness_status": freshness.get("status"),
            "freshness_max_age_seconds": freshness.get("max_age_seconds"),
            "blocking_action_boundary_status": blocking_action_boundary.get("status"),
            "workflow_gate_summary": dict(stage_summary),
            "workflow_state_phase": workflow_state.get("phase") if isinstance(workflow_state, dict) else None,
        },
        "provenance": {
            "derived_from": [
                "runtime.workflow_passport",
                "runtime.evidence_integrity_gate",
                "runtime.workflow_readiness_claims",
            ],
            "workflow_passport_schema_version": passport.get("schema_version"),
            "evidence_integrity_gate_schema_version": gate.get("schema_version"),
            "readiness_claims_schema_version": readiness_claims.get("schema_version"),
        },
    }


def _workflow_refresh_receipt_payload(
    *,
    action_preflight: dict[str, Any],
    passport: dict[str, Any],
    gate: dict[str, Any],
    readiness_claims: dict[str, Any],
    session_id: str | None,
    job_id: str | None,
    project_id: str | None,
) -> dict[str, Any]:
    """Build a bounded replay receipt for refreshed workflow projections.

    Args:
        action_preflight: The action preflight generated from rebuilt projections.
        passport: Workflow Passport projection used for the preflight.
        gate: Evidence Integrity Gate projection used for the preflight.
        readiness_claims: Gate-derived readiness claims used for the preflight.
        session_id: Optional runtime session scope.
        job_id: Optional runtime job scope.
        project_id: Optional project scope.

    Returns:
        JSON-safe receipt that proves which local projections were replayed.

    Raises:
        ValueError: If any projection payload is not object-shaped.
    """

    if not isinstance(action_preflight, dict):
        raise ValueError("action_preflight must be an object")
    if not isinstance(passport, dict):
        raise ValueError("passport must be an object")
    if not isinstance(gate, dict):
        raise ValueError("gate must be an object")
    if not isinstance(readiness_claims, dict):
        raise ValueError("readiness_claims must be an object")

    normalized_action_id = _require_non_empty_string(
        action_preflight.get("action_id"),
        field_name="action_preflight.action_id",
        max_length=160,
    )
    normalized_claim_id = _require_non_empty_string(
        action_preflight.get("required_claim_id"),
        field_name="action_preflight.required_claim_id",
        max_length=160,
    )
    generated_at = utc_now_iso_z()
    scope = {
        "session_id": _safe_projection_string(session_id),
        "job_id": _safe_projection_string(job_id),
        "project_id": _safe_projection_string(project_id),
    }
    projection_digests = {
        "workflow_passport": _digest_json_payload(passport),
        "evidence_integrity_gate": _digest_json_payload(gate),
        "workflow_readiness_claims": _digest_json_payload(readiness_claims),
        "action_preflight": _digest_json_payload(action_preflight),
    }
    status = str(action_preflight.get("status") or "unresolved").strip() or "unresolved"
    refresh_required = bool(action_preflight.get("refresh_required"))
    can_proceed = bool(action_preflight.get("can_proceed"))
    receipt_seed = {
        "schema_version": _PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "action_id": normalized_action_id,
        "required_claim_id": normalized_claim_id,
        "scope": scope,
        "projection_digests": projection_digests,
        "status": status,
        "can_proceed": can_proceed,
    }
    receipt_id = f"preflight_refresh:{hashlib.sha256(_digest_json_payload(receipt_seed).encode('utf-8')).hexdigest()[:24]}"
    return {
        "schema_version": _PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "generated_at": generated_at,
        "action_id": normalized_action_id,
        "required_claim_id": normalized_claim_id,
        "scope": scope,
        "status": status,
        "can_proceed": can_proceed,
        "refresh_required": refresh_required,
        "projection_digests": projection_digests,
        "projection_refs": [
            {
                "ref_type": "workflow_passport",
                "schema_version": passport.get("schema_version"),
                "generated_at": passport.get("generated_at"),
                "current_stage_id": passport.get("current_stage_id"),
            },
            {
                "ref_type": "evidence_integrity_gate",
                "schema_version": gate.get("schema_version"),
                "generated_at": gate.get("generated_at"),
                "status": gate.get("status"),
            },
            {
                "ref_type": "workflow_readiness_claims",
                "schema_version": readiness_claims.get("schema_version"),
                "status": readiness_claims.get("status"),
            },
            {
                "ref_type": "action_preflight",
                "schema_version": action_preflight.get("schema_version"),
                "generated_at": action_preflight.get("generated_at"),
                "status": status,
            },
        ],
        "freshness": dict(action_preflight.get("freshness") or {}),
        "validation": {
            "passport_schema_version": passport.get("schema_version"),
            "evidence_integrity_gate_schema_version": gate.get("schema_version"),
            "readiness_claims_schema_version": readiness_claims.get("schema_version"),
            "preflight_schema_version": action_preflight.get("schema_version"),
            "gate_status": action_preflight.get("gate_status"),
            "claim_status": action_preflight.get("claim_status"),
            "blocker_count": len(action_preflight.get("blockers") or []),
            "unresolved_count": len(action_preflight.get("unresolved") or []),
            "refresh_required": refresh_required,
        },
        "replay": {
            "kind": "workflow_projection_refresh",
            "steps": [
                "Rebuilt Workflow Passport from local runtime jobs, events, artifacts, approvals, and material-processing task records.",
                "Rebuilt Evidence Integrity Gate from the refreshed passport and bounded runtime diagnostics.",
                "Rebuilt workflow readiness claims and action preflight from the refreshed gate.",
            ],
            "external_mutation": False,
            "source_material_mutation": False,
        },
        "provenance": {
            "derived_from": [
                "runtime.workflow_passport",
                "runtime.evidence_integrity_gate",
                "runtime.workflow_readiness_claims",
                "runtime.action_preflight",
            ],
            "standard_patterns": [
                "W3C PROV activity/entity generation",
                "Workflow Run RO-Crate workflow run outputs",
                "checkpointed workflow replay",
            ],
        },
    }


def _receipt_timestamp_key(receipt: dict[str, Any]) -> str:
    """Return a stable ordering key for replay receipts."""

    generated_at = _safe_projection_string(receipt.get("generated_at"))
    receipt_id = _safe_projection_string(receipt.get("receipt_id"))
    return f"{generated_at or ''}\u0000{receipt_id or ''}"


def _receipt_validation_counts(receipt: dict[str, Any]) -> dict[str, int]:
    """Return bounded validation counts used for replay lineage deltas."""

    validation = receipt.get("validation")
    if not isinstance(validation, dict):
        validation = {}

    def _count(key: str) -> int:
        value = validation.get(key)
        if isinstance(value, bool):
            return int(value)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    return {
        "blocker_count": _count("blocker_count"),
        "unresolved_count": _count("unresolved_count"),
    }


def _compact_refresh_receipt_row(receipt: dict[str, Any], *, ordinal: int) -> dict[str, Any]:
    """Return an agent-safe receipt row without embedding full projections."""

    if not isinstance(receipt, dict):
        raise ValueError("receipt must be an object")
    counts = _receipt_validation_counts(receipt)
    projection_digests = receipt.get("projection_digests")
    if not isinstance(projection_digests, dict):
        projection_digests = {}
    replay = receipt.get("replay")
    if not isinstance(replay, dict):
        replay = {}
    return {
        "ordinal": ordinal,
        "receipt_id": _safe_projection_string(receipt.get("receipt_id")),
        "generated_at": _safe_projection_string(receipt.get("generated_at")),
        "action_id": _safe_projection_string(receipt.get("action_id")),
        "required_claim_id": _safe_projection_string(receipt.get("required_claim_id")),
        "status": _safe_projection_string(receipt.get("status")) or "unresolved",
        "can_proceed": bool(receipt.get("can_proceed")),
        "refresh_required": bool(receipt.get("refresh_required")),
        "blocker_count": counts["blocker_count"],
        "unresolved_count": counts["unresolved_count"],
        "digest_keys": sorted(
            str(key)
            for key, value in projection_digests.items()
            if _safe_projection_string(key) is not None and _safe_projection_string(value) is not None
        )[:16],
        "projection_digests": {
            str(key): str(value)
            for key, value in sorted(projection_digests.items(), key=lambda item: str(item[0]))[:16]
            if _safe_projection_string(key) is not None and _safe_projection_string(value) is not None
        },
        "external_mutation": bool(replay.get("external_mutation")),
        "source_material_mutation": bool(replay.get("source_material_mutation")),
    }


def _receipt_delta(latest: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Compare latest receipt state against the previous replay receipt."""

    latest_counts = _receipt_validation_counts(latest)
    previous_counts = _receipt_validation_counts(previous) if isinstance(previous, dict) else {
        "blocker_count": 0,
        "unresolved_count": 0,
    }
    latest_digests = latest.get("projection_digests") if isinstance(latest.get("projection_digests"), dict) else {}
    previous_digests = previous.get("projection_digests") if isinstance(previous, dict) and isinstance(previous.get("projection_digests"), dict) else {}
    changed_digest_keys = sorted(
        {
            str(key)
            for key in set(latest_digests.keys()) | set(previous_digests.keys())
            if latest_digests.get(key) != previous_digests.get(key)
        }
    )
    return {
        "status_changed": (
            _safe_projection_string(latest.get("status"))
            != (_safe_projection_string(previous.get("status")) if isinstance(previous, dict) else None)
        ),
        "can_proceed_changed": (
            bool(latest.get("can_proceed"))
            != (bool(previous.get("can_proceed")) if isinstance(previous, dict) else False)
        ),
        "refresh_required_changed": (
            bool(latest.get("refresh_required"))
            != (bool(previous.get("refresh_required")) if isinstance(previous, dict) else False)
        ),
        "blocker_count_delta": latest_counts["blocker_count"] - previous_counts["blocker_count"],
        "unresolved_count_delta": latest_counts["unresolved_count"] - previous_counts["unresolved_count"],
        "changed_digest_keys": changed_digest_keys[:16],
    }


def _append_receipt_candidate(
    receipts: list[dict[str, Any]],
    seen_receipt_ids: set[str],
    candidate: Any,
) -> None:
    """Append a valid receipt candidate while preserving first-seen evidence."""

    if not isinstance(candidate, dict):
        return
    if candidate.get("schema_version") != _PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION:
        return
    receipt_id = _safe_projection_string(candidate.get("receipt_id"))
    if receipt_id is None or receipt_id in seen_receipt_ids:
        return
    receipts.append(dict(_json_safe_copy(candidate)))
    seen_receipt_ids.add(receipt_id)


def _collect_job_preflight_receipts(
    job: WritingJob,
    artifacts: list[WritingArtifact],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Collect unique persisted preflight receipts for a job.

    Why:
        Replay lineage and cross-job indexes must agree on receipt identity and
        ordering without expanding full projection payloads or mutating runtime
        state.
    """

    receipts: list[dict[str, Any]] = []
    seen_receipt_ids: set[str] = set()
    metadata = dict(job.metadata)
    _append_receipt_candidate(receipts, seen_receipt_ids, metadata.get("latest_preflight_refresh_receipt"))
    stored = metadata.get(_PREFLIGHT_REFRESH_RECEIPTS_KEY)
    if isinstance(stored, list):
        for item in stored:
            _append_receipt_candidate(receipts, seen_receipt_ids, item)

    artifact_count = 0
    for artifact in artifacts:
        if artifact.artifact_type != ArtifactType.METADATA:
            continue
        if artifact.metadata.get("kind") != "preflight_refresh_receipt":
            continue
        artifact_count += 1
        _append_receipt_candidate(receipts, seen_receipt_ids, artifact.content)

    receipts.sort(key=_receipt_timestamp_key)
    return receipts, {
        "metadata_receipt_count": len(stored) if isinstance(stored, list) else 0,
        "artifact_receipt_count": artifact_count,
    }


def _workflow_replay_index_row(
    *,
    job: WritingJob,
    session: WritingSession | None,
    project_id: str | None,
    receipts: list[dict[str, Any]],
    receipt_counts: dict[str, int],
    ordinal: int,
) -> dict[str, Any]:
    """Return one compact cross-job replay-index row."""

    latest = receipts[-1]
    previous = receipts[-2] if len(receipts) > 1 else None
    latest_row = _compact_refresh_receipt_row(latest, ordinal=len(receipts))
    comparison = _receipt_delta(latest, previous)
    status = str(latest_row.get("status") or "unresolved")
    counts = _receipt_validation_counts(latest)
    recovery_priority = 0
    if status == "blocked" or counts["blocker_count"] > 0:
        recovery_priority += 100
    if status in {"unresolved", "stale"} or counts["unresolved_count"] > 0:
        recovery_priority += 50
    if bool(latest_row.get("refresh_required")):
        recovery_priority += 25
    if not bool(latest_row.get("can_proceed")):
        recovery_priority += 10
    return {
        "ordinal": ordinal,
        "job_id": job.job_id,
        "session_id": job.session_id,
        "project_id": project_id,
        "job_kind": job.kind.value,
        "job_status": job.status.value,
        "session_title": _safe_projection_string((session.metadata if session else {}).get("title")) if session else None,
        "receipt_count": len(receipts),
        "latest_receipt_id": latest_row.get("receipt_id"),
        "latest_generated_at": latest_row.get("generated_at"),
        "latest_status": status,
        "latest_action_id": latest_row.get("action_id"),
        "latest_required_claim_id": latest_row.get("required_claim_id"),
        "latest_can_proceed": bool(latest_row.get("can_proceed")),
        "latest_refresh_required": bool(latest_row.get("refresh_required")),
        "latest_blocker_count": latest_row.get("blocker_count") or 0,
        "latest_unresolved_count": latest_row.get("unresolved_count") or 0,
        "changed_digest_keys": list(comparison.get("changed_digest_keys") or [])[:16],
        "comparison": comparison,
        "recovery_priority": recovery_priority,
        "metadata_receipt_count": receipt_counts.get("metadata_receipt_count", 0),
        "artifact_receipt_count": receipt_counts.get("artifact_receipt_count", 0),
        "resume_probes": [
            _handoff_resume_probe("Read runtime job", f"/runtime/job/{job.job_id}"),
            _handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{job.job_id}/workflow-replay-lineage"),
            _handoff_resume_probe("Read latest workflow refresh receipt", f"/runtime/job/{job.job_id}/preflight-refresh-receipt"),
        ],
        "read_only": True,
    }


def _agent_handoff_replay_recovery(
    *,
    lineage: dict[str, Any],
    replay_index: dict[str, Any],
    refresh_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Return bounded replay context for a recoverable agent handoff card.

    Args:
        lineage: Per-job replay lineage built from persisted refresh receipts.
        replay_index: Cross-job replay index scoped to the handoff project/session.
        refresh_receipt: Current handoff-card refresh receipt.

    Returns:
        Compact read-only recovery context. The payload intentionally carries
        refs and counts, not full workflow projections, so handoff cards remain
        safe for MCP and Agent Workspace display.
    """

    if not isinstance(lineage, dict):
        raise ValueError("lineage must be an object")
    if not isinstance(replay_index, dict):
        raise ValueError("replay_index must be an object")
    if not isinstance(refresh_receipt, dict):
        raise ValueError("refresh_receipt must be an object")

    summary = replay_index.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    lineage_summary = lineage.get("summary")
    if not isinstance(lineage_summary, dict):
        lineage_summary = {}
    latest = lineage.get("latest")
    if not isinstance(latest, dict):
        latest = {}
    index_items = replay_index.get("items")
    if not isinstance(index_items, list):
        index_items = []
    highest_priority = next((item for item in index_items if isinstance(item, dict)), None)

    def _count(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    replay_probes: list[dict[str, Any]] = []
    for source in (lineage.get("resume_probes"), replay_index.get("resume_probes")):
        if not isinstance(source, list):
            continue
        for probe in source:
            if isinstance(probe, dict):
                _append_unique_mapping(replay_probes, _compact_projection_mapping(probe), max_items=12)

    blocker_count = _count(lineage_summary.get("latest_blocker_count"))
    unresolved_count = _count(lineage_summary.get("latest_unresolved_count"))
    blocked_job_count = _count(summary.get("blocked_job_count"))
    unresolved_job_count = _count(summary.get("unresolved_job_count"))
    recovery_required = (
        bool(blocker_count)
        or bool(unresolved_count)
        or bool(blocked_job_count)
        or bool(unresolved_job_count)
        or bool(latest.get("refresh_required"))
        or bool(refresh_receipt.get("refresh_required"))
    )
    return {
        "schema_version": "scholar_ai_agent_handoff_replay_recovery_v1",
        "current_receipt": {
            "receipt_id": _safe_projection_string(refresh_receipt.get("receipt_id")),
            "status": _safe_projection_string(refresh_receipt.get("status")) or "unresolved",
            "can_proceed": bool(refresh_receipt.get("can_proceed")),
            "refresh_required": bool(refresh_receipt.get("refresh_required")),
        },
        "lineage": {
            "schema_version": lineage.get("schema_version"),
            "receipt_count": _count(lineage.get("receipt_count")),
            "latest_receipt_id": lineage.get("latest_receipt_id"),
            "latest_status": _safe_projection_string(latest.get("status")) or lineage_summary.get("latest_status"),
            "latest_blocker_count": blocker_count,
            "latest_unresolved_count": unresolved_count,
            "lineage_is_read_only": bool(lineage_summary.get("lineage_is_read_only", True)),
        },
        "index": {
            "schema_version": replay_index.get("schema_version"),
            "matching_job_count": _count(replay_index.get("matching_job_count")),
            "returned_count": _count(replay_index.get("returned_count")),
            "blocked_job_count": blocked_job_count,
            "unresolved_job_count": unresolved_job_count,
            "stale_job_count": _count(summary.get("stale_job_count")),
            "index_is_read_only": bool(summary.get("index_is_read_only", True)),
            "requires_exact_job_id": bool(summary.get("requires_exact_job_id", False)),
        },
        "highest_priority_attempt": _compact_projection_mapping(
            highest_priority,
            allowed_keys=(
                "job_id",
                "session_id",
                "project_id",
                "latest_status",
                "latest_action_id",
                "latest_required_claim_id",
                "latest_receipt_id",
                "latest_blocker_count",
                "latest_unresolved_count",
                "latest_refresh_required",
                "recovery_priority",
                "read_only",
            ),
        )
        if highest_priority
        else {},
        "resume_probes": replay_probes[:12],
        "recovery_required": recovery_required,
        "read_only": True,
        "source_material_mutation": False,
        "external_mutation": False,
    }


def _agent_handoff_current_replay_lineage(
    *,
    job: WritingJob,
    artifacts: list[WritingArtifact],
    refresh_receipt: dict[str, Any],
    project_id: str | None,
    limit: int = 12,
) -> dict[str, Any]:
    """Build a replay-lineage projection that includes the current handoff receipt."""

    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    receipts, receipt_counts = _collect_job_preflight_receipts(job, artifacts)
    receipt_id = _safe_projection_string(refresh_receipt.get("receipt_id"))
    if receipt_id is not None and all(receipt.get("receipt_id") != receipt_id for receipt in receipts):
        receipts.append(dict(_json_safe_copy(refresh_receipt)))
    receipts.sort(key=_receipt_timestamp_key)
    latest = receipts[-1] if receipts else None
    previous = receipts[-2] if len(receipts) > 1 else None
    latest_row = _compact_refresh_receipt_row(latest, ordinal=len(receipts)) if latest is not None else None
    previous_row = _compact_refresh_receipt_row(previous, ordinal=len(receipts) - 1) if previous is not None else None
    bounded_receipts = receipts[-limit:]
    items = [
        _compact_refresh_receipt_row(receipt, ordinal=(len(receipts) - len(bounded_receipts) + index + 1))
        for index, receipt in enumerate(bounded_receipts)
    ]
    blockers: list[str] = []
    unresolved: list[str] = []
    if latest is not None:
        latest_counts = _receipt_validation_counts(latest)
        latest_status = _safe_projection_string(latest.get("status")) or "unresolved"
        if latest_status == "blocked" or latest_counts["blocker_count"] > 0:
            _append_unique_text(
                blockers,
                f"Latest replay receipt reports {latest_counts['blocker_count']} blocking checks.",
                max_items=8,
            )
        if latest_status in {"unresolved", "stale"} or latest_counts["unresolved_count"] > 0:
            _append_unique_text(
                unresolved,
                f"Latest replay receipt reports {latest_counts['unresolved_count']} unresolved checks.",
                max_items=8,
            )
        if bool(latest.get("refresh_required")):
            _append_unique_text(
                unresolved,
                "Latest replay still requires a Workflow Passport and Evidence Integrity Gate refresh.",
                max_items=8,
            )
    resume_probes = [
        _handoff_resume_probe("Read runtime job", f"/runtime/job/{job.job_id}"),
        _handoff_resume_probe("Read runtime snapshot", f"/runtime/job/{job.job_id}/snapshot"),
        _handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{job.job_id}/workflow-replay-lineage"),
    ]
    if latest_row and latest_row.get("receipt_id"):
        resume_probes.append(
            _handoff_resume_probe(
                "Read latest workflow refresh receipt",
                f"/runtime/job/{job.job_id}/preflight-refresh-receipt",
                {"receipt_id": str(latest_row["receipt_id"])},
            )
        )
    return dict(_json_safe_copy({
        "schema_version": _WORKFLOW_REPLAY_LINEAGE_SCHEMA_VERSION,
        "generated_at": utc_now_iso_z(),
        "job_id": job.job_id,
        "session_id": job.session_id,
        "project_id": project_id,
        "scope": {
            "session_id": job.session_id,
            "job_id": job.job_id,
            "project_id": project_id,
        },
        "receipt_count": len(receipts),
        "returned_count": len(items),
        "latest_receipt_id": latest_row.get("receipt_id") if latest_row else None,
        "latest": latest_row or {},
        "previous": previous_row or {},
        "items": items,
        "comparison": _receipt_delta(latest, previous) if latest is not None else {},
        "blockers": blockers[:8],
        "unresolved": unresolved[:8],
        "resume_probes": resume_probes[:8],
        "summary": {
            "has_receipts": bool(receipts),
            "latest_status": latest_row.get("status") if latest_row else None,
            "latest_can_proceed": latest_row.get("can_proceed") if latest_row else None,
            "latest_refresh_required": latest_row.get("refresh_required") if latest_row else None,
            "latest_blocker_count": latest_row.get("blocker_count") if latest_row else 0,
            "latest_unresolved_count": latest_row.get("unresolved_count") if latest_row else 0,
            "metadata_receipt_count": receipt_counts["metadata_receipt_count"],
            "artifact_receipt_count": receipt_counts["artifact_receipt_count"],
            "includes_current_handoff_receipt": receipt_id is not None,
            "lineage_is_read_only": True,
        },
        "provenance": {
            "derived_from": [
                "runtime.job_metadata.latest_preflight_refresh_receipt",
                "runtime.job_metadata.preflight_refresh_receipts",
                "runtime.artifacts.preflight_refresh_receipt",
                "runtime.agent_handoff_card.current_refresh_receipt",
            ],
            "source_material_mutation": False,
            "external_mutation": False,
        },
    }))


def _agent_handoff_current_replay_index(
    *,
    jobs: list[WritingJob],
    sessions_by_id: dict[str, WritingSession],
    artifacts_by_job: dict[str, list[WritingArtifact]],
    current_job: WritingJob,
    current_receipt: dict[str, Any],
    session_id: str,
    project_id: str | None,
    limit: int = 10,
) -> dict[str, Any]:
    """Build a scoped replay index that includes the current handoff receipt."""

    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    rows: list[dict[str, Any]] = []
    total_jobs_scanned = 0
    total_receipts_seen = 0
    status_counts: dict[str, int] = {}
    blockers: list[str] = []
    unresolved: list[str] = []
    project_ids: set[str] = set()
    session_ids: set[str] = set()

    current_receipt_id = _safe_projection_string(current_receipt.get("receipt_id"))
    for job in jobs:
        if job.session_id != session_id:
            continue
        session = sessions_by_id.get(job.session_id)
        job_project_id = _project_id_for_job(job, session)
        if project_id is not None and job_project_id != project_id:
            continue
        total_jobs_scanned += 1
        receipts, receipt_counts = _collect_job_preflight_receipts(job, artifacts_by_job.get(job.job_id, []))
        if job.job_id == current_job.job_id and current_receipt_id is not None:
            if all(receipt.get("receipt_id") != current_receipt_id for receipt in receipts):
                receipts.append(dict(_json_safe_copy(current_receipt)))
        receipts.sort(key=_receipt_timestamp_key)
        if not receipts:
            continue
        total_receipts_seen += len(receipts)
        row = _workflow_replay_index_row(
            job=job,
            session=session,
            project_id=job_project_id,
            receipts=receipts,
            receipt_counts=receipt_counts,
            ordinal=0,
        )
        rows.append(row)
        latest_status = str(row.get("latest_status") or "unresolved")
        status_counts[latest_status] = status_counts.get(latest_status, 0) + 1
        session_ids.add(job.session_id)
        if job_project_id:
            project_ids.add(job_project_id)
        if row["latest_status"] == "blocked" or row["latest_blocker_count"] > 0:
            _append_unique_text(
                blockers,
                f"Job {job.job_id} latest replay receipt reports {row['latest_blocker_count']} blocking checks.",
                max_items=12,
            )
        if row["latest_status"] in {"unresolved", "stale"} or row["latest_unresolved_count"] > 0:
            _append_unique_text(
                unresolved,
                f"Job {job.job_id} latest replay receipt reports {row['latest_unresolved_count']} unresolved checks.",
                max_items=12,
            )
        if row["latest_refresh_required"]:
            _append_unique_text(
                unresolved,
                f"Job {job.job_id} still requires refreshed workflow projections before retry.",
                max_items=12,
            )

    rows.sort(
        key=lambda row: (
            int(row.get("recovery_priority") or 0),
            str(row.get("latest_generated_at") or ""),
            str(row.get("job_id") or ""),
        ),
        reverse=True,
    )
    bounded_rows = [{**row, "ordinal": index + 1} for index, row in enumerate(rows[:limit])]
    resume_probes = [
        _handoff_resume_probe("List workflow replay index", "/runtime/workflow-replay-index"),
        _handoff_resume_probe(
            "List session-scoped workflow replay index",
            "/runtime/workflow-replay-index",
            {"session_id": session_id},
        ),
    ]
    if project_id:
        resume_probes.append(
            _handoff_resume_probe(
                "List project-scoped workflow replay index",
                "/runtime/workflow-replay-index",
                {"project_id": project_id},
            )
        )
    if bounded_rows:
        resume_probes.append(
            _handoff_resume_probe(
                "Read highest-priority replay lineage",
                f"/runtime/job/{bounded_rows[0]['job_id']}/workflow-replay-lineage",
            )
        )
    return dict(_json_safe_copy({
        "schema_version": _WORKFLOW_REPLAY_INDEX_SCHEMA_VERSION,
        "generated_at": utc_now_iso_z(),
        "scope": {
            "session_id": session_id,
            "project_id": project_id,
            "status": None,
            "action_id": None,
            "limit": limit,
        },
        "total_jobs_scanned": total_jobs_scanned,
        "total_receipts_seen": total_receipts_seen,
        "matching_job_count": len(rows),
        "returned_count": len(bounded_rows),
        "items": bounded_rows,
        "blockers": blockers[:12],
        "unresolved": unresolved[:12],
        "resume_probes": resume_probes[:10],
        "summary": {
            "has_replay_evidence": bool(rows),
            "blocked_job_count": status_counts.get("blocked", 0),
            "unresolved_job_count": status_counts.get("unresolved", 0),
            "stale_job_count": status_counts.get("stale", 0),
            "ready_job_count": status_counts.get("ready", 0),
            "status_counts": status_counts,
            "project_ids": sorted(project_ids)[:24],
            "session_ids": sorted(session_ids)[:24],
            "filtered_out_count": 0,
            "includes_current_handoff_receipt": current_receipt_id is not None,
            "index_is_read_only": True,
            "requires_exact_job_id": False,
        },
        "provenance": {
            "derived_from": [
                "runtime.jobs",
                "runtime.job_metadata.latest_preflight_refresh_receipt",
                "runtime.job_metadata.preflight_refresh_receipts",
                "runtime.artifacts.preflight_refresh_receipt",
                "runtime.agent_handoff_card.current_refresh_receipt",
            ],
            "source_material_mutation": False,
            "external_mutation": False,
        },
    }))


def _iter_runtime_metadata_dicts(jobs: list[WritingJob]) -> list[tuple[str, dict[str, Any]]]:
    """Return metadata-bearing objects attached to selected runtime jobs."""

    rows: list[tuple[str, dict[str, Any]]] = []
    for job in jobs:
        metadata = dict(job.metadata)
        for key in (
            _WRITING_WORKFLOW_STATE_KEY,
            _MATERIAL_PROCESSING_TASK_KEY,
            "retrieval_diagnostics",
            "locator_coverage",
            "qrels_status",
            "citation_verifications",
            "citation_overlap",
            "citation_overlaps",
            "academic_writing_lint",
            "lint_report",
            "export_manifest",
            "behavior_eval_pack",
            "behavior_eval",
        ):
            value = metadata.get(key)
            if isinstance(value, dict):
                rows.append((f"runtime.job_metadata:{job.job_id}:{key}", value))
            elif isinstance(value, list):
                for index, item in enumerate(value[:32]):
                    if isinstance(item, dict):
                        rows.append((f"runtime.job_metadata:{job.job_id}:{key}:{index}", item))
    return rows


def _iter_artifact_dicts(jobs: list[WritingJob], artifacts_by_job: dict[str, list[WritingArtifact]]) -> list[tuple[str, dict[str, Any]]]:
    """Return object-shaped runtime artifact content and metadata rows."""

    rows: list[tuple[str, dict[str, Any]]] = []
    for job in jobs:
        for artifact in artifacts_by_job.get(job.job_id, []):
            if isinstance(artifact.content, dict):
                rows.append((f"runtime.artifact:{artifact.artifact_id}:content", dict(artifact.content)))
            metadata = dict(artifact.metadata)
            if metadata:
                rows.append((f"runtime.artifact:{artifact.artifact_id}:metadata", metadata))
    return rows


def _bounded_handoff_refs(values: Any, *, max_items: int = 24) -> list[dict[str, Any]]:
    """Return compact JSON-safe refs for agent handoff artifacts."""

    if not isinstance(values, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in values[:max_items]:
        if not isinstance(item, dict):
            continue
        ref = _compact_projection_mapping(
            item,
            allowed_keys=(
                "ref_id",
                "kind",
                "project_id",
                "material_id",
                "chunk_id",
                "title",
                "summary",
                "read_endpoint",
                "page",
                "bbox",
                "bbox_unit",
                "status",
                "source",
            ),
        )
        if ref:
            _append_unique_mapping(refs, ref, max_items=max_items)
    return refs


def _bounded_handoff_artifacts(artifacts: list[WritingArtifact], *, max_items: int = 24) -> list[dict[str, Any]]:
    """Return compact artifact summaries without expanding large artifact bodies."""

    rows: list[dict[str, Any]] = []
    for artifact in artifacts[:max_items]:
        content_kind: str | None = None
        if isinstance(artifact.content, dict):
            content_kind = _safe_projection_string(artifact.content.get("kind"))
        row = {
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type.value,
            "created_at": artifact.created_at,
            "created_by": artifact.created_by,
            "mime_type": artifact.mime_type,
            "content_shape": "object" if isinstance(artifact.content, dict) else "text",
            "content_kind": content_kind,
            "metadata": _compact_projection_mapping(dict(artifact.metadata)),
        }
        _append_unique_mapping(
            rows,
            {
                key: _projection_value(value)
                for key, value in row.items()
                if not _is_blank_projection_value(value)
            },
            max_items=max_items,
        )
    return rows


def _handoff_status_from_job_status(status: Any) -> str:
    """Return a stable handoff lifecycle string for one runtime job."""

    normalized = str(getattr(status, "value", status) or "").strip().lower()
    if normalized in {"completed", "failed", "cancelled", "paused"}:
        return normalized
    if normalized in {"started", "in_progress", "queued", "created", "approval_pending"}:
        return normalized
    return "unresolved"


def _handoff_resume_probe(label: str, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return one read-only probe a resumed agent should run first."""

    query = {
        str(key): str(value)
        for key, value in (params or {}).items()
        if _safe_projection_string(value) is not None
    }
    return {
        "label": label,
        "method": "GET",
        "endpoint": endpoint,
        "url": f"{endpoint}?{urlencode(query)}" if query else endpoint,
        "read_only": True,
    }


def _collect_nested_dicts(value: Any, *, max_items: int = 128) -> list[dict[str, Any]]:
    """Return bounded nested mappings for integrity-signal discovery."""

    collected: list[dict[str, Any]] = []

    def _visit(candidate: Any) -> None:
        if len(collected) >= max_items:
            return
        if isinstance(candidate, dict):
            collected.append(candidate)
            for nested in candidate.values():
                _visit(nested)
            return
        if isinstance(candidate, list):
            for nested in candidate:
                _visit(nested)

    _visit(value)
    return collected


def _find_first_nested_dict(value: Any, keys: set[str]) -> dict[str, Any] | None:
    """Return the first nested mapping that contains any requested key."""

    for item in _collect_nested_dicts(value):
        if any(key in item for key in keys):
            return item
    return None


def _extract_locator_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return locator coverage payloads discovered in a runtime object."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if "coverage_state" in item and "risk_level" in item and (
            "page_coverage_ratio" in item
            or "bbox_coverage_ratio" in item
            or "page_locator_count" in item
            or "bbox_locator_count" in item
        ):
            matches.append((source_id, item))
    return matches[:16]


def _extract_qrels_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return retrieval-qrels status payloads discovered in a runtime object."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if "semantic_quality_claim_allowed" in item and "quality_claim" in item:
            matches.append((source_id, item))
    return matches[:16]


def _extract_citation_verification_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return citation verification payloads discovered in a runtime object."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if "citation_id" in item and "status" in item and (
            "verification_id" in item or "rationale" in item or "source_anchor" in item
        ):
            matches.append((source_id, item))
    return matches[:32]


def _extract_citation_overlap_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return citation overlap payloads discovered in a runtime object."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if "overlap_score" in item and (
            "anchor_id" in item or "overlapping_anchors" in item or "recommendation" in item
        ):
            matches.append((source_id, item))
    return matches[:32]


def _extract_lint_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return academic-writing lint payloads discovered in a runtime object."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if "passed" in item and ("issues" in item or "quality_gate" in item or "metrics" in item):
            matches.append((source_id, item))
    return matches[:16]


def _extract_export_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return export manifest payloads discovered in a runtime object."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if ("format" in item and "filename" in item) or (
            "citation_chain" in item or "review_findings" in item or "evidence_rows" in item
        ):
            matches.append((source_id, item))
    return matches[:16]


def _extract_behavior_eval_payloads(source_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return observation-mode behavior-eval payloads discovered in runtime data."""

    matches: list[tuple[str, dict[str, Any]]] = []
    for item in _collect_nested_dicts(payload):
        if item.get("schema_version") != "scholar_ai_behavior_eval_pack_v1":
            continue
        if item.get("mode") != "observations":
            continue
        summary = item.get("summary")
        results = item.get("results")
        if isinstance(summary, dict) and isinstance(results, list):
            matches.append((source_id, item))
    return matches[:16]


def _locator_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert locator coverage into a blocking/warning integrity signal."""

    coverage_state = str(payload.get("coverage_state") or "missing")
    risk_level = str(payload.get("risk_level") or "warn")
    project_ref_count = int(payload.get("project_ref_count") or 0)
    if risk_level == "block":
        status = "block"
        severity = "block"
        message = "Evidence refs are missing source locators required for traceable review."
    elif risk_level == "warn":
        status = "warn"
        severity = "warn"
        message = "Evidence refs are only partially layout-located and need review before strong claims."
    elif project_ref_count == 0 and coverage_state == "no_refs":
        status = "not_applicable"
        severity = "note"
        message = "No project evidence refs are present for locator integrity checks."
    else:
        status = "pass"
        severity = "none"
        message = "Evidence refs have sufficient source locator coverage for this gate."
    return _integrity_signal(
        signal_id=f"locator:{source_id}",
        category="locator",
        status=status,
        severity=severity,
        message=message,
        evidence=_bounded_signal_evidence(
            "runtime_payload",
            source_id,
            coverage_state=coverage_state,
            risk_level=risk_level,
        ),
        next_actions=[
            "Rebuild evidence refs with page and bbox locators before export or agent handoff."
        ] if status == "block" else [],
        metadata=_compact_projection_mapping(
            payload,
            allowed_keys=(
                "coverage_state",
                "risk_level",
                "total_refs",
                "project_ref_count",
                "page_coverage_ratio",
                "bbox_coverage_ratio",
                "missing_locator_count",
                "sample_missing_ref_ids",
                "notes",
            ),
        ),
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="locator_coverage",
            status=status,
            checked_facts=_compact_projection_mapping(
                payload,
                allowed_keys=(
                    "schema_version",
                    "coverage_state",
                    "risk_level",
                    "total_refs",
                    "project_ref_count",
                    "material_locator_count",
                    "page_locator_count",
                    "bbox_locator_count",
                    "bbox_unit_counts",
                    "source_label_coverage_ratio",
                    "figure_table_locator_count",
                    "missing_locator_count",
                    "sample_missing_ref_ids",
                ),
            ),
            evidence_refs=_bounded_signal_evidence(
                "locator_coverage",
                source_id,
                coverage_state=coverage_state,
                risk_level=risk_level,
            ),
        ),
    )


def _qrels_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert retrieval qrels state into semantic-quality gate signal."""

    status_value = str(payload.get("status") or "missing")
    allowed = bool(payload.get("semantic_quality_claim_allowed"))
    if allowed:
        status = "pass"
        severity = "none"
        message = "Canonical qrels are available for retrieval-quality claims."
    elif status_value in {"candidate", "reviewed"}:
        status = "unresolved"
        severity = "warn"
        message = "Retrieval quality labels exist but are not canonical proof yet."
    else:
        status = "unresolved"
        severity = "note"
        message = "Retrieval quality claims remain unresolved because canonical qrels are missing."
    return _integrity_signal(
        signal_id=f"retrieval_quality:{source_id}",
        category="retrieval_quality",
        status=status,
        severity=severity,
        message=message,
        evidence=_bounded_signal_evidence(
            "runtime_payload",
            source_id,
            qrels_status=status_value,
            quality_claim=payload.get("quality_claim"),
        ),
        next_actions=[
            "Promote reviewed qrels before claiming semantic retrieval quality."
        ] if status == "unresolved" else [],
        metadata=_compact_projection_mapping(
            payload,
            allowed_keys=(
                "status",
                "candidate_qrels_count",
                "reviewed_qrels_count",
                "canonical_qrels_count",
                "semantic_quality_claim_allowed",
                "quality_claim",
                "notes",
            ),
        ),
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="qrels_status",
            status=status,
            checked_facts=_compact_projection_mapping(
                payload,
                allowed_keys=(
                    "schema_version",
                    "status",
                    "candidate_qrels_count",
                    "reviewed_qrels_count",
                    "canonical_qrels_count",
                    "semantic_quality_claim_allowed",
                    "quality_claim",
                    "notes",
                ),
            ),
            evidence_refs=_bounded_signal_evidence(
                "qrels_status",
                source_id,
                qrels_status=status_value,
                quality_claim=payload.get("quality_claim"),
            ),
        ),
    )


def _citation_verification_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert citation verification state into pass/block/unresolved signal."""

    status_value = str(payload.get("status") or "needs_review")
    citation_id = _safe_projection_string(payload.get("citation_id")) or "unknown"
    if status_value == "verified":
        status = "pass"
        severity = "none"
        message = "Citation source anchor is verified."
    elif status_value == "unsupported":
        status = "block"
        severity = "block"
        message = "Citation is unsupported by its recorded source anchor."
    else:
        status = "unresolved"
        severity = "warn"
        message = "Citation source verification needs review and must not be shown as verified."
    return _integrity_signal(
        signal_id=f"citation_verification:{citation_id}:{source_id}",
        category="citation_verification",
        status=status,
        severity=severity,
        message=message,
        evidence=_bounded_signal_evidence(
            "citation_verification",
            payload.get("verification_id") or citation_id,
            citation_id=citation_id,
            source_kind=payload.get("source_kind"),
        ),
        next_actions=[
            "Attach a source anchor and verify the citation before export."
        ] if status != "pass" else [],
        metadata=_compact_projection_mapping(
            payload,
            allowed_keys=("verification_id", "citation_id", "status", "rationale", "source_kind", "source_labels"),
        ),
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="citation_verification",
            status=status,
            checked_facts=_compact_projection_mapping(
                payload,
                allowed_keys=(
                    "verification_id",
                    "citation_id",
                    "status",
                    "rationale",
                    "source_kind",
                    "source_labels",
                    "source_anchor",
                ),
            ),
            evidence_refs=_bounded_signal_evidence(
                "citation_verification",
                payload.get("verification_id") or citation_id,
                citation_id=citation_id,
                source_kind=payload.get("source_kind"),
            ),
        ),
    )


def _citation_overlap_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert citation overlap diagnostics into review signal."""

    try:
        overlap_score = float(payload.get("overlap_score") or 0.0)
    except (TypeError, ValueError):
        overlap_score = 0.0
    anchor_id = _safe_projection_string(payload.get("anchor_id")) or "unknown"
    if overlap_score >= 0.92:
        status = "block"
        severity = "block"
        message = "Citation anchors overlap too strongly and need deduplication or source review."
    elif overlap_score >= 0.75:
        status = "warn"
        severity = "warn"
        message = "Citation anchors may reuse the same evidence and should be reviewed."
    else:
        status = "pass"
        severity = "none"
        message = "Citation overlap is within the local review threshold."
    return _integrity_signal(
        signal_id=f"citation_overlap:{anchor_id}:{source_id}",
        category="citation_overlap",
        status=status,
        severity=severity,
        message=message,
        evidence=_bounded_signal_evidence(
            "citation_overlap",
            anchor_id,
            overlap_score=round(overlap_score, 4),
        ),
        next_actions=[
            "Deduplicate overlapping citation anchors or justify distinct claims."
        ] if status in {"warn", "block"} else [],
        metadata=_compact_projection_mapping(
            {
                **payload,
                "overlap_score": round(overlap_score, 4),
            },
            allowed_keys=("anchor_id", "material_id", "chunk_id", "overlap_score", "overlapping_anchors", "recommendation"),
        ),
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="citation_overlap",
            status=status,
            checked_facts=_compact_projection_mapping(
                {
                    **payload,
                    "overlap_score": round(overlap_score, 4),
                },
                allowed_keys=("anchor_id", "material_id", "chunk_id", "overlap_score", "overlapping_anchors", "recommendation"),
            ),
            evidence_refs=_bounded_signal_evidence(
                "citation_overlap",
                anchor_id,
                overlap_score=round(overlap_score, 4),
            ),
        ),
    )


def _lint_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert academic-writing lint output into integrity gate signal."""

    passed = bool(payload.get("passed"))
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    issue_severities = [
        str(item.get("severity") or "")
        for item in issues
        if isinstance(item, dict)
    ]
    if passed:
        status = "pass"
        severity = "none"
        message = "Academic writing lint passed."
    elif "error" in issue_severities:
        status = "block"
        severity = "block"
        message = "Academic writing lint reported error-level integrity issues."
    elif issues:
        status = "warn"
        severity = "warn"
        message = "Academic writing lint reported warning-level issues."
    else:
        status = "unresolved"
        severity = "note"
        message = "Academic writing lint result is incomplete and needs rerun."
    return _integrity_signal(
        signal_id=f"writing_lint:{source_id}",
        category="writing_lint",
        status=status,
        severity=severity,
        message=message,
        evidence=_bounded_signal_evidence(
            "runtime_payload",
            source_id,
            issue_count=len(issues),
        ),
        next_actions=[
            "Resolve lint issues or rerun the writing lint before export readiness is claimed."
        ] if status != "pass" else [],
        metadata={
            "passed": passed,
            "issue_count": len(issues),
            "issue_severities": sorted(set(filter(None, issue_severities))),
            **_compact_projection_mapping(payload, allowed_keys=("score", "quality_gate", "recommendations")),
        },
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="academic_writing_lint",
            status=status,
            checked_facts={
                "passed": passed,
                "issue_count": len(issues),
                "issue_severities": sorted(set(filter(None, issue_severities))),
                **_compact_projection_mapping(payload, allowed_keys=("score", "quality_gate", "recommendations")),
            },
            evidence_refs=_bounded_signal_evidence(
                "academic_writing_lint",
                source_id,
                issue_count=len(issues),
            ),
        ),
    )


def _export_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert export manifest facts into readiness signal."""

    review_findings = payload.get("review_findings") if isinstance(payload.get("review_findings"), list) else []
    blocking_findings = [
        item
        for item in review_findings
        if isinstance(item, dict) and str(item.get("severity") or "").lower() in {"error", "block", "critical"}
    ]
    citation_chain = payload.get("citation_chain") if isinstance(payload.get("citation_chain"), list) else []
    if blocking_findings:
        status = "block"
        severity = "block"
        message = "Export manifest contains blocking review findings."
    elif not citation_chain and not payload.get("evidence_rows"):
        status = "unresolved"
        severity = "warn"
        message = "Export manifest lacks citation-chain or evidence-row proof."
    else:
        status = "pass"
        severity = "none"
        message = "Export manifest includes reviewable citation or evidence provenance."
    return _integrity_signal(
        signal_id=f"export_readiness:{source_id}",
        category="export_readiness",
        status=status,
        severity=severity,
        message=message,
        evidence=_bounded_signal_evidence(
            "runtime_payload",
            source_id,
            format=payload.get("format"),
            filename=payload.get("filename"),
        ),
        next_actions=[
            "Regenerate export evidence rows and clear blocking review findings."
        ] if status != "pass" else [],
        metadata={
            "review_finding_count": len(review_findings),
            "blocking_finding_count": len(blocking_findings),
            "citation_chain_count": len(citation_chain),
            **_compact_projection_mapping(payload, allowed_keys=("format", "filename", "media_type")),
        },
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="export_manifest",
            status=status,
            checked_facts={
                "review_finding_count": len(review_findings),
                "blocking_finding_count": len(blocking_findings),
                "citation_chain_count": len(citation_chain),
                "has_evidence_rows": bool(payload.get("evidence_rows")),
                **_compact_projection_mapping(payload, allowed_keys=("format", "filename", "media_type")),
            },
            evidence_refs=_bounded_signal_evidence(
                "export_manifest",
                source_id,
                format=payload.get("format"),
                filename=payload.get("filename"),
            ),
        ),
    )


def _behavior_eval_integrity_signal(source_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Convert observation-mode behavior evals into blocking gate signals."""

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    behavior_status = str(summary.get("behavior_status") or "unresolved")
    if behavior_status == "block":
        status = "block"
        severity = "block"
        message = "Behavior Eval Pack found blocking MCP/agent workflow red flags."
    elif behavior_status == "warn":
        status = "warn"
        severity = "warn"
        message = "Behavior Eval Pack found warning-level MCP/agent workflow red flags."
    elif behavior_status == "pass":
        status = "pass"
        severity = "note"
        message = "Behavior Eval Pack observation run passed without red flags."
    else:
        status = "unresolved"
        severity = "warn"
        message = "Behavior Eval Pack observation run is unresolved."

    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    findings: list[dict[str, Any]] = []
    for result in results[:32]:
        if not isinstance(result, dict):
            continue
        for finding in result.get("findings") or []:
            if not isinstance(finding, dict):
                continue
            _append_unique_mapping(
                findings,
                _compact_projection_mapping(
                    finding,
                    allowed_keys=(
                        "finding_id",
                        "case_id",
                        "category",
                        "severity",
                        "message",
                    ),
                ),
                max_items=12,
            )

    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    next_actions = [
        str(action)
        for action in list(payload.get("next_actions") or [])[:8]
        if _safe_projection_string(action) is not None
    ]
    checked_facts = {
        "mode": payload.get("mode"),
        "structural_status": summary.get("structural_status"),
        "behavior_status": behavior_status,
        "observation_count": summary.get("observation_count"),
        "red_flag_count": summary.get("red_flag_count"),
        "block_count": summary.get("block_count"),
        "warn_count": summary.get("warn_count"),
        "unresolved_count": summary.get("unresolved_count"),
        "finding_count": len(findings),
        "record_written": bool((payload.get("run_record") or {}).get("path"))
        if isinstance(payload.get("run_record"), dict)
        else False,
    }
    evidence_refs = _bounded_signal_evidence(
        "behavior_eval_pack",
        source_id,
        mode=payload.get("mode"),
        behavior_status=behavior_status,
        red_flag_count=summary.get("red_flag_count"),
    )
    return _integrity_signal(
        signal_id=f"behavior_eval:{_digest_json_payload({'source_id': source_id, 'summary': summary})}",
        category="behavior_eval",
        status=status,
        severity=severity,
        message=message,
        evidence=evidence_refs,
        next_actions=next_actions or ["Review behavior-eval findings before making export, handoff, or external-action claims."],
        metadata=_compact_projection_mapping(
            {
                "mode": payload.get("mode"),
                "behavior_status": behavior_status,
                "structural_status": summary.get("structural_status"),
                "red_flag_count": summary.get("red_flag_count"),
                "blocker_count": len(blockers),
                "warning_count": len(warnings),
            }
        ),
        drilldown=_integrity_payload_drilldown(
            source_id=source_id,
            source_kind="behavior_eval_pack",
            status=status,
            checked_facts=checked_facts,
            evidence_refs=evidence_refs,
            replay_refs=[
                {
                    "ref_type": "behavior_eval_pack",
                    "ref_id": source_id,
                    "finding_count": len(findings),
                    "sample_findings": findings[:6],
                }
            ],
        ),
    )


def _project_id_for_job(job: WritingJob, session: WritingSession | None) -> str | None:
    """Return the project id attached to a runtime job or its session."""

    metadata = dict(job.metadata)
    project_id = _metadata_string(metadata, ("project_id", "projectId"))
    if project_id:
        return project_id
    if session is None:
        return None
    return _metadata_string(dict(session.metadata), ("project_id", "projectId"))


def _research_object_id(object_type: str, raw_id: str) -> str:
    """Return a stable namespaced research object identifier."""

    normalized_type = _safe_projection_string(object_type)
    normalized_raw_id = _safe_projection_string(raw_id)
    if normalized_type is None:
        raise ValueError("object_type must not be empty")
    if normalized_raw_id is None:
        raise ValueError("raw_id must not be empty")
    return f"{normalized_type}:{normalized_raw_id}"


def _research_object_type_for_job(job: WritingJob) -> str:
    """Return the research object vocabulary term for a runtime job."""

    metadata = dict(job.metadata)
    explicit_type = _safe_projection_string(metadata.get("research_object_type"))
    if explicit_type:
        return explicit_type
    return _RESEARCH_JOB_KIND_OBJECT_TYPES.get(job.kind.value, "writing_job")


def _raw_research_object_id(object_type: str, metadata: dict[str, Any], fallback: str) -> str:
    """Return the best metadata id for one object type."""

    id_keys = _RESEARCH_OBJECT_ID_KEYS.get(object_type, ())
    return _metadata_string(metadata, id_keys) or fallback


def _research_event_type_for_job_event(job: WritingJob, event: WritingEvent) -> str:
    """Return the domain event type for a runtime event."""

    event_type = event.event_type.value
    return _RESEARCH_JOB_EVENT_TYPES.get(
        (job.kind.value, event_type),
        _RESEARCH_EVENT_TYPE_BY_RUNTIME_EVENT.get(event_type, f"runtime.{event_type}"),
    )


def _source_refs_from_metadata(metadata: dict[str, Any], *, job_id: str | None = None) -> list[dict[str, Any]]:
    """Return bounded source references from runtime metadata."""

    refs: list[dict[str, Any]] = []
    material_id = _metadata_string(metadata, ("material_id", "source_material_id"))
    if material_id:
        refs.append({"ref_type": "material", "ref_id": material_id})
    source_path = _metadata_string(metadata, ("source_path", "input_ref"))
    if source_path:
        refs.append({"ref_type": "source_path", "label": source_path})
    source_paths = metadata.get("source_paths")
    if isinstance(source_paths, list):
        refs.append({"ref_type": "source_paths", "count": len(source_paths)})
    if job_id:
        refs.append({"ref_type": "runtime_job", "ref_id": job_id})
    return refs


def _coerce_job_kind(value: Any) -> tuple[JobKind, str | None]:
    """Return a supported job kind and the original value when it is unknown.

    Why:
        Runtime state can outlive one binary version. Falling back keeps older
        desktops able to load future job records while preserving the raw kind
        in metadata for diagnostics and UI labels.
    """

    raw_kind = str(value or JobKind.PROMPT_ACTION.value)
    try:
        return JobKind(raw_kind), None
    except ValueError:
        return JobKind.PROMPT_ACTION, raw_kind


def _is_http_like_exception(exc: BaseException) -> bool:
    """Return True for FastAPI/Starlette HTTPException-like errors.

    We can't add HTTPException to the recoverable tuple directly because
    importing fastapi at module load adds startup cost. Detect by class name
    walking the MRO so both ``fastapi.HTTPException`` and
    ``starlette.exceptions.HTTPException`` (the former's parent) match.
    """
    for cls in type(exc).__mro__:
        if cls.__name__ == "HTTPException":
            return True
    return False


def _format_http_exception(exc: BaseException) -> str:
    """Render an HTTPException for the job error string."""
    status = getattr(exc, "status_code", None)
    detail = getattr(exc, "detail", None)
    if status and detail:
        return f"HTTP {status}: {detail}"
    if detail:
        return str(detail)
    return str(exc)


def _resolve_workspace_root(entry_cwd: str | Path | None = None) -> Path:
    """Resolve the workspace root, preferring a parent git root when present."""
    candidate = Path(entry_cwd or Path.cwd()).expanduser().resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return parent
    return candidate


def _default_runtime_storage_root() -> Path:
    """Return the default workspace-local storage root for runtime persistence."""
    configured_root = os.environ.get("WRITING_RUNTIME_STORAGE_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    try:
        from project_paths import runtime_state_path

        return runtime_state_path("writing_runtime")
    except Exception:
        return _resolve_workspace_root() / ".modular" / "sessions"


def _stable_workspace_key(workspace_root: Path) -> str:
    """Build a stable workspace key from a normalized root path."""
    return hashlib.sha256(str(workspace_root).encode("utf-8")).hexdigest()


def _default_runtime_db_path() -> Path:
    """Resolve the default SQLite path for the runtime singleton."""
    configured_path = os.environ.get("WRITING_RUNTIME_DB_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return _default_runtime_storage_root() / "index.sqlite3"


@dataclass
class JobExecutionContext:
    """Context for executing a job with runtime state."""
    job: WritingJob
    execution_state: dict[str, Any] = field(default_factory=dict)
    is_paused: bool = False
    is_cancelled: bool = False
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        """Initialize async events if not already set."""
        if not isinstance(self.pause_event, asyncio.Event):
            self.pause_event = asyncio.Event()
        if not isinstance(self.cancel_event, asyncio.Event):
            self.cancel_event = asyncio.Event()
        self.pause_event.set()  # Start as not paused


class WritingRuntime:
    """
    Long-lived backend runtime managing sessions, jobs, events, and artifacts.
    
    Responsibilities:
    - Manage session lifecycle and context
    - Queue, execute, pause, resume, and cancel jobs
    - Emit events for state transitions
    - Store artifacts from job execution
    - Maintain approval gates
    
    In-memory state: Clean interfaces support future persistence to database or file system.
    """

    def __init__(self, database_path: str | Path | None = None, autosave: bool = False):
        """Initialize runtime with empty state and optional SQLite persistence."""
        self._sessions: dict[str, WritingSession] = {}
        self._jobs: dict[str, WritingJob] = {}
        self._job_queue: list[str] = []  # job_ids in order
        self._job_contexts: dict[str, JobExecutionContext] = {}
        self._events: dict[str, list[WritingEvent]] = {}  # events by session_id
        self._artifacts: dict[str, list[WritingArtifact]] = {}  # artifacts by job_id
        self._approval_requests: dict[str, WritingApprovalRequest] = {}
        self._event_subscribers: dict[str, list[Callable]] = {}  # session_id -> callbacks
        self._session_transcripts: dict[str, list[dict[str, Any]]] = {}
        self._session_checkpoints: dict[str, list[dict[str, Any]]] = {}
        self._job_tasks: dict[str, asyncio.Task[Any]] = {}
        self._logger = logging.getLogger(f"{__name__}.{id(self)}")
        self._memory_adapter: Any | None = None
        self._memory_adapter_resolved = False
        self._database_path = Path(database_path).resolve() if database_path is not None else None
        self._repository = None
        if self._database_path is not None:
            try:
                self._repository = WritingRuntimeRepository(self._database_path)
            except (OSError, sqlite3.Error) as exc:
                self._logger.warning("Unable to open SQLite runtime repository at %s: %s", self._database_path, exc)
        self._autosave = autosave and self._repository is not None

        if self._repository is not None and self._repository.is_healthy() and self._repository.has_data():
            self.load_from_database()

    # ==========================================================================
    # Session Management
    # ==========================================================================

    def create_session(
        self,
        mode: SessionMode,
        user_id: str | None = None,
        settings: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingSession:
        """Create a new writing session."""
        normalized_metadata = self._normalize_session_metadata(metadata)
        session = WritingSession.create(
            mode=mode,
            user_id=user_id,
            settings=settings,
            tags=tags,
            metadata=normalized_metadata,
        )
        self._sessions[session.session_id] = session
        self._events[session.session_id] = []
        self._session_transcripts[session.session_id] = []
        self._session_checkpoints[session.session_id] = []
        self._append_transcript_event(
            session.session_id,
            "session_created",
            {
                "session_id": session.session_id,
                "title": session.metadata.get("title", "Untitled session"),
                "workspace_root": session.metadata["workspace_root"],
                "workspace_key": session.metadata["workspace_key"],
                "entry_cwd": session.metadata["entry_cwd"],
            },
        )
        self._create_checkpoint(session.session_id, kind="session_created")
        self._logger.info("Created session %s with mode %s", session.session_id, mode.value)
        self._autosave_if_enabled()
        return session

    def get_session(self, session_id: str) -> WritingSession | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        user_id: str | None = None,
        workspace_key: str | None = None,
        include_archived: bool = False,
    ) -> list[WritingSession]:
        """List sessions, optionally filtered by user and workspace."""
        sessions = list(self._sessions.values())
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        if workspace_key:
            sessions = [s for s in sessions if s.metadata.get("workspace_key") == workspace_key]
        if not include_archived:
            sessions = [s for s in sessions if s.metadata.get("status", "active") != "archived"]
        sessions.sort(key=lambda session: session.metadata.get("updated_at", session.created_at), reverse=True)
        return sessions

    def get_current_session(
        self,
        workspace_root: str | Path | None = None,
        workspace_key: str | None = None,
        entry_cwd: str | Path | None = None,
    ) -> WritingSession | None:
        """Return the most recently active session for a workspace binding."""
        resolved_workspace_key = workspace_key
        if resolved_workspace_key is None:
            root_candidate = Path(workspace_root).expanduser().resolve() if workspace_root else _resolve_workspace_root(entry_cwd)
            resolved_workspace_key = _stable_workspace_key(root_candidate)
        sessions = self.list_sessions(workspace_key=resolved_workspace_key)
        return sessions[0] if sessions else None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all runtime state owned by it.

        Args:
            session_id: Existing runtime session identifier.

        Returns:
            True when a session was deleted; False when it did not exist.

        Raises:
            ValueError: If ``session_id`` is blank.
        """
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        if normalized not in self._sessions:
            return False

        job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.session_id == normalized
        ]
        approval_ids = [
            approval_id
            for approval_id, approval in self._approval_requests.items()
            if approval.session_id == normalized
        ]

        self._sessions.pop(normalized, None)
        self._events.pop(normalized, None)
        self._session_transcripts.pop(normalized, None)
        self._session_checkpoints.pop(normalized, None)
        self._event_subscribers.pop(normalized, None)
        for job_id in job_ids:
            self._jobs.pop(job_id, None)
            self._job_contexts.pop(job_id, None)
            self._artifacts.pop(job_id, None)
        job_id_set = set(job_ids)
        self._job_queue = [job_id for job_id in self._job_queue if job_id not in job_id_set]
        for approval_id in approval_ids:
            self._approval_requests.pop(approval_id, None)

        if self._repository is not None:
            self._repository.delete_session(normalized)
        self._autosave_if_enabled()
        self._logger.info("Deleted session %s", normalized)
        return True

    def resume_session(
        self,
        session_id: str | None = None,
        workspace_root: str | Path | None = None,
        workspace_key: str | None = None,
        entry_cwd: str | Path | None = None,
    ) -> dict[str, Any]:
        """Resume a session by ID or current workspace binding."""
        session = self.get_session(session_id) if session_id else self.get_current_session(
            workspace_root=workspace_root,
            workspace_key=workspace_key,
            entry_cwd=entry_cwd,
        )
        if session is None:
            raise ValueError("No resumable session found")
        timeline = self.get_session_timeline(session.session_id, limit=100)
        return {
            "session": session.to_dict(),
            "head_event_id": session.metadata.get("head_event_id"),
            "head_checkpoint_id": session.metadata.get("head_checkpoint_id"),
            "timeline": timeline["items"],
            "next_cursor": timeline["next_cursor"],
        }

    def get_session_timeline(
        self,
        session_id: str,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return the active transcript lineage for a session with cursor pagination."""
        active_timeline = self._get_active_transcript(session_id)
        if after_event_id is not None:
            cursor_index = next(
                (index for index, event in enumerate(active_timeline) if event["event_id"] == after_event_id),
                None,
            )
            if cursor_index is not None:
                active_timeline = active_timeline[cursor_index + 1 :]
        items = active_timeline[:limit]
        next_cursor = items[-1]["event_id"] if len(active_timeline) > limit and items else None
        session = self.get_session(session_id)
        return {
            "session_id": session_id,
            "head_event_id": session.metadata.get("head_event_id") if session else None,
            "items": items,
            "next_cursor": next_cursor,
        }

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """List checkpoints for a session, annotating active lineage membership."""
        active_event_ids = {event["event_id"] for event in self._get_active_transcript(session_id)}
        checkpoints = []
        for checkpoint in self._session_checkpoints.get(session_id, []):
            enriched = dict(checkpoint)
            enriched["active"] = checkpoint["event_id"] in active_event_ids
            checkpoints.append(enriched)
        checkpoints.sort(key=lambda item: item["created_at"])
        return checkpoints

    def rewind_session(self, session_id: str, checkpoint_id: str, mode: str = "conversation_only") -> dict[str, Any]:
        """Rewind the active session head back to a stored checkpoint lineage."""
        checkpoint = self._get_checkpoint(session_id, checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for session {session_id}")
        self._append_transcript_event(
            session_id,
            "session_rewound",
            {
                "checkpoint_id": checkpoint_id,
                "mode": mode,
                "workspace_restore_supported": mode != "conversation_only",
                "workspace_restore_limited": mode != "conversation_only",
            },
            parent_event_id=checkpoint["event_id"],
        )
        self._replace_session_metadata(session_id, head_checkpoint_id=checkpoint_id)
        self._autosave_if_enabled()
        return self.resume_session(session_id=session_id)

    def fork_session(
        self,
        session_id: str,
        checkpoint_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Create a branch session seeded from an existing checkpoint lineage."""
        source_session = self.get_session(session_id)
        if source_session is None:
            raise ValueError(f"Session {session_id} not found")
        checkpoint = self._get_checkpoint(session_id, checkpoint_id)
        if checkpoint is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for session {session_id}")

        source_lineage = self._get_lineage_to_event(session_id, checkpoint["event_id"])
        source_checkpoint_map = {
            item["event_id"]: item
            for item in self._session_checkpoints.get(session_id, [])
            if item["event_id"] in {event["event_id"] for event in source_lineage}
        }

        fork_metadata = self._normalize_session_metadata(
            {
                **dict(source_session.metadata),
                "title": title or f"{source_session.metadata.get('title', 'Session')} (fork)",
                "parent_session_id": session_id,
                "forked_from_checkpoint_id": checkpoint_id,
                "forked_from_turn_id": checkpoint["metadata"].get("source_job_id"),
            }
        )
        fork_metadata["head_event_id"] = None
        fork_metadata["head_checkpoint_id"] = None
        forked_session = WritingSession.create(
            mode=source_session.mode,
            user_id=source_session.user_id,
            settings=dict(source_session.settings),
            tags=list(source_session.tags),
            metadata=fork_metadata,
        )
        self._sessions[forked_session.session_id] = forked_session
        self._events[forked_session.session_id] = []
        self._session_transcripts[forked_session.session_id] = []
        self._session_checkpoints[forked_session.session_id] = []

        event_id_map: dict[str, str] = {}
        copied_transcript: list[dict[str, Any]] = []
        copied_checkpoints: list[dict[str, Any]] = []
        for source_event in source_lineage:
            new_event_id = f"evt_{os.urandom(8).hex()}"
            event_id_map[source_event["event_id"]] = new_event_id
            copied_transcript.append(
                {
                    **source_event,
                    "event_id": new_event_id,
                    "session_id": forked_session.session_id,
                    "parent_event_id": event_id_map.get(source_event.get("parent_event_id")),
                }
            )
            source_checkpoint = source_checkpoint_map.get(source_event["event_id"])
            if source_checkpoint is not None:
                copied_checkpoints.append(
                    {
                        "checkpoint_id": f"chk_{os.urandom(8).hex()}",
                        "session_id": forked_session.session_id,
                        "event_id": new_event_id,
                        "created_at": source_checkpoint["created_at"],
                        "kind": source_checkpoint["kind"],
                        "metadata": {
                            **dict(source_checkpoint.get("metadata") or {}),
                            "source_checkpoint_id": source_checkpoint["checkpoint_id"],
                        },
                    }
                )

        self._session_transcripts[forked_session.session_id] = copied_transcript
        self._session_checkpoints[forked_session.session_id] = copied_checkpoints
        copied_target_checkpoint = next(
            (
                item
                for item in copied_checkpoints
                if item["metadata"].get("source_checkpoint_id") == checkpoint_id
            ),
            None,
        )
        self._replace_session_metadata(
            forked_session.session_id,
            head_event_id=event_id_map[checkpoint["event_id"]],
            head_checkpoint_id=copied_target_checkpoint["checkpoint_id"] if copied_target_checkpoint else None,
        )
        if self._repository is not None:
            self._repository.replace_transcript(forked_session.session_id, copied_transcript)

        self._append_transcript_event(
            forked_session.session_id,
            "session_forked",
            {
                "source_session_id": session_id,
                "source_checkpoint_id": checkpoint_id,
            },
            parent_event_id=event_id_map[checkpoint["event_id"]],
        )
        self._create_checkpoint(forked_session.session_id, kind="session_forked")
        self._autosave_if_enabled()
        return self.resume_session(session_id=forked_session.session_id)

    # ==========================================================================
    # Job Management
    # ==========================================================================

    def create_job(
        self,
        session_id: str,
        kind: JobKind,
        input_text: str = "",
        action_id: str | None = None,
        skill_id: str | None = None,
        scope: str | None = None,
        output_mode: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingJob:
        """Create a new job in a session."""
        session = self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        job = WritingJob.create(
            session_id=session_id,
            kind=kind,
            input_text=input_text,
            action_id=action_id,
            skill_id=skill_id,
            scope=scope,
            output_mode=output_mode,
            tags=tags,
            metadata=metadata,
        )

        self._jobs[job.job_id] = job
        self._job_queue.append(job.job_id)
        self._job_contexts[job.job_id] = JobExecutionContext(job=job)
        self._artifacts[job.job_id] = []

        # Emit job created event
        self._emit_event(
            session_id,
            WritingEvent.create(
                job_id=job.job_id,
                session_id=session_id,
                event_type=EventType.JOB_CREATED,
                data={
                    "job_id": job.job_id,
                    "kind": kind.value,
                    "input_text": input_text,
                    "action_id": action_id,
                    "skill_id": skill_id,
                },
            ),
        )

        self._logger.info("Created job %s in session %s", job.job_id, session_id)
        return job

    def get_job(self, job_id: str) -> WritingJob | None:
        """Retrieve a job by ID."""
        return self._jobs.get(job_id)

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and all runtime data owned by that job.

        Args:
            job_id: Existing runtime job identifier.

        Returns:
            True when the job existed and was removed; False when it was absent.

        Raises:
            ValueError: If ``job_id`` is blank.
        """
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self._jobs.get(normalized)
        if job is None:
            return False

        task = self._job_tasks.pop(normalized, None)
        if task is not None and not task.done():
            task.cancel()

        session_id = job.session_id
        self._jobs.pop(normalized, None)
        self._job_contexts.pop(normalized, None)
        self._artifacts.pop(normalized, None)
        self._job_queue = [queued_id for queued_id in self._job_queue if queued_id != normalized]
        self._approval_requests = {
            approval_id: approval
            for approval_id, approval in self._approval_requests.items()
            if approval.job_id != normalized
        }
        self._events[session_id] = [
            event
            for event in self._events.get(session_id, [])
            if event.job_id != normalized
        ]
        self._session_checkpoints[session_id] = [
            checkpoint
            for checkpoint in self._session_checkpoints.get(session_id, [])
            if dict(checkpoint.get("metadata") or {}).get("source_job_id") != normalized
        ]

        self._ensure_transcript_loaded(session_id)
        filtered_transcript = [
            event
            for event in self._session_transcripts.get(session_id, [])
            if not self._transcript_event_references_job(event, normalized)
        ]
        self._session_transcripts[session_id] = filtered_transcript
        if self.get_session(session_id) is not None:
            remaining_checkpoint_ids = {
                str(checkpoint.get("checkpoint_id"))
                for checkpoint in self._session_checkpoints.get(session_id, [])
            }
            current_session = self.get_session(session_id)
            current_head_event_id = str(current_session.metadata.get("head_event_id") or "") if current_session else ""
            current_head_checkpoint_id = str(current_session.metadata.get("head_checkpoint_id") or "") if current_session else ""
            remaining_event_ids = {
                str(event.get("event_id"))
                for event in filtered_transcript
                if isinstance(event, dict)
            }
            metadata_updates: dict[str, Any] = {}
            if current_head_event_id and current_head_event_id not in remaining_event_ids:
                metadata_updates["head_event_id"] = filtered_transcript[-1]["event_id"] if filtered_transcript else None
            if current_head_checkpoint_id and current_head_checkpoint_id not in remaining_checkpoint_ids:
                checkpoints = self._session_checkpoints.get(session_id, [])
                metadata_updates["head_checkpoint_id"] = checkpoints[-1]["checkpoint_id"] if checkpoints else None
            if metadata_updates:
                self._replace_session_metadata(session_id, **metadata_updates)
            if self._repository is not None:
                self._repository.replace_transcript(session_id, filtered_transcript)

        self._autosave_if_enabled()
        self._logger.info("Deleted job %s and its runtime data", normalized)
        return True

    @staticmethod
    def _transcript_event_references_job(event: dict[str, Any], job_id: str) -> bool:
        """Return True when a transcript event belongs to the target job."""
        if not isinstance(event, dict):
            return False
        payload = event.get("payload")
        if isinstance(payload, dict):
            if str(payload.get("job_id") or "") == job_id:
                return True
            if str(payload.get("source_job_id") or "") == job_id:
                return True
        return False

    def list_jobs(self, session_id: str, status: JobStatus | None = None) -> list[WritingJob]:
        """List all jobs in a session, optionally filtered by status."""
        jobs = [j for j in self._jobs.values() if j.session_id == session_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        return jobs

    def query_job_status(self, job_id: str) -> dict[str, Any]:
        """Query current job status with detailed information."""
        job = self.get_job(job_id)
        if not job:
            return {"error": f"Job {job_id} not found"}

        ctx = self._job_contexts.get(job_id)
        return {
            "job_id": job_id,
            "session_id": job.session_id,
            "status": job.status.value,
            "kind": job.kind.value,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "is_paused": ctx.is_paused if ctx else False,
            "is_cancelled": ctx.is_cancelled if ctx else False,
            "error": job.error,
            "metadata": dict(job.metadata),
        }

    def get_job_event_head_sequence(self, job_id: str) -> int:
        """Return the highest event sequence currently recorded for a job.

        Args:
            job_id: Runtime job identifier.

        Returns:
            The highest per-job sequence, or ``0`` when the job has no events.

        Raises:
            ValueError: If ``job_id`` is blank.
        """
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized)
        if job is None:
            return 0
        self._ensure_session_event_sequences(job.session_id)
        return max(
            (event.sequence for event in self._events.get(job.session_id, []) if event.job_id == normalized),
            default=0,
        )

    @staticmethod
    def _coerce_event_sequence(value: Any) -> int:
        """Coerce persisted sequence values into the safe non-negative range."""
        if isinstance(value, bool):
            return 0
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    def _next_event_sequence(self, job_id: str) -> int:
        """Return the next monotonic sequence value for one job."""
        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        highest = 0
        for events in self._events.values():
            for event in events:
                if event.job_id == normalized and event.sequence > highest:
                    highest = event.sequence
        return highest + 1

    def _with_event_sequence(self, event: WritingEvent) -> WritingEvent:
        """Attach a per-job sequence when an incoming event does not have one."""
        if event.sequence > 0:
            return event
        return replace(event, sequence=self._next_event_sequence(event.job_id))

    def _ensure_session_event_sequences(self, session_id: str) -> None:
        """Backfill missing event sequences for old in-memory or persisted state."""
        events = self._events.get(session_id, [])
        if not events:
            return
        next_by_job: dict[str, int] = {}
        for event in events:
            current_sequence = self._coerce_event_sequence(event.sequence)
            if current_sequence > 0:
                next_by_job[event.job_id] = max(next_by_job.get(event.job_id, 1), current_sequence + 1)
        normalized_events: list[WritingEvent] = []
        changed = False
        for event in sorted(events, key=lambda item: (item.timestamp, item.event_id)):
            job_id = event.job_id
            current_sequence = self._coerce_event_sequence(event.sequence)
            if current_sequence > 0:
                normalized_events.append(event if current_sequence == event.sequence else replace(event, sequence=current_sequence))
                changed = changed or current_sequence != event.sequence
                continue
            next_sequence = next_by_job.get(job_id, 1)
            next_by_job[job_id] = next_sequence + 1
            normalized_events.append(replace(event, sequence=next_sequence))
            changed = True
        if changed:
            self._events[session_id] = normalized_events

    def emit_job_progress(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Append a machine-readable progress event for a running job.

        Args:
            job_id: Existing runtime job identifier.
            stage: Stable stage key, short ASCII or Chinese label.
            message: User-facing progress summary.
            progress: Optional 0..100 progress percentage.
            data: Optional JSON-serializable event payload extensions.

        Raises:
            ValueError: If the job does not exist or payload fields are blank.
        """
        normalized_stage = str(stage or "").strip()
        normalized_message = str(message or "").strip()
        if not normalized_stage:
            raise ValueError("stage must not be empty")
        if not normalized_message:
            raise ValueError("message must not be empty")
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        payload: dict[str, Any] = {
            "stage": normalized_stage,
            "message": normalized_message,
        }
        if progress is not None:
            payload["progress"] = max(0, min(100, int(progress)))
        if data:
            payload.update(dict(data))
        metadata = dict(job.metadata)
        metadata.update(
            {
                "progress_stage": normalized_stage,
                "progress_message": normalized_message,
                **({"progress": payload["progress"]} if "progress" in payload else {}),
            }
        )
        self._jobs[job_id] = replace(job, metadata=metadata)
        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PROGRESS,
                data=payload,
            ),
        )
        self._autosave_if_enabled()

    # ==========================================================================
    # Job Lifecycle Control
    # ==========================================================================

    async def start_job(self, job_id: str, executor: Callable[[WritingJob], Any] | None = None) -> WritingJob:
        """
        Start executing a job.
        
        If executor is provided, it will be called asynchronously.
        The executor should handle pause/resume/cancel via the context.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Transition to STARTED
        job = job.with_status(JobStatus.STARTED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_STARTED,
            ),
        )

        self._logger.info("Started job %s", job_id)

        if executor:
            task = asyncio.create_task(self._run_job_executor(job_id, executor))
            self._job_tasks[job_id] = task

        self._autosave_if_enabled()
        return self.get_job(job_id) or job

    async def _run_job_executor(self, job_id: str, executor: Callable[[WritingJob], Any]) -> None:
        """Run a job executor outside the request path and finalize its result."""
        job = self.get_job(job_id)
        if not job:
            self._job_tasks.pop(job_id, None)
            return
        try:
            ctx = self._job_contexts.get(job_id)
            if ctx and ctx.is_cancelled:
                return
            job = job.with_status(JobStatus.IN_PROGRESS)
            self._jobs[job_id] = job
            self._emit_event(
                job.session_id,
                WritingEvent.create(
                    job_id=job_id,
                    session_id=job.session_id,
                    event_type=EventType.JOB_PROGRESS,
                    data={"stage": "running", "message": "任务已进入后台执行"},
                ),
            )
            executor_result = executor(job)
            if inspect.isawaitable(executor_result):
                executor_result = await executor_result
            ctx = self._job_contexts.get(job_id)
            current = self.get_job(job_id)
            if (ctx and ctx.is_cancelled) or (current and current.status == JobStatus.CANCELLED):
                return
            await self._finalize_executor_result(job_id, executor_result)
        except asyncio.CancelledError:
            current = self.get_job(job_id)
            if current and current.status != JobStatus.CANCELLED:
                await self.cancel_job(job_id)
            raise
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
            current = self.get_job(job_id)
            if current and current.status != JobStatus.CANCELLED:
                self._logger.error("Executor error for job %s: %s", job_id, exc)
                await self.fail_job(job_id, str(exc))
        except BaseException as exc:  # noqa: BLE001 — must not silently drop FastAPI HTTPException; UI relies on JOB_FAILED event.
            # HTTPException (FastAPI/Starlette) inherits from Exception, not the
            # narrow recoverable tuple above. Without this branch, a 400/401
            # from chat/embedding/rerank providers escapes asyncio as
            # "Task exception was never retrieved" and the job stays
            # IN_PROGRESS forever — the UI calls this "stuck at 1800s".
            if _is_http_like_exception(exc):
                current = self.get_job(job_id)
                if current and current.status != JobStatus.CANCELLED:
                    msg = _format_http_exception(exc)
                    self._logger.error("HTTP error for job %s: %s", job_id, msg)
                    await self.fail_job(job_id, msg)
                return  # swallow — fail_job already emitted JOB_FAILED
            raise  # truly unknown error: surface to asyncio, don't lie
        finally:
            self._job_tasks.pop(job_id, None)
            self._autosave_if_enabled()

    async def pause_job(self, job_id: str) -> WritingJob:
        """Pause a running job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status not in (JobStatus.STARTED, JobStatus.IN_PROGRESS):
            raise ValueError(f"Cannot pause job in status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_paused = True
            ctx.pause_event.clear()

        job = job.with_status(JobStatus.PAUSED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PAUSED,
            ),
        )

        self._logger.info("Paused job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def resume_job(self, job_id: str) -> WritingJob:
        """Resume a paused job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status != JobStatus.PAUSED:
            raise ValueError(f"Cannot resume job in status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_paused = False
            ctx.pause_event.set()

        job = job.with_status(JobStatus.IN_PROGRESS)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_RESUMED,
            ),
        )

        self._logger.info("Resumed job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def cancel_job(self, job_id: str) -> WritingJob:
        """Cancel a job."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError(f"Cannot cancel job already in terminal status {job.status.value}")

        ctx = self._job_contexts.get(job_id)
        if ctx:
            ctx.is_cancelled = True
            ctx.cancel_event.set()
        task = self._job_tasks.pop(job_id, None)
        if task is not None and not task.done():
            task.cancel()

        job = job.with_status(JobStatus.CANCELLED)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_CANCELLED,
            ),
        )

        self._logger.info("Cancelled job %s", job_id)
        self._create_checkpoint(job.session_id, kind="job_cancelled", source_job_id=job_id)
        self._autosave_if_enabled()
        return job

    def update_job_metadata(self, job_id: str, updates: dict[str, Any]) -> WritingJob:
        """Merge JSON-safe metadata into one runtime job.

        Args:
            job_id: Existing runtime job identifier.
            updates: Object-shaped metadata patch. Keys with ``None`` values are
                preserved because downstream routes use explicit nulls as state.

        Returns:
            Updated immutable job record.

        Raises:
            ValueError: If the job does not exist or updates is not an object.
        """
        if not isinstance(updates, dict):
            raise ValueError("updates must be a metadata object")
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        metadata = dict(job.metadata)
        metadata.update(dict(updates))
        updated = replace(job, metadata=metadata)
        self._jobs[job_id] = updated
        self._autosave_if_enabled()
        return updated

    def update_writing_workflow_state(
        self,
        job_id: str,
        *,
        phase: str,
        intake: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        citation_bank: list[dict[str, Any]] | None = None,
        lint_report: dict[str, Any] | None = None,
        export_manifest: dict[str, Any] | None = None,
        change_log: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Persist an auditable writing workflow-state snapshot.

        Args:
            job_id: Existing runtime job identifier.
            phase: Non-empty workflow phase label owned by writing/runtime code.
            intake: User-confirmed task, venue, medium, language, and policy facts.
            evidence_refs: Claim/evidence support rows without full source bodies.
            citation_bank: Citation-support rows linked to evidence refs.
            lint_report: Deterministic writing-quality gate output.
            export_manifest: Medium-specific export artifact metadata.
            change_log: Ordered workflow-state change summaries.

        Returns:
            JSON-safe workflow state stored in job metadata and METADATA artifact.

        Raises:
            ValueError: If the job does not exist or state fields have invalid shapes.
        """

        normalized_phase = str(phase or "").strip()
        if not normalized_phase:
            raise ValueError("phase must be a non-empty string")
        job = self.get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        prior = self.get_writing_workflow_state(job_id) or {}
        state: dict[str, Any] = {
            **prior,
            "schema_version": "writing_workflow_state_v1",
            "job_id": job.job_id,
            "session_id": job.session_id,
            "phase": normalized_phase,
            "updated_at": utc_now_iso_z(),
        }
        object_updates = {
            "intake": intake,
            "lint_report": lint_report,
            "export_manifest": export_manifest,
        }
        for field_name, value in object_updates.items():
            if value is not None or field_name not in state:
                state[field_name] = _require_object(value, field_name=field_name)
        list_updates = {
            "evidence_refs": evidence_refs,
            "citation_bank": citation_bank,
            "change_log": change_log,
        }
        for field_name, value in list_updates.items():
            if value is not None or field_name not in state:
                state[field_name] = _require_object_list(value, field_name=field_name)
        state["readiness"] = _workflow_readiness(state)

        metadata = dict(job.metadata)
        metadata[_WRITING_WORKFLOW_STATE_KEY] = dict(state)
        updated_job = replace(job, metadata=metadata)
        self._jobs[job_id] = updated_job

        self._store_artifact(
            WritingArtifact.create(
                job_id=job_id,
                session_id=job.session_id,
                artifact_type=ArtifactType.METADATA,
                content={
                    "kind": _WRITING_WORKFLOW_STATE_KEY,
                    "state": dict(state),
                },
                created_by="writing_runtime",
                metadata={
                    "workflow_phase": normalized_phase,
                    "schema_version": state["schema_version"],
                },
                mime_type="application/json",
            )
        )
        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PROGRESS,
                data={
                    "workflow_state_updated": True,
                    "workflow_phase": normalized_phase,
                    "readiness": dict(state["readiness"]),
                },
            ),
        )
        self._autosave_if_enabled()
        return dict(state)

    def get_writing_workflow_state(self, job_id: str) -> dict[str, Any] | None:
        """Return the latest persisted writing workflow-state snapshot.

        Args:
            job_id: Existing runtime job identifier.

        Returns:
            Detached workflow-state object, or None when the job has no state.

        Raises:
            ValueError: If ``job_id`` is blank or unknown.
        """

        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized)
        if job is None:
            raise ValueError(f"Job {normalized} not found")
        state = job.metadata.get(_WRITING_WORKFLOW_STATE_KEY)
        if state is None:
            return None
        if not isinstance(state, dict):
            raise ValueError("writing_workflow_state metadata must be an object")
        return dict(_json_safe_copy(state))

    def build_writing_readiness_claims(self, job_id: str) -> dict[str, Any]:
        """Build gate-derived readiness claims for one writing workflow job.

        Args:
            job_id: Runtime job id whose workflow-state summary is being read.

        Returns:
            Read-only claim state derived from the Evidence Integrity Gate.

        Raises:
            ValueError: If the job id is blank or unknown.
        """

        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized)
        if job is None:
            raise ValueError(f"Job {normalized} not found")
        workflow_state = job.metadata.get(_WRITING_WORKFLOW_STATE_KEY)
        if workflow_state is not None and not isinstance(workflow_state, dict):
            workflow_state = None
        session = self.get_session(job.session_id)
        gate = self.build_evidence_integrity_gate(
            session_id=job.session_id,
            job_id=job.job_id,
            project_id=_project_id_for_job(job, session),
            limit=500,
        )
        return _workflow_readiness_claims(
            workflow_state=workflow_state,
            gate=gate,
        )

    def build_action_preflight(
        self,
        *,
        action_id: str,
        required_claim_id: str,
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        require_ready: bool = False,
        workflow_state: dict[str, Any] | None = None,
        persist_refresh_receipt: bool = False,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Build a read-only preflight projection before export or handoff actions.

        Args:
            action_id: Stable local action identifier.
            required_claim_id: Workflow readiness claim that represents the action.
            session_id: Optional runtime session scope.
            job_id: Optional runtime job scope.
            project_id: Optional project scope.
            require_ready: Whether a non-ready claim blocks the action.
            workflow_state: Optional just-built workflow state for new export jobs.
            persist_refresh_receipt: Whether to attach a local refresh/replay
                receipt to the owning job when ``job_id`` is available.
            limit: Maximum runtime rows used by the projections.

        Returns:
            Versioned action preflight payload with passport, gate, and claim refs.

        Raises:
            ValueError: If ids are blank or scoped runtime records are missing.
        """

        normalized_action_id = str(action_id or "").strip()
        normalized_claim_id = str(required_claim_id or "").strip()
        if not normalized_action_id:
            raise ValueError("action_id must not be empty")
        if not normalized_claim_id:
            raise ValueError("required_claim_id must not be empty")
        if workflow_state is not None and not isinstance(workflow_state, dict):
            raise ValueError("workflow_state must be an object when provided")
        passport = self.build_workflow_passport(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )
        gate = self.build_evidence_integrity_gate(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )
        if workflow_state is None and job_id:
            try:
                workflow_state = self.get_writing_workflow_state(job_id)
            except ValueError:
                workflow_state = None
        readiness_claims = _workflow_readiness_claims(
            workflow_state=workflow_state,
            gate=gate,
        )
        preflight = _workflow_action_preflight_payload(
            action_id=normalized_action_id,
            required_claim_id=normalized_claim_id,
            passport=passport,
            gate=gate,
            readiness_claims=readiness_claims,
            require_ready=bool(require_ready),
            workflow_state=workflow_state,
        )
        receipt = _workflow_refresh_receipt_payload(
            action_preflight=preflight,
            passport=passport,
            gate=gate,
            readiness_claims=readiness_claims,
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
        )
        receipt_ref = {
            "ref_type": "preflight_refresh_receipt",
            "ref_id": receipt["receipt_id"],
            "schema_version": receipt["schema_version"],
            "generated_at": receipt["generated_at"],
            "status": receipt["status"],
        }
        evidence = list(preflight.get("evidence") or [])
        _append_unique_mapping(evidence, receipt_ref, max_items=16)
        preflight = {
            **preflight,
            "refresh_receipt_id": receipt["receipt_id"],
            "refresh_receipt": receipt,
            "evidence": evidence[:16],
            "summary": {
                **dict(preflight.get("summary") or {}),
                "refresh_receipt_id": receipt["receipt_id"],
            },
            "provenance": {
                **dict(preflight.get("provenance") or {}),
                "refresh_receipt_schema_version": receipt["schema_version"],
            },
        }
        if persist_refresh_receipt and job_id:
            persisted_receipt = self.persist_preflight_refresh_receipt(job_id, receipt)
            preflight = {
                **preflight,
                "refresh_receipt": persisted_receipt,
                "refresh_receipt_id": persisted_receipt["receipt_id"],
            }
        return preflight

    def persist_preflight_refresh_receipt(
        self,
        job_id: str,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one preflight refresh receipt as local replay evidence.

        Args:
            job_id: Existing runtime job that owns the command or handoff.
            receipt: Versioned receipt returned by the action-preflight builder.

        Returns:
            JSON-safe receipt content after metadata and artifact persistence.

        Raises:
            ValueError: If the job is missing or receipt shape is invalid.
        """

        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        if not isinstance(receipt, dict):
            raise ValueError("preflight refresh receipt must be an object")
        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")
        normalized_receipt = dict(_json_safe_copy(receipt))
        if normalized_receipt.get("schema_version") != _PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION:
            raise ValueError("preflight refresh receipt schema_version is invalid")
        receipt_id = _require_non_empty_string(
            normalized_receipt.get("receipt_id"),
            field_name="preflight_refresh_receipt.receipt_id",
            max_length=200,
        )

        metadata = dict(job.metadata)
        prior_receipts = metadata.get(_PREFLIGHT_REFRESH_RECEIPTS_KEY)
        receipts = (
            [
                dict(item)
                for item in prior_receipts
                if isinstance(item, dict) and item.get("receipt_id") != receipt_id
            ]
            if isinstance(prior_receipts, list)
            else []
        )
        receipts.append(normalized_receipt)
        metadata[_PREFLIGHT_REFRESH_RECEIPTS_KEY] = receipts[-12:]
        metadata["latest_preflight_refresh_receipt"] = normalized_receipt
        updated = replace(job, metadata=metadata)
        self._jobs[normalized_job_id] = updated
        self._store_artifact(
            WritingArtifact.create(
                job_id=job.job_id,
                session_id=job.session_id,
                artifact_type=ArtifactType.METADATA,
                content=normalized_receipt,
                created_by="runtime",
                metadata={
                    "kind": "preflight_refresh_receipt",
                    "schema_version": _PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION,
                    "receipt_id": receipt_id,
                    "action_id": normalized_receipt.get("action_id"),
                    "project_id": (normalized_receipt.get("scope") or {}).get("project_id")
                    if isinstance(normalized_receipt.get("scope"), dict)
                    else None,
                    "status": normalized_receipt.get("status"),
                    "refresh_required": bool(normalized_receipt.get("refresh_required")),
                },
                mime_type="application/json",
            )
        )
        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job.job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PROGRESS,
                data={
                    "preflight_refresh_receipt_recorded": True,
                    "receipt_id": receipt_id,
                    "action_id": normalized_receipt.get("action_id"),
                    "status": normalized_receipt.get("status"),
                },
            ),
        )
        self._autosave_if_enabled()
        return normalized_receipt

    def get_preflight_refresh_receipt(
        self,
        job_id: str,
        receipt_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a persisted preflight refresh receipt for one runtime job.

        Args:
            job_id: Existing runtime job identifier.
            receipt_id: Optional receipt id. When omitted, the latest receipt is
                returned from job metadata.

        Returns:
            Detached receipt object, or None when no matching receipt exists.

        Raises:
            ValueError: If the job id is blank, unknown, or receipt metadata is corrupt.
        """

        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        normalized_receipt_id = str(receipt_id or "").strip() if receipt_id is not None else None
        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")
        candidates: list[dict[str, Any]] = []
        latest = job.metadata.get("latest_preflight_refresh_receipt")
        if isinstance(latest, dict):
            candidates.append(dict(latest))
        stored = job.metadata.get(_PREFLIGHT_REFRESH_RECEIPTS_KEY)
        if isinstance(stored, list):
            for item in stored:
                if isinstance(item, dict):
                    candidates.append(dict(item))
        for artifact in reversed(self.get_job_artifacts(normalized_job_id, ArtifactType.METADATA)):
            if artifact.metadata.get("kind") != "preflight_refresh_receipt":
                continue
            if isinstance(artifact.content, dict):
                candidates.append(dict(artifact.content))
        if not candidates:
            return None
        for candidate in candidates:
            if candidate.get("schema_version") != _PREFLIGHT_REFRESH_RECEIPT_SCHEMA_VERSION:
                continue
            if normalized_receipt_id is None or candidate.get("receipt_id") == normalized_receipt_id:
                return dict(_json_safe_copy(candidate))
        return None

    def build_workflow_replay_lineage(
        self,
        job_id: str,
        *,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Build a compact replay lineage for one job's preflight receipts.

        Args:
            job_id: Existing runtime job identifier.
            limit: Maximum compact receipt rows returned, from 1 through 50.

        Returns:
            Read-only lineage projection comparing latest and prior receipts.

        Raises:
            ValueError: If the job id is blank, unknown, or limit is invalid.
        """

        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        if isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        if normalized_limit < 1 or normalized_limit > 50:
            raise ValueError("limit must be between 1 and 50")

        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")

        receipts, receipt_counts = _collect_job_preflight_receipts(
            job,
            self.get_job_artifacts(normalized_job_id),
        )

        receipts.sort(key=_receipt_timestamp_key)
        latest = receipts[-1] if receipts else None
        previous = receipts[-2] if len(receipts) > 1 else None
        latest_row = _compact_refresh_receipt_row(latest, ordinal=len(receipts)) if latest is not None else None
        previous_row = _compact_refresh_receipt_row(previous, ordinal=len(receipts) - 1) if previous is not None else None
        bounded_receipts = receipts[-normalized_limit:]
        items = [
            _compact_refresh_receipt_row(receipt, ordinal=(len(receipts) - len(bounded_receipts) + index + 1))
            for index, receipt in enumerate(bounded_receipts)
        ]

        blockers: list[str] = []
        unresolved: list[str] = []
        if latest is not None:
            latest_counts = _receipt_validation_counts(latest)
            latest_status = _safe_projection_string(latest.get("status")) or "unresolved"
            if latest_status == "blocked" or latest_counts["blocker_count"] > 0:
                _append_unique_text(
                    blockers,
                    f"Latest replay receipt reports {latest_counts['blocker_count']} blocking checks.",
                    max_items=8,
                )
            if latest_status in {"unresolved", "stale"} or latest_counts["unresolved_count"] > 0:
                _append_unique_text(
                    unresolved,
                    f"Latest replay receipt reports {latest_counts['unresolved_count']} unresolved checks.",
                    max_items=8,
                )
            if bool(latest.get("refresh_required")):
                _append_unique_text(
                    unresolved,
                    "Latest replay still requires a Workflow Passport and Evidence Integrity Gate refresh.",
                    max_items=8,
                )

        session = self.get_session(job.session_id)
        project_id = _project_id_for_job(job, session)
        scope = {
            "session_id": job.session_id,
            "job_id": job.job_id,
            "project_id": project_id,
        }
        resume_probes = [
            _handoff_resume_probe("Read runtime job", f"/runtime/job/{job.job_id}"),
            _handoff_resume_probe("Read runtime snapshot", f"/runtime/job/{job.job_id}/snapshot"),
            _handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{job.job_id}/workflow-replay-lineage"),
        ]
        if latest_row and latest_row.get("receipt_id"):
            resume_probes.append(
                _handoff_resume_probe(
                    "Read latest workflow refresh receipt",
                    f"/runtime/job/{job.job_id}/preflight-refresh-receipt",
                    {"receipt_id": str(latest_row["receipt_id"])},
                )
            )

        lineage = {
            "schema_version": _WORKFLOW_REPLAY_LINEAGE_SCHEMA_VERSION,
            "generated_at": utc_now_iso_z(),
            "job_id": job.job_id,
            "session_id": job.session_id,
            "project_id": project_id,
            "scope": scope,
            "receipt_count": len(receipts),
            "returned_count": len(items),
            "latest_receipt_id": latest_row.get("receipt_id") if latest_row else None,
            "latest": latest_row or {},
            "previous": previous_row or {},
            "items": items,
            "comparison": _receipt_delta(latest, previous) if latest is not None else {},
            "blockers": blockers[:8],
            "unresolved": unresolved[:8],
            "resume_probes": resume_probes[:8],
            "summary": {
                "has_receipts": bool(receipts),
                "latest_status": latest_row.get("status") if latest_row else None,
                "latest_can_proceed": latest_row.get("can_proceed") if latest_row else None,
                "latest_refresh_required": latest_row.get("refresh_required") if latest_row else None,
                "latest_blocker_count": latest_row.get("blocker_count") if latest_row else 0,
                "latest_unresolved_count": latest_row.get("unresolved_count") if latest_row else 0,
                "metadata_receipt_count": receipt_counts["metadata_receipt_count"],
                "artifact_receipt_count": receipt_counts["artifact_receipt_count"],
                "lineage_is_read_only": True,
            },
            "provenance": {
                "derived_from": [
                    "runtime.job_metadata.latest_preflight_refresh_receipt",
                    "runtime.job_metadata.preflight_refresh_receipts",
                    "runtime.artifacts.preflight_refresh_receipt",
                ],
                "standard_patterns": [
                    "OpenLineage run event lineage",
                    "W3C PROV activity/entity generation",
                    "Workflow Run RO-Crate workflow outputs",
                    "Great Expectations validation result history",
                ],
                "source_material_mutation": False,
                "external_mutation": False,
            },
        }
        return dict(_json_safe_copy(lineage))

    def build_workflow_replay_index(
        self,
        *,
        session_id: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        action_id: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Build a bounded cross-job index of workflow replay receipts.

        Args:
            session_id: Optional runtime session scope.
            project_id: Optional Scholar AI project scope.
            status: Optional latest receipt status filter.
            action_id: Optional action id filter, such as ``writing.export_project``.
            limit: Maximum index rows returned, from 1 through 50.

        Returns:
            Read-only replay index that lets agents recover workflow attempts
            without knowing a specific job id first.

        Raises:
            ValueError: If filters are blank, unknown, or outside safe bounds.
        """

        normalized_session_id = str(session_id or "").strip() if session_id is not None else None
        normalized_project_id = str(project_id or "").strip() if project_id is not None else None
        normalized_status = str(status or "").strip().lower() if status is not None else None
        normalized_action_id = str(action_id or "").strip() if action_id is not None else None
        if session_id is not None and not normalized_session_id:
            raise ValueError("session_id must not be empty")
        if project_id is not None and not normalized_project_id:
            raise ValueError("project_id must not be empty")
        if status is not None and normalized_status not in {"ready", "unresolved", "blocked", "stale"}:
            raise ValueError("status must be one of ready, unresolved, blocked, stale")
        if action_id is not None and not normalized_action_id:
            raise ValueError("action_id must not be empty")
        if isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        if normalized_limit < 1 or normalized_limit > 50:
            raise ValueError("limit must be between 1 and 50")
        if normalized_session_id is not None and self.get_session(normalized_session_id) is None:
            raise ValueError(f"Session {normalized_session_id} not found")

        rows: list[dict[str, Any]] = []
        total_jobs_scanned = 0
        total_receipts_seen = 0
        filtered_out = 0
        status_counts: dict[str, int] = {}
        project_ids: set[str] = set()
        session_ids: set[str] = set()
        blockers: list[str] = []
        unresolved: list[str] = []

        for job in self._jobs.values():
            if normalized_session_id is not None and job.session_id != normalized_session_id:
                continue
            session = self.get_session(job.session_id)
            job_project_id = _project_id_for_job(job, session)
            if normalized_project_id is not None and job_project_id != normalized_project_id:
                continue
            total_jobs_scanned += 1
            receipts, receipt_counts = _collect_job_preflight_receipts(job, self.get_job_artifacts(job.job_id))
            if not receipts:
                continue
            total_receipts_seen += len(receipts)
            latest = receipts[-1]
            latest_status = _safe_projection_string(latest.get("status")) or "unresolved"
            latest_action_id = _safe_projection_string(latest.get("action_id"))
            if normalized_status is not None and latest_status != normalized_status:
                filtered_out += 1
                continue
            if normalized_action_id is not None and latest_action_id != normalized_action_id:
                filtered_out += 1
                continue
            row = _workflow_replay_index_row(
                job=job,
                session=session,
                project_id=job_project_id,
                receipts=receipts,
                receipt_counts=receipt_counts,
                ordinal=0,
            )
            rows.append(row)
            status_counts[latest_status] = status_counts.get(latest_status, 0) + 1
            session_ids.add(job.session_id)
            if job_project_id:
                project_ids.add(job_project_id)
            if row["latest_status"] == "blocked" or row["latest_blocker_count"] > 0:
                _append_unique_text(
                    blockers,
                    f"Job {job.job_id} latest replay receipt reports {row['latest_blocker_count']} blocking checks.",
                    max_items=12,
                )
            if row["latest_status"] in {"unresolved", "stale"} or row["latest_unresolved_count"] > 0:
                _append_unique_text(
                    unresolved,
                    f"Job {job.job_id} latest replay receipt reports {row['latest_unresolved_count']} unresolved checks.",
                    max_items=12,
                )
            if row["latest_refresh_required"]:
                _append_unique_text(
                    unresolved,
                    f"Job {job.job_id} still requires refreshed workflow projections before retry.",
                    max_items=12,
                )

        rows.sort(
            key=lambda row: (
                int(row.get("recovery_priority") or 0),
                str(row.get("latest_generated_at") or ""),
                str(row.get("job_id") or ""),
            ),
            reverse=True,
        )
        bounded_rows = [
            {
                **row,
                "ordinal": index + 1,
            }
            for index, row in enumerate(rows[:normalized_limit])
        ]
        resume_probes = [
            _handoff_resume_probe("List workflow replay index", "/runtime/workflow-replay-index"),
            _handoff_resume_probe("Read workflow passport", "/runtime/workflow-passport"),
            _handoff_resume_probe("Read evidence integrity gate", "/runtime/evidence-integrity-gate"),
        ]
        if normalized_session_id:
            resume_probes.append(
                _handoff_resume_probe(
                    "List session-scoped workflow replay index",
                    "/runtime/workflow-replay-index",
                    {"session_id": normalized_session_id},
                )
            )
        if normalized_project_id:
            resume_probes.append(
                _handoff_resume_probe(
                    "List project-scoped workflow replay index",
                    "/runtime/workflow-replay-index",
                    {"project_id": normalized_project_id},
                )
            )
        if bounded_rows:
            first = bounded_rows[0]
            resume_probes.append(
                _handoff_resume_probe(
                    "Read highest-priority replay lineage",
                    f"/runtime/job/{first['job_id']}/workflow-replay-lineage",
                )
            )

        index = {
            "schema_version": _WORKFLOW_REPLAY_INDEX_SCHEMA_VERSION,
            "generated_at": utc_now_iso_z(),
            "scope": {
                "session_id": normalized_session_id,
                "project_id": normalized_project_id,
                "status": normalized_status,
                "action_id": normalized_action_id,
                "limit": normalized_limit,
            },
            "total_jobs_scanned": total_jobs_scanned,
            "total_receipts_seen": total_receipts_seen,
            "matching_job_count": len(rows),
            "returned_count": len(bounded_rows),
            "items": bounded_rows,
            "blockers": blockers[:12],
            "unresolved": unresolved[:12],
            "resume_probes": resume_probes[:10],
            "summary": {
                "has_replay_evidence": bool(rows),
                "blocked_job_count": status_counts.get("blocked", 0),
                "unresolved_job_count": status_counts.get("unresolved", 0),
                "stale_job_count": status_counts.get("stale", 0),
                "ready_job_count": status_counts.get("ready", 0),
                "status_counts": status_counts,
                "project_ids": sorted(project_ids)[:24],
                "session_ids": sorted(session_ids)[:24],
                "filtered_out_count": filtered_out,
                "index_is_read_only": True,
                "requires_exact_job_id": False,
            },
            "provenance": {
                "derived_from": [
                    "runtime.jobs",
                    "runtime.job_metadata.latest_preflight_refresh_receipt",
                    "runtime.job_metadata.preflight_refresh_receipts",
                    "runtime.artifacts.preflight_refresh_receipt",
                ],
                "standard_patterns": [
                    "Temporal Visibility workflow listing and search attributes",
                    "OpenLineage run event lineage",
                    "W3C PROV activity/entity generation",
                    "Workflow Run RO-Crate workflow outputs",
                ],
                "source_material_mutation": False,
                "external_mutation": False,
            },
        }
        return dict(_json_safe_copy(index))

    def update_material_processing_task(
        self,
        job_id: str,
        *,
        request: dict[str, Any],
        status: str | None = None,
        result: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a resumable material-processing task contract.

        Args:
            job_id: Existing runtime job identifier.
            request: Versioned material-processing request object.
            status: Optional task lifecycle state; defaults to prior status or queued.
            result: Optional bounded processing result summary.
            artifacts: Optional typed artifact summaries for generated outputs.
            warnings: Optional bounded warning strings.
            provenance: Optional audit facts for the writer of this task record.

        Returns:
            JSON-safe material-processing task record stored in job metadata.

        Raises:
            ValueError: If the job is missing or the task contract has invalid shape.
        """

        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")

        prior = self.get_material_processing_task(normalized_job_id) or {}
        normalized_request = _normalize_material_processing_request(request)
        normalized_status = _normalize_material_processing_status(
            status or prior.get("status") or JobStatus.QUEUED.value
        )
        normalized_result = (
            _require_object(result, field_name="result")
            if result is not None or "result" not in prior
            else _require_object(prior.get("result"), field_name="result")
        )
        normalized_artifacts = (
            _normalize_material_processing_artifacts(artifacts)
            if artifacts is not None or "artifacts" not in prior
            else _normalize_material_processing_artifacts(prior.get("artifacts"))
        )
        normalized_warnings = (
            _normalize_material_processing_warnings(warnings)
            if warnings is not None or "warnings" not in prior
            else _normalize_material_processing_warnings(prior.get("warnings"))
        )
        normalized_provenance = {
            "derived_from": "runtime.job_metadata",
            "runtime_job_id": job.job_id,
            **_require_object(provenance or prior.get("provenance"), field_name="provenance"),
        }
        task_record: dict[str, Any] = {
            "schema_version": _MATERIAL_PROCESSING_SCHEMA_VERSION,
            "job_id": job.job_id,
            "session_id": job.session_id,
            "status": normalized_status,
            "created_at": str(prior.get("created_at") or job.created_at),
            "updated_at": utc_now_iso_z(),
            "request": normalized_request,
            "result": normalized_result,
            "cache": dict(normalized_request["cache"]),
            "artifacts": normalized_artifacts,
            "warnings": normalized_warnings,
            "provenance": normalized_provenance,
        }
        decision_record = _build_material_processing_cache_decision_record(
            job=job,
            task_record=task_record,
            artifacts=normalized_artifacts,
            warnings=normalized_warnings,
        )
        task_record["cache"]["decision_record"] = decision_record

        metadata = dict(job.metadata)
        metadata[_MATERIAL_PROCESSING_TASK_KEY] = dict(task_record)
        updated_job = replace(job, metadata=metadata)
        self._jobs[normalized_job_id] = updated_job

        self._store_artifact(
            WritingArtifact.create(
                job_id=job.job_id,
                session_id=job.session_id,
                artifact_type=ArtifactType.METADATA,
                content={
                    "kind": _MATERIAL_PROCESSING_TASK_KEY,
                    "state": dict(task_record),
                },
                created_by="writing_runtime",
                metadata={
                    "kind": _MATERIAL_PROCESSING_TASK_KEY,
                    "schema_version": _MATERIAL_PROCESSING_SCHEMA_VERSION,
                    "project_id": normalized_request["project_id"],
                    "material_id": normalized_request["material_id"],
                    "processing_mode": normalized_request["processing_mode"],
                    "cache_key": task_record["cache"].get("cache_key"),
                    "cache_decision_id": decision_record["decision_id"],
                },
                mime_type="application/json",
            )
        )
        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job.job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_PROGRESS,
                data={
                    "material_processing_task_updated": True,
                    "material_processing_status": normalized_status,
                    "material_id": normalized_request["material_id"],
                    "processing_mode": normalized_request["processing_mode"],
                    "cache_decision": task_record["cache"].get("decision"),
                    "cache_decision_id": decision_record["decision_id"],
                    "cache_replayable": decision_record["replayable"],
                    "artifact_count": len(normalized_artifacts),
                },
            ),
        )
        self._autosave_if_enabled()
        return dict(_json_safe_copy(task_record))

    def record_material_processing_task_result(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any],
        artifacts: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
        cache_decision: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a material-processing task with result/cache/artifact facts.

        Args:
            job_id: Existing runtime job identifier with a task request.
            status: Terminal or progress status for the task record.
            result: Bounded result summary; raw document text must not be stored here.
            artifacts: Optional typed artifact summaries.
            warnings: Optional bounded warning strings.
            cache_decision: Optional cache decision override for this run.
            provenance: Optional audit facts for the result writer.

        Returns:
            Updated JSON-safe material-processing task record.

        Raises:
            ValueError: If no task request exists or result fields are invalid.
        """

        task = self.get_material_processing_task(job_id)
        if task is None:
            raise ValueError(f"Material processing task not found: {job_id}")
        request = _require_object(task.get("request"), field_name="material_processing_task.request")
        if cache_decision is not None:
            cache = _require_object(request.get("cache"), field_name="cache")
            cache["decision"] = cache_decision
            request["cache"] = cache
        return self.update_material_processing_task(
            job_id,
            request=request,
            status=status,
            result=result,
            artifacts=artifacts,
            warnings=warnings,
            provenance=provenance or task.get("provenance"),
        )

    def get_material_processing_task(self, job_id: str) -> dict[str, Any] | None:
        """Return the latest material-processing task record for a runtime job.

        Args:
            job_id: Existing runtime job identifier.

        Returns:
            Detached task record, or None when the job has no material task.

        Raises:
            ValueError: If ``job_id`` is blank, unknown, or metadata is corrupt.
        """

        normalized = str(job_id or "").strip()
        if not normalized:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized)
        if job is None:
            raise ValueError(f"Job {normalized} not found")
        task = job.metadata.get(_MATERIAL_PROCESSING_TASK_KEY)
        if task is None:
            return None
        if not isinstance(task, dict):
            raise ValueError("material_processing_task metadata must be an object")
        return dict(_json_safe_copy(task))

    def build_research_projection(
        self,
        *,
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Build a read-only research object/event projection over runtime state.

        Args:
            session_id: Optional runtime session filter.
            job_id: Optional runtime job filter.
            project_id: Optional project id filter from job/session metadata.
            limit: Maximum number of projected events to return.

        Returns:
            JSON-safe projection with object, event, approval, and effect summaries.

        Raises:
            ValueError: If a filter is malformed or references missing runtime data.
        """

        normalized_session_id = _safe_projection_string(session_id)
        normalized_job_id = _safe_projection_string(job_id)
        normalized_project_id = _safe_projection_string(project_id)
        if isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        if int(limit) < 1:
            raise ValueError("limit must be greater than zero")
        event_limit = min(int(limit), 1000)

        if normalized_session_id and self.get_session(normalized_session_id) is None:
            raise ValueError(f"Session {normalized_session_id} not found")
        if normalized_job_id and self.get_job(normalized_job_id) is None:
            raise ValueError(f"Job {normalized_job_id} not found")

        jobs = list(self._jobs.values())
        if normalized_job_id:
            selected_job = self.get_job(normalized_job_id)
            if selected_job is None:
                raise ValueError(f"Job {normalized_job_id} not found")
            jobs = [selected_job]
        if normalized_session_id:
            jobs = [job for job in jobs if job.session_id == normalized_session_id]
        if normalized_project_id:
            jobs = [
                job
                for job in jobs
                if _project_id_for_job(job, self.get_session(job.session_id)) == normalized_project_id
            ]

        selected_job_ids = {job.job_id for job in jobs}
        objects_by_id: dict[str, dict[str, Any]] = {}
        job_object_index: dict[str, tuple[str, str]] = {}
        approval_boundaries: list[dict[str, Any]] = []

        def _upsert_object(candidate: dict[str, Any]) -> None:
            object_id = _safe_projection_string(candidate.get("object_id"))
            object_type = _safe_projection_string(candidate.get("object_type"))
            status = _safe_projection_string(candidate.get("status"))
            if object_id is None or object_type is None or status is None:
                raise ValueError("research object projection requires id, type, and status")
            candidate["object_id"] = object_id
            candidate["object_type"] = object_type
            candidate["status"] = status
            existing = objects_by_id.get(object_id)
            if existing is None:
                objects_by_id[object_id] = {
                    "object_id": object_id,
                    "object_type": object_type,
                    "status": status,
                    "project_id": candidate.get("project_id"),
                    "material_id": candidate.get("material_id"),
                    "title": candidate.get("title"),
                    "created_at": candidate.get("created_at"),
                    "updated_at": candidate.get("updated_at"),
                    "source_refs": list(candidate.get("source_refs") or []),
                    "provenance": dict(candidate.get("provenance") or {}),
                    "state": dict(candidate.get("state") or {}),
                    "confirmation_boundary": dict(candidate.get("confirmation_boundary") or {}),
                    "effects": dict(candidate.get("effects") or {}),
                }
                return

            existing["status"] = status if status != "referenced" else existing.get("status", status)
            if candidate.get("project_id") and not existing.get("project_id"):
                existing["project_id"] = candidate["project_id"]
            if candidate.get("material_id") and not existing.get("material_id"):
                existing["material_id"] = candidate["material_id"]
            if candidate.get("title") and not existing.get("title"):
                existing["title"] = candidate["title"]
            if candidate.get("created_at") and (
                not existing.get("created_at") or str(candidate["created_at"]) < str(existing["created_at"])
            ):
                existing["created_at"] = candidate["created_at"]
            if candidate.get("updated_at") and (
                not existing.get("updated_at") or str(candidate["updated_at"]) > str(existing["updated_at"])
            ):
                existing["updated_at"] = candidate["updated_at"]
            refs = list(existing.get("source_refs") or [])
            for ref in candidate.get("source_refs") or []:
                if ref not in refs:
                    refs.append(ref)
            existing["source_refs"] = refs
            existing["provenance"] = {**dict(existing.get("provenance") or {}), **dict(candidate.get("provenance") or {})}
            existing["state"] = {**dict(existing.get("state") or {}), **dict(candidate.get("state") or {})}
            existing["confirmation_boundary"] = {
                **dict(existing.get("confirmation_boundary") or {}),
                **dict(candidate.get("confirmation_boundary") or {}),
            }
            existing["effects"] = {**dict(existing.get("effects") or {}), **dict(candidate.get("effects") or {})}

        for job in jobs:
            session = self.get_session(job.session_id)
            metadata = dict(job.metadata)
            project_id_for_job = _project_id_for_job(job, session)
            material_id = _metadata_string(metadata, ("material_id", "source_material_id"))
            object_type = _research_object_type_for_job(job)
            raw_object_id = _raw_research_object_id(object_type, metadata, job.job_id)
            object_id = _research_object_id(object_type, raw_object_id)
            artifacts = list(self._artifacts.get(job.job_id, []))
            approvals = [
                approval
                for approval in self._approval_requests.values()
                if approval.job_id == job.job_id
            ]
            pending_approvals = [
                approval
                for approval in approvals
                if approval.status == ApprovalStatus.PENDING
            ]
            events = [
                event
                for event in self._events.get(job.session_id, [])
                if event.job_id == job.job_id
            ]
            job_object_index[job.job_id] = (object_id, object_type)
            _upsert_object(
                {
                    "object_id": object_id,
                    "object_type": object_type,
                    "status": job.status.value,
                    "project_id": project_id_for_job,
                    "material_id": material_id,
                    "title": _metadata_string(metadata, ("title", "name", "filename", "source_label")),
                    "created_at": job.created_at,
                    "updated_at": job.completed_at or job.started_at or job.created_at,
                    "source_refs": _source_refs_from_metadata(metadata, job_id=job.job_id),
                    "provenance": {
                        "derived_from": ["runtime.jobs"],
                        "runtime_job_id": job.job_id,
                        "runtime_session_id": job.session_id,
                        "runtime_job_kind": job.kind.value,
                    },
                    "state": {
                        "job_kind": job.kind.value,
                        "tags": list(job.tags),
                        **({"scope": job.scope} if job.scope else {}),
                        **({"output_mode": job.output_mode} if job.output_mode else {}),
                        **_compact_projection_mapping(metadata, allowed_keys=_RESEARCH_STATE_KEYS),
                    },
                    "confirmation_boundary": {
                        "requires_user_confirmation": bool(pending_approvals),
                        "approval_count": len(approvals),
                        "pending_approval_count": len(pending_approvals),
                    },
                    "effects": {
                        "runtime_event_count": len(events),
                        "artifact_count": len(artifacts),
                        "approval_count": len(approvals),
                    },
                }
            )
            if project_id_for_job:
                _upsert_object(
                    {
                        "object_id": _research_object_id(_RESEARCH_PROJECT_OBJECT_TYPE, project_id_for_job),
                        "object_type": _RESEARCH_PROJECT_OBJECT_TYPE,
                        "status": "active",
                        "project_id": project_id_for_job,
                        "title": _metadata_string(dict(session.metadata), ("title", "project_title")) if session else None,
                        "created_at": session.created_at if session else job.created_at,
                        "updated_at": job.completed_at or job.started_at or job.created_at,
                        "source_refs": [{"ref_type": "runtime_session", "ref_id": job.session_id}],
                        "provenance": {"derived_from": ["runtime.sessions", "runtime.jobs"]},
                        "state": {"session_id": job.session_id},
                        "confirmation_boundary": {"requires_user_confirmation": False},
                        "effects": {"linked_job_count": 1},
                    }
                )
            if material_id:
                _upsert_object(
                    {
                        "object_id": _research_object_id("research_material", material_id),
                        "object_type": "research_material",
                        "status": job.status.value if object_type == "research_material" else "referenced",
                        "project_id": project_id_for_job,
                        "material_id": material_id,
                        "title": _metadata_string(metadata, ("title", "filename", "source_label")),
                        "created_at": job.created_at,
                        "updated_at": job.completed_at or job.started_at or job.created_at,
                        "source_refs": _source_refs_from_metadata(metadata, job_id=job.job_id),
                        "provenance": {"derived_from": ["runtime.job_metadata"]},
                        "state": {"linked_runtime_job_id": job.job_id},
                        "confirmation_boundary": {"requires_user_confirmation": False},
                        "effects": {"linked_job_count": 1},
                    }
                )
            evidence_pack_id = _metadata_string(metadata, ("evidence_pack_id", "evidence_pack_ref", "pack_id"))
            if evidence_pack_id:
                _upsert_object(
                    {
                        "object_id": _research_object_id("evidence_pack", evidence_pack_id),
                        "object_type": "evidence_pack",
                        "status": job.status.value if object_type == "evidence_pack" else "referenced",
                        "project_id": project_id_for_job,
                        "material_id": material_id,
                        "created_at": job.created_at,
                        "updated_at": job.completed_at or job.started_at or job.created_at,
                        "source_refs": _source_refs_from_metadata(metadata, job_id=job.job_id),
                        "provenance": {"derived_from": ["runtime.job_metadata"]},
                        "state": {"linked_runtime_job_id": job.job_id},
                        "confirmation_boundary": {"requires_user_confirmation": False},
                        "effects": {"linked_job_count": 1},
                    }
                )
            agent_request_id = _metadata_string(metadata, ("agent_request_id", "request_id", "runtime_request_id"))
            if agent_request_id:
                _upsert_object(
                    {
                        "object_id": _research_object_id("agent_request", agent_request_id),
                        "object_type": "agent_request",
                        "status": job.status.value if object_type == "agent_request" else "referenced",
                        "project_id": project_id_for_job,
                        "material_id": material_id,
                        "created_at": job.created_at,
                        "updated_at": job.completed_at or job.started_at or job.created_at,
                        "source_refs": [{"ref_type": "runtime_job", "ref_id": job.job_id}],
                        "provenance": {"derived_from": ["runtime.job_metadata"]},
                        "state": {"linked_runtime_job_id": job.job_id},
                        "confirmation_boundary": {
                            "requires_user_confirmation": bool(pending_approvals),
                            "approval_count": len(approvals),
                            "pending_approval_count": len(pending_approvals),
                        },
                        "effects": {"linked_job_count": 1},
                    }
                )
            for artifact in artifacts:
                artifact_metadata = dict(artifact.metadata)
                content_kind = None
                if isinstance(artifact.content, dict):
                    content_kind = _safe_projection_string(artifact.content.get("kind"))
                artifact_object_type = "runtime_artifact"
                artifact_raw_id = artifact.artifact_id
                artifact_evidence_pack_id = _metadata_string(artifact_metadata, ("evidence_pack_id", "pack_id"))
                if artifact_evidence_pack_id or content_kind == "evidence_pack":
                    artifact_object_type = "evidence_pack"
                    artifact_raw_id = artifact_evidence_pack_id or artifact.artifact_id
                _upsert_object(
                    {
                        "object_id": _research_object_id(artifact_object_type, artifact_raw_id),
                        "object_type": artifact_object_type,
                        "status": "created",
                        "project_id": project_id_for_job,
                        "material_id": material_id,
                        "created_at": artifact.created_at,
                        "updated_at": artifact.created_at,
                        "source_refs": [{"ref_type": "runtime_job", "ref_id": job.job_id}],
                        "provenance": {
                            "derived_from": ["runtime.artifacts"],
                            "runtime_artifact_id": artifact.artifact_id,
                            "runtime_job_id": job.job_id,
                        },
                        "state": {
                            "artifact_type": artifact.artifact_type.value,
                            "mime_type": artifact.mime_type,
                            "created_by": artifact.created_by,
                            **_compact_projection_mapping(artifact_metadata, allowed_keys=_RESEARCH_STATE_KEYS),
                        },
                        "confirmation_boundary": {"requires_user_confirmation": False},
                        "effects": {
                            "content_shape": "object" if isinstance(artifact.content, dict) else "text",
                        },
                    }
                )

        for approval in self._approval_requests.values():
            if approval.job_id not in selected_job_ids:
                continue
            target_job = self.get_job(approval.job_id)
            if target_job is None:
                continue
            session = self.get_session(target_job.session_id)
            metadata = dict(target_job.metadata)
            project_id_for_job = _project_id_for_job(target_job, session)
            material_id = _metadata_string(metadata, ("material_id", "source_material_id"))
            target_object_id, target_object_type = job_object_index.get(
                approval.job_id,
                (_research_object_id("writing_job", approval.job_id), "writing_job"),
            )
            approval_object_id = _research_object_id("approval_gate", approval.approval_id)
            boundary = {
                "approval_id": approval.approval_id,
                "object_id": approval_object_id,
                "target_object_id": target_object_id,
                "target_object_type": target_object_type,
                "job_id": approval.job_id,
                "session_id": approval.session_id,
                "status": approval.status.value,
                "reason": approval.reason,
                "requested_at": approval.requested_at,
                "responded_at": approval.responded_at,
                "response_by": approval.response_by,
                "metadata": _compact_projection_mapping(dict(approval.metadata)),
            }
            approval_boundaries.append(boundary)
            _upsert_object(
                {
                    "object_id": approval_object_id,
                    "object_type": "approval_gate",
                    "status": approval.status.value,
                    "project_id": project_id_for_job,
                    "material_id": material_id,
                    "created_at": approval.requested_at,
                    "updated_at": approval.responded_at or approval.requested_at,
                    "source_refs": [{"ref_type": "runtime_job", "ref_id": approval.job_id}],
                    "provenance": {
                        "derived_from": ["runtime.approval_requests"],
                        "runtime_approval_id": approval.approval_id,
                    },
                    "state": {
                        "reason": approval.reason,
                        "target_object_id": target_object_id,
                        **_compact_projection_mapping(dict(approval.metadata)),
                    },
                    "confirmation_boundary": {
                        "requires_user_confirmation": approval.status == ApprovalStatus.PENDING,
                        "approval_id": approval.approval_id,
                        "target_object_id": target_object_id,
                    },
                    "effects": {
                        "responded": approval.responded_at is not None,
                    },
                }
            )

        projected_events: list[dict[str, Any]] = []
        for job in jobs:
            object_id, object_type = job_object_index.get(
                job.job_id,
                (_research_object_id("writing_job", job.job_id), "writing_job"),
            )
            for event in self._events.get(job.session_id, []):
                if event.job_id != job.job_id:
                    continue
                event_data = _compact_projection_mapping(dict(event.data))
                approval_id = _safe_projection_string(event.data.get("approval_id"))
                projected_events.append(
                    {
                        "event_id": event.event_id,
                        "event_type": _research_event_type_for_job_event(job, event),
                        "source": _RESEARCH_EVENT_SOURCE,
                        "subject": object_id,
                        "object_id": object_id,
                        "object_type": object_type,
                        "session_id": event.session_id,
                        "job_id": event.job_id,
                        "timestamp": event.timestamp,
                        "sequence": event.sequence,
                        "status": job.status.value,
                        "actor": _safe_projection_string(event.metadata.get("actor")),
                        "data": event_data,
                        "provenance": {
                            "derived_from": "runtime.events",
                            "runtime_event_id": event.event_id,
                            "runtime_event_type": event.event_type.value,
                        },
                        "confirmation_boundary": {
                            "requires_user_confirmation": event.event_type == EventType.APPROVAL_REQUIRED,
                            **({"approval_id": approval_id} if approval_id else {}),
                        },
                    }
                )
            for artifact in self._artifacts.get(job.job_id, []):
                artifact_metadata = dict(artifact.metadata)
                artifact_object_type = "runtime_artifact"
                artifact_raw_id = artifact.artifact_id
                artifact_evidence_pack_id = _metadata_string(artifact_metadata, ("evidence_pack_id", "pack_id"))
                if artifact_evidence_pack_id:
                    artifact_object_type = "evidence_pack"
                    artifact_raw_id = artifact_evidence_pack_id
                projected_events.append(
                    {
                        "event_id": f"artifact_{artifact.artifact_id}_created",
                        "event_type": "evidence.pack.created" if artifact_object_type == "evidence_pack" else "artifact.created",
                        "source": _RESEARCH_EVENT_SOURCE,
                        "subject": _research_object_id(artifact_object_type, artifact_raw_id),
                        "object_id": _research_object_id(artifact_object_type, artifact_raw_id),
                        "object_type": artifact_object_type,
                        "session_id": artifact.session_id,
                        "job_id": artifact.job_id,
                        "timestamp": artifact.created_at,
                        "sequence": 0,
                        "status": "created",
                        "actor": artifact.created_by,
                        "data": {
                            "artifact_type": artifact.artifact_type.value,
                            "mime_type": artifact.mime_type,
                        },
                        "provenance": {
                            "derived_from": "runtime.artifacts",
                            "runtime_artifact_id": artifact.artifact_id,
                        },
                        "confirmation_boundary": {"requires_user_confirmation": False},
                    }
                )
        for boundary in approval_boundaries:
            status = str(boundary["status"])
            event_type = "approval.required" if status == ApprovalStatus.PENDING.value else f"approval.{status}"
            projected_events.append(
                {
                    "event_id": f"approval_{boundary['approval_id']}_{status}",
                    "event_type": event_type,
                    "source": _RESEARCH_EVENT_SOURCE,
                    "subject": str(boundary["object_id"]),
                    "object_id": str(boundary["object_id"]),
                    "object_type": "approval_gate",
                    "session_id": str(boundary["session_id"]),
                    "job_id": str(boundary["job_id"]),
                    "timestamp": str(boundary["responded_at"] or boundary["requested_at"]),
                    "sequence": 0,
                    "status": status,
                    "actor": _safe_projection_string(boundary.get("response_by")),
                    "data": {
                        "approval_id": boundary["approval_id"],
                        "target_object_id": boundary["target_object_id"],
                        "target_object_type": boundary["target_object_type"],
                    },
                    "provenance": {
                        "derived_from": "runtime.approval_requests",
                        "runtime_approval_id": boundary["approval_id"],
                    },
                    "confirmation_boundary": {
                        "requires_user_confirmation": status == ApprovalStatus.PENDING.value,
                        "approval_id": boundary["approval_id"],
                        "target_object_id": boundary["target_object_id"],
                    },
                }
            )

        projected_events.sort(key=lambda item: (str(item.get("timestamp") or ""), int(item.get("sequence") or 0), str(item.get("event_id") or "")))
        projected_events = projected_events[:event_limit]
        objects = sorted(objects_by_id.values(), key=lambda item: (str(item["object_type"]), str(item["object_id"])))

        object_type_counts: dict[str, int] = {}
        event_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for item in objects:
            _increment_projection_count(object_type_counts, str(item.get("object_type") or "unknown"))
            _increment_projection_count(status_counts, str(item.get("status") or "unknown"))
        for item in projected_events:
            _increment_projection_count(event_type_counts, str(item.get("event_type") or "unknown"))

        return {
            "schema_version": _RESEARCH_PROJECTION_SCHEMA_VERSION,
            "generated_at": utc_now_iso_z(),
            "scope": {
                "session_id": normalized_session_id,
                "job_id": normalized_job_id,
                "project_id": normalized_project_id,
                "event_limit": event_limit,
            },
            "objects": objects,
            "events": projected_events,
            "approval_boundaries": approval_boundaries,
            "status_projection": {
                "object_count": len(objects),
                "event_count": len(projected_events),
                "object_type_counts": object_type_counts,
                "event_type_counts": event_type_counts,
                "status_counts": status_counts,
                "pending_approval_count": sum(
                    1
                    for boundary in approval_boundaries
                    if boundary.get("status") == ApprovalStatus.PENDING.value
                ),
                "requires_user_confirmation": any(
                    boundary.get("status") == ApprovalStatus.PENDING.value
                    for boundary in approval_boundaries
                ),
                "effect_counts": {
                    "jobs": len(jobs),
                    "artifacts": sum(len(self._artifacts.get(job.job_id, [])) for job in jobs),
                    "approvals": len(approval_boundaries),
                },
            },
        }

    def build_workflow_passport(
        self,
        *,
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Build a read-only stage passport over runtime workflow evidence.

        Args:
            session_id: Optional runtime session filter.
            job_id: Optional runtime job filter.
            project_id: Optional project id filter from job/session metadata.
            limit: Maximum number of projected events to inspect.

        Returns:
            JSON-safe passport with ordered stages, gates, and provenance.

        Raises:
            ValueError: If the projection filters are invalid.
        """

        projection = self.build_research_projection(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )
        stage_rows: dict[str, dict[str, Any]] = {}
        for stage in _WORKFLOW_STAGE_DEFINITIONS:
            stage_id = str(stage["stage_id"])
            stage_rows[stage_id] = {
                "stage_id": stage_id,
                "label": stage["label"],
                "status": "not_started",
                "required_artifacts": list(stage["required_artifacts"]),
                "present_artifacts": [],
                "object_ids": [],
                "event_types": [],
                "blockers": [],
                "unresolved": [],
                "requires_user_confirmation": False,
                "diagnostics": _new_passport_diagnostics(),
                "reproducibility": _new_passport_reproducibility(),
                "next_actions": [str(stage["next_action"])],
                "updated_at": None,
            }

        objects = projection.get("objects")
        if not isinstance(objects, list):
            raise ValueError("research projection objects must be a list")
        events = projection.get("events")
        if not isinstance(events, list):
            raise ValueError("research projection events must be a list")

        for item in objects:
            if not isinstance(item, dict):
                continue
            object_type = _safe_projection_string(item.get("object_type"))
            object_id = _safe_projection_string(item.get("object_id"))
            if object_type is None or object_id is None:
                continue
            state = item.get("state") if isinstance(item.get("state"), dict) else {}
            effects = item.get("effects") if isinstance(item.get("effects"), dict) else {}
            boundary = item.get("confirmation_boundary") if isinstance(item.get("confirmation_boundary"), dict) else {}
            for stage in _WORKFLOW_STAGE_DEFINITIONS:
                object_types = stage.get("object_types")
                if not isinstance(object_types, set):
                    continue
                if object_type not in object_types and not _stage_matches_workflow_state(stage, state):
                    continue
                row = stage_rows[str(stage["stage_id"])]
                _append_unique_text(row["object_ids"], object_id)
                row["status"] = _strongest_passport_status(
                    str(row["status"]),
                    _passport_status_from_runtime_status(item.get("status")),
                )
                if item.get("updated_at") and (
                    not row.get("updated_at") or str(item["updated_at"]) > str(row["updated_at"])
                ):
                    row["updated_at"] = item["updated_at"]
                diagnostics = row.get("diagnostics")
                if isinstance(diagnostics, dict):
                    diagnostics["object_count"] = int(diagnostics.get("object_count") or 0) + 1
                    _increment_nested_count(diagnostics, "status_counts", item.get("status"))
                if boundary.get("requires_user_confirmation"):
                    row["requires_user_confirmation"] = True
                    _append_unique_text(row["blockers"], "Pending user confirmation is required.")
                if object_type == "runtime_artifact" or effects.get("content_shape"):
                    diagnostics = row.get("diagnostics")
                    if isinstance(diagnostics, dict):
                        diagnostics["artifact_count"] = int(diagnostics.get("artifact_count") or 0) + 1
                    _append_unique_mapping(
                        row["present_artifacts"],
                        {
                            "ref_type": "research_object",
                            "ref_id": object_id,
                            "object_type": object_type,
                            **_compact_projection_mapping(state, allowed_keys=("artifact_type", "mime_type", "created_by")),
                        },
                    )
                workflow_state = state if _stage_matches_workflow_state(stage, state) else {}
                if workflow_state:
                    phase = _safe_projection_string(workflow_state.get("phase"))
                    _append_unique_mapping(
                        row["present_artifacts"],
                        {
                            "artifact_type": "writing_workflow_state",
                            "phase": phase,
                            "ref_type": "research_object",
                            "ref_id": object_id,
                        },
                    )

        selected_job_ids = {
            str(job.job_id)
            for job in self._jobs.values()
            if _safe_projection_string(job_id) in (None, str(job.job_id))
            and (not _safe_projection_string(session_id) or job.session_id == _safe_projection_string(session_id))
            and (
                not _safe_projection_string(project_id)
                or _project_id_for_job(job, self.get_session(job.session_id)) == _safe_projection_string(project_id)
            )
        }
        for selected_job_id in selected_job_ids:
            job = self.get_job(selected_job_id)
            if job is None:
                continue
            task = job.metadata.get(_MATERIAL_PROCESSING_TASK_KEY)
            if isinstance(task, dict):
                ingest_row = stage_rows["material_ingest"]
                ingest_row["status"] = _strongest_passport_status(
                    str(ingest_row["status"]),
                    _passport_status_from_runtime_status(task.get("status")),
                )
                _record_passport_material_task(ingest_row, selected_job_id, task)
                task_request = task.get("request") if isinstance(task.get("request"), dict) else {}
                material_id = _safe_projection_string(task_request.get("material_id"))
                if material_id is not None:
                    _append_unique_text(ingest_row["object_ids"], _research_object_id("research_material", material_id))
                else:
                    _append_unique_text(ingest_row["unresolved"], "Material processing task is missing material_id.")
                _append_unique_mapping(
                    ingest_row["present_artifacts"],
                    {
                        "artifact_type": _MATERIAL_PROCESSING_TASK_KEY,
                        "status": task.get("status"),
                        "processing_mode": task_request.get("processing_mode"),
                        "cache_decision": task.get("cache", {}).get("decision"),
                        "ref_type": "runtime_job",
                        "ref_id": selected_job_id,
                    },
                )
                for artifact_ref in _material_processing_artifact_refs(task):
                    _append_unique_mapping(ingest_row["present_artifacts"], artifact_ref)
                if task.get("status") in {"failed", "cancelled"}:
                    _append_unique_text(ingest_row["blockers"], "Material processing did not complete.")
                elif task.get("status") != "completed":
                    _append_unique_text(ingest_row["unresolved"], "Material processing is not completed yet.")
                read_artifact_count = _material_processing_target_count(
                    task,
                    {"chunks", "locators", "chunk_index", "locator_index", "evidence_refs"},
                )
                if read_artifact_count > 0:
                    read_row = stage_rows["material_read"]
                    read_row["status"] = _strongest_passport_status(
                        str(read_row["status"]),
                        "complete" if task.get("status") == "completed" else "in_progress",
                    )
                    _record_passport_material_task(read_row, selected_job_id, task)
                    if material_id is not None:
                        _append_unique_text(read_row["object_ids"], _research_object_id("research_material", material_id))
                    for artifact_ref in _material_processing_artifact_refs(task):
                        if artifact_ref.get("output_target") in {"chunks", "locators", "evidence_refs"} or artifact_ref.get(
                            "artifact_type"
                        ) in {"chunk_index", "locator_index"}:
                            _append_unique_mapping(read_row["present_artifacts"], artifact_ref)
                    if task.get("status") != "completed":
                        _append_unique_text(read_row["unresolved"], "Material read locators exist but processing is not completed yet.")
            workflow_state = job.metadata.get(_WRITING_WORKFLOW_STATE_KEY)
            if isinstance(workflow_state, dict):
                for stage in _WORKFLOW_STAGE_DEFINITIONS:
                    if not _stage_matches_workflow_state(stage, workflow_state):
                        continue
                    row = stage_rows[str(stage["stage_id"])]
                    _append_unique_text(row["object_ids"], _research_object_id("writing_job", job.job_id))
                    row["status"] = _strongest_passport_status(str(row["status"]), "complete")
                    if workflow_state.get("updated_at") and (
                        not row.get("updated_at") or str(workflow_state["updated_at"]) > str(row["updated_at"])
                    ):
                        row["updated_at"] = workflow_state["updated_at"]
                    _append_unique_mapping(
                        row["present_artifacts"],
                        {
                            "artifact_type": _WRITING_WORKFLOW_STATE_KEY,
                            "phase": workflow_state.get("phase"),
                            "ref_type": "runtime_job",
                            "ref_id": job.job_id,
                        },
                    )
                    _record_passport_workflow_state(row, job.job_id, workflow_state)
                    readiness = workflow_state.get("readiness")
                    if isinstance(readiness, dict):
                        missing = [
                            key
                            for key, value in readiness.items()
                            if key.startswith("has_") and not bool(value)
                        ][:8]
                        for key in missing:
                            _append_unique_text(row["unresolved"], f"Workflow readiness is missing {key}.")

        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = _safe_projection_string(event.get("event_type"))
            if event_type is None:
                continue
            for stage in _WORKFLOW_STAGE_DEFINITIONS:
                if not _stage_matches_event(stage, event_type):
                    continue
                row = stage_rows[str(stage["stage_id"])]
                _record_passport_stage_event(row, event_type)
                _append_unique_text(row["event_types"], event_type)
                _append_unique_text(row["object_ids"], event.get("object_id"))
                if event.get("timestamp") and (
                    not row.get("updated_at") or str(event["timestamp"]) > str(row["updated_at"])
                ):
                    row["updated_at"] = event["timestamp"]
                status = _safe_projection_string(event.get("status"))
                row["status"] = _strongest_passport_status(
                    str(row["status"]),
                    _passport_status_from_event(event_type, status),
                )
                boundary = event.get("confirmation_boundary") if isinstance(event.get("confirmation_boundary"), dict) else {}
                if boundary.get("requires_user_confirmation"):
                    row["requires_user_confirmation"] = True
                    _append_unique_text(row["blockers"], "Pending user confirmation is required.")

        selected_jobs = [
            job
            for job in self._jobs.values()
            if job.job_id in selected_job_ids
        ]
        payload_rows = _iter_runtime_metadata_dicts(selected_jobs) + _iter_artifact_dicts(selected_jobs, self._artifacts)
        for source_id, payload in payload_rows:
            _record_passport_integrity_payload(stage_rows["material_read"], source_id, payload)
            _record_passport_integrity_payload(stage_rows["evidence_pack"], source_id, payload)
        for selected_job in selected_jobs:
            kind_value = str(getattr(selected_job.kind, "value", selected_job.kind))
            if kind_value == JobKind.ARTIFACT_EXPORT.value:
                _record_passport_preflight_receipts(stage_rows["export"], selected_job, self._artifacts)
            if kind_value == JobKind.AGENT_REQUEST.value or bool(selected_job.metadata.get("agent_bridge")):
                _record_passport_preflight_receipts(stage_rows["agent_handoff"], selected_job, self._artifacts)

        stages: list[dict[str, Any]] = []
        gate_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        for stage in _WORKFLOW_STAGE_DEFINITIONS:
            row = stage_rows[str(stage["stage_id"])]
            if row["status"] == "not_started" and (row["object_ids"] or row["event_types"] or row["present_artifacts"]):
                row["status"] = "unresolved"
            gate = _passport_gate_for_stage(stage, row)
            row["gate"] = gate
            for private_key in ("blockers", "unresolved", "requires_user_confirmation"):
                row.pop(private_key, None)
            _trim_passport_stage_projection(row)
            stages.append(row)
            _increment_projection_count(gate_counts, gate["status"])
            _increment_projection_count(severity_counts, gate["severity"])

        current_stage_id = None
        for row in stages:
            if row["status"] != "complete":
                current_stage_id = str(row["stage_id"])
                break
        if current_stage_id is None and stages:
            current_stage_id = str(stages[-1]["stage_id"])
        return {
            "schema_version": _WORKFLOW_PASSPORT_SCHEMA_VERSION,
            "generated_at": utc_now_iso_z(),
            "scope": dict(projection.get("scope") or {}),
            "stages": stages,
            "current_stage_id": current_stage_id,
            "gate_summary": {
                "stage_count": len(stages),
                "gate_counts": gate_counts,
                "severity_counts": severity_counts,
                "blocking_stage_ids": [
                    row["stage_id"]
                    for row in stages
                    if row.get("gate", {}).get("status") == "block"
                ],
                "unresolved_stage_ids": [
                    row["stage_id"]
                    for row in stages
                    if row.get("gate", {}).get("status") == "unresolved"
                ],
                "requires_user_confirmation": any(
                    row.get("gate", {}).get("requires_user_confirmation")
                    for row in stages
                ),
            },
            "provenance": {
                "derived_from": [
                    "runtime.research_projection",
                    "runtime.jobs",
                    "runtime.events",
                    "runtime.artifacts",
                    "runtime.approval_requests",
                    "runtime.material_processing_task",
                    "runtime.writing_workflow_state",
                ],
                "research_projection_schema_version": projection.get("schema_version"),
                "object_count": len(objects),
                "event_count": len(events),
            },
        }

    def build_evidence_integrity_gate(
        self,
        *,
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Build a read-only integrity gate over runtime evidence signals.

        Args:
            session_id: Optional runtime session filter.
            job_id: Optional runtime job filter.
            project_id: Optional project id filter from job/session metadata.
            limit: Maximum number of projected events to inspect.

        Returns:
            JSON-safe gate payload with pass/warn/block/unresolved signals.

        Raises:
            ValueError: If the projection filters are invalid.
        """

        normalized_session_id = _safe_projection_string(session_id)
        normalized_job_id = _safe_projection_string(job_id)
        normalized_project_id = _safe_projection_string(project_id)
        passport = self.build_workflow_passport(
            session_id=normalized_session_id,
            job_id=normalized_job_id,
            project_id=normalized_project_id,
            limit=limit,
        )
        jobs = list(self._jobs.values())
        if normalized_job_id:
            selected_job = self.get_job(normalized_job_id)
            if selected_job is None:
                raise ValueError(f"Job {normalized_job_id} not found")
            jobs = [selected_job]
        if normalized_session_id:
            jobs = [job for job in jobs if job.session_id == normalized_session_id]
        if normalized_project_id:
            jobs = [
                job
                for job in jobs
                if _project_id_for_job(job, self.get_session(job.session_id)) == normalized_project_id
            ]

        signals: list[dict[str, Any]] = []
        for stage in passport.get("stages", []):
            if not isinstance(stage, dict):
                continue
            gate = stage.get("gate") if isinstance(stage.get("gate"), dict) else {}
            gate_status = str(gate.get("status") or "unresolved")
            if gate_status not in {"block", "unresolved", "warn"}:
                continue
            stage_id = str(stage.get("stage_id") or "unknown")
            signals.append(
                _integrity_signal(
                    signal_id=f"workflow_stage:{stage_id}",
                    category="workflow_stage",
                    status=gate_status,
                    severity=str(gate.get("severity") or "note"),
                    message=f"Workflow stage {stage_id}: {gate.get('reason') or 'stage requires review.'}",
                    evidence=list(gate.get("evidence") or [])[:12],
                    next_actions=list(stage.get("next_actions") or [])[:4],
                    metadata={
                        "stage_id": stage_id,
                        "stage_status": stage.get("status"),
                        "required_artifacts": list(stage.get("required_artifacts") or []),
                    },
                    drilldown=_workflow_stage_drilldown(stage, gate),
                )
            )

        artifact_rows = _iter_artifact_dicts(jobs, self._artifacts)
        payload_rows = _iter_runtime_metadata_dicts(jobs) + artifact_rows
        locator_signal_count = 0
        qrels_signal_count = 0
        citation_signal_count = 0
        for source_id, payload in payload_rows:
            for locator_source_id, locator_payload in _extract_locator_payloads(source_id, payload):
                signals.append(_locator_integrity_signal(locator_source_id, locator_payload))
                locator_signal_count += 1
            for qrels_source_id, qrels_payload in _extract_qrels_payloads(source_id, payload):
                signals.append(_qrels_integrity_signal(qrels_source_id, qrels_payload))
                qrels_signal_count += 1
            for verification_source_id, verification_payload in _extract_citation_verification_payloads(source_id, payload):
                signals.append(_citation_verification_integrity_signal(verification_source_id, verification_payload))
                citation_signal_count += 1
            for overlap_source_id, overlap_payload in _extract_citation_overlap_payloads(source_id, payload):
                signals.append(_citation_overlap_integrity_signal(overlap_source_id, overlap_payload))
            for lint_source_id, lint_payload in _extract_lint_payloads(source_id, payload):
                signals.append(_lint_integrity_signal(lint_source_id, lint_payload))
            for export_source_id, export_payload in _extract_export_payloads(source_id, payload):
                signals.append(_export_integrity_signal(export_source_id, export_payload))
            for behavior_source_id, behavior_payload in _extract_behavior_eval_payloads(source_id, payload):
                signals.append(_behavior_eval_integrity_signal(behavior_source_id, behavior_payload))

        for job in jobs:
            workflow_state = job.metadata.get(_WRITING_WORKFLOW_STATE_KEY)
            if not isinstance(workflow_state, dict):
                continue
            evidence_refs = workflow_state.get("evidence_refs")
            if isinstance(evidence_refs, list) and evidence_refs and locator_signal_count == 0:
                signals.append(
                    _integrity_signal(
                        signal_id=f"locator:missing_coverage:{job.job_id}",
                        category="locator",
                        status="unresolved",
                        severity="warn",
                        message="Evidence refs exist, but locator coverage diagnostics are missing.",
                        evidence=_bounded_signal_evidence(
                            "runtime_job",
                            job.job_id,
                            evidence_ref_count=len(evidence_refs),
                        ),
                        next_actions=[
                            "Rebuild evidence pack or search refs so locator_coverage is recorded."
                        ],
                        metadata={"evidence_ref_count": len(evidence_refs)},
                        drilldown=_integrity_payload_drilldown(
                            source_id=job.job_id,
                            source_kind="workflow_state_missing_locator_coverage",
                            status="unresolved",
                            checked_facts={
                                "runtime_job_id": job.job_id,
                                "evidence_ref_count": len(evidence_refs),
                                "locator_signal_count": locator_signal_count,
                            },
                            evidence_refs=_bounded_signal_evidence(
                                "runtime_job",
                                job.job_id,
                                evidence_ref_count=len(evidence_refs),
                            ),
                        ),
                    )
                )
            citation_bank = workflow_state.get("citation_bank")
            if isinstance(citation_bank, list) and citation_bank and citation_signal_count == 0:
                signals.append(
                    _integrity_signal(
                        signal_id=f"citation_verification:missing_records:{job.job_id}",
                        category="citation_verification",
                        status="unresolved",
                        severity="warn",
                        message="Citation bank exists, but citation verification records are missing.",
                        evidence=_bounded_signal_evidence(
                            "runtime_job",
                            job.job_id,
                            citation_count=len(citation_bank),
                        ),
                        next_actions=[
                            "Run citation source verification before marking citations as verified."
                        ],
                        metadata={"citation_count": len(citation_bank)},
                        drilldown=_integrity_payload_drilldown(
                            source_id=job.job_id,
                            source_kind="workflow_state_missing_citation_verifications",
                            status="unresolved",
                            checked_facts={
                                "runtime_job_id": job.job_id,
                                "citation_count": len(citation_bank),
                                "citation_signal_count": citation_signal_count,
                            },
                            evidence_refs=_bounded_signal_evidence(
                                "runtime_job",
                                job.job_id,
                                citation_count=len(citation_bank),
                            ),
                        ),
                    )
                )
            if qrels_signal_count == 0 and isinstance(evidence_refs, list) and evidence_refs:
                signals.append(
                    _integrity_signal(
                        signal_id=f"retrieval_quality:missing_qrels_status:{job.job_id}",
                        category="retrieval_quality",
                        status="unresolved",
                        severity="note",
                        message="Evidence refs exist, but retrieval qrels status is not recorded.",
                        evidence=_bounded_signal_evidence(
                            "runtime_job",
                            job.job_id,
                            evidence_ref_count=len(evidence_refs),
                        ),
                        next_actions=[
                            "Record qrels_status before making retrieval-quality claims."
                        ],
                        metadata={"evidence_ref_count": len(evidence_refs)},
                        drilldown=_integrity_payload_drilldown(
                            source_id=job.job_id,
                            source_kind="workflow_state_missing_qrels_status",
                            status="unresolved",
                            checked_facts={
                                "runtime_job_id": job.job_id,
                                "evidence_ref_count": len(evidence_refs),
                                "qrels_signal_count": qrels_signal_count,
                            },
                            evidence_refs=_bounded_signal_evidence(
                                "runtime_job",
                                job.job_id,
                                evidence_ref_count=len(evidence_refs),
                            ),
                        ),
                    )
                )

        deduped_by_id: dict[str, dict[str, Any]] = {}
        for signal in signals:
            signal_id = str(signal.get("signal_id") or "")
            existing = deduped_by_id.get(signal_id)
            if existing is None or _integrity_status_rank(str(signal.get("status") or "")) > _integrity_status_rank(
                str(existing.get("status") or "")
            ):
                deduped_by_id[signal_id] = signal
        deduped_signals = sorted(deduped_by_id.values(), key=_integrity_signal_sort_key)

        status_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for signal in deduped_signals:
            _increment_projection_count(status_counts, str(signal.get("status") or "unknown"))
            _increment_projection_count(severity_counts, str(signal.get("severity") or "unknown"))
            _increment_projection_count(category_counts, str(signal.get("category") or "unknown"))

        blockers = [
            str(signal.get("message"))
            for signal in deduped_signals
            if signal.get("status") == "block"
        ][:16]
        unresolved = [
            str(signal.get("message"))
            for signal in deduped_signals
            if signal.get("status") == "unresolved"
        ][:16]
        workflow_states = [
            job.metadata.get(_WRITING_WORKFLOW_STATE_KEY)
            for job in jobs
            if isinstance(job.metadata.get(_WRITING_WORKFLOW_STATE_KEY), dict)
        ]
        primary_workflow_state = workflow_states[0] if workflow_states else None
        gate_payload = {
            "schema_version": _EVIDENCE_INTEGRITY_GATE_SCHEMA_VERSION,
            "generated_at": utc_now_iso_z(),
            "scope": dict(passport.get("scope") or {}),
            "status": _integrity_gate_status(deduped_signals),
            "signals": deduped_signals,
            "summary": {
                "signal_count": len(deduped_signals),
                "status_counts": status_counts,
                "severity_counts": severity_counts,
                "category_counts": category_counts,
                "runtime_job_count": len(jobs),
                "artifact_payload_count": len(artifact_rows),
                "workflow_passport_status": passport.get("gate_summary"),
                "unresolved_is_pass": False,
            },
            "blockers": blockers,
            "unresolved": unresolved,
            "provenance": {
                "derived_from": [
                    "runtime.workflow_passport",
                    "runtime.jobs",
                    "runtime.artifacts",
                    "runtime.writing_workflow_state",
                    "runtime.evidence_retrieval_diagnostics",
                    "runtime.citation_verifications",
                    "runtime.academic_writing_lint",
                    "runtime.export_manifest",
                    "runtime.behavior_eval_pack",
                ],
                "workflow_passport_schema_version": passport.get("schema_version"),
            },
        }
        gate_payload["enforcement"] = _workflow_readiness_claims(
            workflow_state=primary_workflow_state,
            gate=gate_payload,
        )
        gate_payload["blocking_action_boundary"] = gate_payload["enforcement"].get("blocking_action_boundary")
        return {
            **gate_payload,
        }

    def build_agent_handoff_card(
        self,
        job_id: str,
        *,
        persist: bool = False,
    ) -> dict[str, Any]:
        """Build a bounded resume card for one runtime-visible agent job.

        Args:
            job_id: Runtime job id that owns the agent request.
            persist: When true, store the card as job metadata and a metadata
                artifact for later MCP/Agent Workspace reads.

        Returns:
            JSON-safe handoff card with probes, blockers, and resume prompt.

        Raises:
            ValueError: If the job is missing or not an agent request.
        """

        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")
        kind_value = str(getattr(job.kind, "value", job.kind))
        if kind_value != JobKind.AGENT_REQUEST.value and not bool(job.metadata.get("agent_bridge")):
            raise ValueError("agent handoff card requires an agent request job")

        session = self.get_session(job.session_id)
        metadata = dict(job.metadata)
        request_id = _metadata_string(metadata, ("agent_request_id", "request_id", "runtime_request_id"))
        project_id = _project_id_for_job(job, session)
        agent_host = _metadata_string(metadata, ("agent_host",))
        intent = _metadata_string(metadata, ("intent", "task_goal", "target_document"))
        status = _handoff_status_from_job_status(job.status)
        passport = self.build_workflow_passport(
            session_id=job.session_id,
            job_id=job.job_id,
            project_id=project_id,
            limit=500,
        )
        gate = self.build_evidence_integrity_gate(
            session_id=job.session_id,
            job_id=job.job_id,
            project_id=project_id,
            limit=500,
        )
        current_stage_id = _safe_projection_string(passport.get("current_stage_id"))
        stages = passport.get("stages") if isinstance(passport.get("stages"), list) else []
        stage_by_id = {
            str(stage.get("stage_id")): stage
            for stage in stages
            if isinstance(stage, dict) and _safe_projection_string(stage.get("stage_id")) is not None
        }
        current_stage = stage_by_id.get(str(current_stage_id)) if current_stage_id else None
        completed_evidence: list[dict[str, Any]] = []
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            if stage.get("status") != "complete":
                continue
            for artifact_ref in list(stage.get("present_artifacts") or [])[:8]:
                if isinstance(artifact_ref, dict):
                    _append_unique_mapping(
                        completed_evidence,
                        {
                            "stage_id": stage.get("stage_id"),
                            "stage_label": stage.get("label"),
                            **_compact_projection_mapping(artifact_ref),
                        },
                    )

        blockers = [
            str(item)
            for item in list(gate.get("blockers") or [])[:16]
            if _safe_projection_string(item) is not None
        ]
        unresolved = [
            str(item)
            for item in list(gate.get("unresolved") or [])[:16]
            if _safe_projection_string(item) is not None
        ]
        if status == "failed" and job.error:
            _append_unique_text(blockers, f"Agent request failed: {str(job.error)[:500]}", max_items=16)
        elif status in {"cancelled", "paused"}:
            _append_unique_text(unresolved, f"Agent request is {status}; inspect current job state before resuming.", max_items=16)
        readiness_claims = _workflow_readiness_claims(
            workflow_state=metadata.get(_WRITING_WORKFLOW_STATE_KEY) if isinstance(metadata.get(_WRITING_WORKFLOW_STATE_KEY), dict) else None,
            gate=gate,
        )
        action_preflight = _workflow_action_preflight_payload(
            action_id="agent.handoff_card",
            required_claim_id="handoff_readiness",
            passport=passport,
            gate=gate,
            readiness_claims=readiness_claims,
            require_ready=False,
            workflow_state=metadata.get(_WRITING_WORKFLOW_STATE_KEY)
            if isinstance(metadata.get(_WRITING_WORKFLOW_STATE_KEY), dict)
            else None,
        )
        refresh_receipt = _workflow_refresh_receipt_payload(
            action_preflight=action_preflight,
            passport=passport,
            gate=gate,
            readiness_claims=readiness_claims,
            session_id=job.session_id,
            job_id=job.job_id,
            project_id=project_id,
        )
        receipt_ref = {
            "ref_type": "preflight_refresh_receipt",
            "ref_id": refresh_receipt["receipt_id"],
            "schema_version": refresh_receipt["schema_version"],
            "generated_at": refresh_receipt["generated_at"],
            "status": refresh_receipt["status"],
        }
        action_preflight_evidence = list(action_preflight.get("evidence") or [])
        _append_unique_mapping(action_preflight_evidence, receipt_ref, max_items=16)
        action_preflight = {
            **action_preflight,
            "refresh_receipt_id": refresh_receipt["receipt_id"],
            "refresh_receipt": refresh_receipt,
            "evidence": action_preflight_evidence[:16],
            "summary": {
                **dict(action_preflight.get("summary") or {}),
                "refresh_receipt_id": refresh_receipt["receipt_id"],
            },
            "provenance": {
                **dict(action_preflight.get("provenance") or {}),
                "refresh_receipt_schema_version": refresh_receipt["schema_version"],
            },
        }
        handoff_claim = next(
            (
                claim
                for claim in readiness_claims.get("claims", [])
                if isinstance(claim, dict) and claim.get("claim_id") == "handoff_readiness"
            ),
            None,
        )
        if isinstance(handoff_claim, dict):
            for message in handoff_claim.get("blockers") or []:
                _append_unique_text(blockers, message, max_items=16)
            for message in handoff_claim.get("unresolved") or []:
                _append_unique_text(unresolved, message, max_items=16)
        for message in action_preflight.get("blockers") or []:
            _append_unique_text(blockers, message, max_items=16)
        for message in action_preflight.get("unresolved") or []:
            _append_unique_text(unresolved, message, max_items=16)
        _append_unique_mapping(completed_evidence, receipt_ref, max_items=24)
        job_artifacts = self.get_job_artifacts(job.job_id)
        scoped_jobs = [
            candidate
            for candidate in self._jobs.values()
            if candidate.session_id == job.session_id
            and (project_id is None or _project_id_for_job(candidate, self.get_session(candidate.session_id)) == project_id)
        ]
        scoped_artifacts_by_job = {
            candidate.job_id: (job_artifacts if candidate.job_id == job.job_id else self.get_job_artifacts(candidate.job_id))
            for candidate in scoped_jobs
        }
        replay_lineage = _agent_handoff_current_replay_lineage(
            job=job,
            artifacts=job_artifacts,
            refresh_receipt=refresh_receipt,
            project_id=project_id,
            limit=12,
        )
        replay_index = _agent_handoff_current_replay_index(
            jobs=scoped_jobs,
            sessions_by_id=dict(self._sessions),
            artifacts_by_job=scoped_artifacts_by_job,
            current_job=job,
            current_receipt=refresh_receipt,
            session_id=job.session_id,
            project_id=project_id,
            limit=10,
        )
        replay_recovery = _agent_handoff_replay_recovery(
            lineage=replay_lineage,
            replay_index=replay_index,
            refresh_receipt=refresh_receipt,
        )

        artifacts = _bounded_handoff_artifacts(job_artifacts)
        resource_refs = _bounded_handoff_refs(metadata.get("resource_refs"), max_items=50)
        resume_probe_params = {
            "session_id": job.session_id,
            "job_id": job.job_id,
            "project_id": project_id,
        }
        resume_probes = [
            _handoff_resume_probe(
                "Read linked agent request",
                f"/api/agent-bridge/request/{request_id}",
            )
            if request_id
            else _handoff_resume_probe("Read runtime job", f"/runtime/job/{job.job_id}"),
            _handoff_resume_probe("Read runtime snapshot", f"/runtime/job/{job.job_id}/snapshot"),
            _handoff_resume_probe("Read workflow passport", "/runtime/workflow-passport", resume_probe_params),
            _handoff_resume_probe("Read evidence integrity gate", "/runtime/evidence-integrity-gate", resume_probe_params),
            _handoff_resume_probe("Read job artifacts", f"/runtime/job/{job.job_id}/artifacts"),
            _handoff_resume_probe("Read workflow replay lineage", f"/runtime/job/{job.job_id}/workflow-replay-lineage"),
            _handoff_resume_probe("List scoped workflow replay index", "/runtime/workflow-replay-index", {
                "session_id": job.session_id,
                "project_id": project_id,
                "limit": 10,
            }),
        ]
        if refresh_receipt.get("receipt_id"):
            resume_probes.append(
                _handoff_resume_probe(
                    "Inspect preflight refresh receipt",
                    f"/runtime/job/{job.job_id}/preflight-refresh-receipt",
                    {"receipt_id": refresh_receipt["receipt_id"]},
                )
            )
        for replay_probe in replay_recovery.get("resume_probes") or []:
            if isinstance(replay_probe, dict):
                _append_unique_mapping(resume_probes, replay_probe, max_items=16)
        forbidden_actions = [
            "Do not push, tag, release, publish, deploy, or upload external artifacts without explicit user authorization.",
            "Do not create Codex skills, Feishu/Lark integrations, or standalone installer/package surfaces from this handoff.",
            "Do not copy, vendor, embed, or translate AGPL PDFMathTranslate code into Scholar AI.",
            "Do not directly write, repair, download, or relink Zotero databases or attachments.",
            "Do not modify github/ reference repositories.",
            "Do not treat unresolved integrity checks as passed or verified.",
        ]
        current_stage_label = str(current_stage.get("label") or current_stage_id or "agent_handoff") if current_stage else str(
            current_stage_id or "agent_handoff"
        )
        resume_prompt_lines = [
            "Resume Scholar AI / 文献助手 MCP-first local work from this handoff card.",
            f"Request id: {request_id or 'unknown'}; runtime job id: {job.job_id}; status: {status}.",
            f"Current stage: {current_stage_label}.",
            "Before any mutating action, run the read-only replay lineage, replay index, workflow passport, and integrity-gate probes listed in this card; then re-check git status plus rollback discipline.",
            "Keep unresolved evidence/integrity checks visible; only proceed with local code, docs, tests, and runtime artifacts inside the authorized boundaries.",
        ]
        highest_priority = replay_recovery.get("highest_priority_attempt")
        if isinstance(highest_priority, dict) and highest_priority.get("job_id"):
            resume_prompt_lines.append(
                "Replay recovery: "
                f"highest-priority job {highest_priority.get('job_id')} "
                f"({highest_priority.get('latest_status', 'unknown')}) "
                f"for {highest_priority.get('latest_required_claim_id', 'unknown')}."
            )
        if blockers:
            resume_prompt_lines.append("Blocking risks: " + "; ".join(blockers[:3]))
        if unresolved:
            resume_prompt_lines.append("Unresolved checks: " + "; ".join(unresolved[:3]))

        card = {
            "schema_version": _AGENT_HANDOFF_CARD_SCHEMA_VERSION,
            "generated_at": utc_now_iso_z(),
            "request_id": request_id,
            "job_id": job.job_id,
            "session_id": job.session_id,
            "project_id": project_id,
            "status": status,
            "agent_host": agent_host,
            "intent": intent,
            "current_stage_id": current_stage_id,
            "completed_evidence": completed_evidence[:24],
            "blockers": blockers[:16],
            "unresolved": unresolved[:16],
            "readiness_claims": readiness_claims,
            "action_preflight": action_preflight,
            "replay_recovery": replay_recovery,
            "resource_refs": resource_refs[:50],
            "artifacts": artifacts[:24],
            "resume_probes": resume_probes[:16],
            "forbidden_actions": forbidden_actions,
            "resume_prompt": "\n".join(resume_prompt_lines),
            "provenance": {
                "derived_from": [
                    "runtime.job_metadata",
                    "runtime.artifacts",
                    "runtime.workflow_passport",
                    "runtime.evidence_integrity_gate",
                    "runtime.action_preflight",
                    "runtime.preflight_refresh_receipt",
                    "runtime.workflow_replay_lineage",
                    "runtime.workflow_replay_index",
                ],
                "workflow_passport_schema_version": passport.get("schema_version"),
                "evidence_integrity_gate_schema_version": gate.get("schema_version"),
                "action_preflight_schema_version": action_preflight.get("schema_version"),
                "preflight_refresh_receipt_schema_version": refresh_receipt.get("schema_version"),
                "workflow_replay_lineage_schema_version": replay_lineage.get("schema_version"),
                "workflow_replay_index_schema_version": replay_index.get("schema_version"),
                "preflight_refresh_receipt_id": refresh_receipt.get("receipt_id"),
                "artifact_count": len(artifacts),
                "resource_ref_count": len(resource_refs),
                "replay_recovery_read_only": True,
            },
        }
        if persist:
            return self.persist_agent_handoff_card(job.job_id, card)
        return card

    def persist_agent_handoff_card(
        self,
        job_id: str,
        card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one handoff card as job metadata and metadata artifact.

        Args:
            job_id: Runtime job id that owns the card.
            card: Optional prebuilt card. When omitted, a fresh card is built.

        Returns:
            The card content after persistence.

        Raises:
            ValueError: If the job is missing or the card is malformed.
        """

        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        if card is None:
            return self.build_agent_handoff_card(normalized_job_id, persist=True)
        if not isinstance(card, dict):
            raise ValueError("agent handoff card must be an object")
        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")
        normalized_card = dict(_json_safe_copy(card))
        if normalized_card.get("schema_version") != _AGENT_HANDOFF_CARD_SCHEMA_VERSION:
            raise ValueError("agent handoff card schema_version is invalid")
        action_preflight = normalized_card.get("action_preflight")
        if isinstance(action_preflight, dict) and isinstance(action_preflight.get("refresh_receipt"), dict):
            self.persist_preflight_refresh_receipt(job.job_id, dict(action_preflight["refresh_receipt"]))
            refreshed_job = self.get_job(normalized_job_id)
            if refreshed_job is not None:
                job = refreshed_job
        metadata = dict(job.metadata)
        metadata[_AGENT_HANDOFF_CARD_KEY] = normalized_card
        updated = replace(job, metadata=metadata)
        self._jobs[normalized_job_id] = updated
        self._store_artifact(
            WritingArtifact.create(
                job_id=job.job_id,
                session_id=job.session_id,
                artifact_type=ArtifactType.METADATA,
                content=normalized_card,
                created_by="runtime",
                metadata={
                    "kind": _AGENT_HANDOFF_CARD_KEY,
                    "schema_version": _AGENT_HANDOFF_CARD_SCHEMA_VERSION,
                    "agent_request_id": normalized_card.get("request_id"),
                    "project_id": normalized_card.get("project_id"),
                    "current_stage_id": normalized_card.get("current_stage_id"),
                    "status": normalized_card.get("status"),
                },
                mime_type="application/json",
            )
        )
        self.emit_job_progress(
            job.job_id,
            stage="agent_handoff",
            message="Agent handoff card recorded for resumable local workflow.",
            progress=100 if normalized_card.get("status") in {"completed", "failed", "cancelled"} else None,
            data={
                "request_id": normalized_card.get("request_id"),
                "handoff_card_recorded": True,
                "blocker_count": len(normalized_card.get("blockers") or []),
                "unresolved_count": len(normalized_card.get("unresolved") or []),
            },
        )
        self._autosave_if_enabled()
        return normalized_card

    async def complete_job(
        self,
        job_id: str,
        result: Any | None = None,
        artifact_metadata: dict[str, Any] | None = None,
    ) -> WritingJob:
        """Mark a job as completed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if artifact_metadata is not None and not isinstance(artifact_metadata, dict):
            raise ValueError("artifact_metadata must be an object")

        job = job.with_status(JobStatus.COMPLETED)
        self._jobs[job_id] = job

        if result:
            self._store_artifact(
                WritingArtifact.create(
                    job_id=job_id,
                    session_id=job.session_id,
                    artifact_type=ArtifactType.TRANSFORMED_TEXT,
                    content=result,
                    created_by="system",
                    metadata=dict(artifact_metadata or {}),
                )
            )

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_COMPLETED,
                data={"result_artifact_count": len(self._artifacts.get(job_id, []))},
            ),
        )

        self._sync_job_to_memory_if_enabled(job_id)
        self._schedule_runtime_job_capture(job)
        self._create_checkpoint(job.session_id, kind="job_completed", source_job_id=job_id)
        self._logger.info("Completed job %s", job_id)
        self._autosave_if_enabled()
        return job

    async def fail_job(self, job_id: str, error: str) -> WritingJob:
        """Mark a job as failed with error message."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job = job.with_error(error)
        self._jobs[job_id] = job

        self._emit_event(
            job.session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=job.session_id,
                event_type=EventType.JOB_FAILED,
                data={"error": error},
            ),
        )

        self._sync_job_to_memory_if_enabled(job_id)
        self._schedule_runtime_job_capture(job, error=error)
        self._create_checkpoint(job.session_id, kind="job_failed", source_job_id=job_id)
        self._logger.info("Failed job %s: %s", job_id, error)
        self._autosave_if_enabled()
        return job

    def _schedule_runtime_job_capture(
        self,
        job: "WritingJob",
        *,
        error: str | None = None,
    ) -> None:
        """Fire runtime-job capture off the terminal-state path."""

        try:
            from evolution import run_capture_in_background
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug(
                "evolution package unavailable; runtime capture skipped: %s", exc
            )
            return
        run_capture_in_background(
            self._capture_runtime_job_to_evolution,
            job,
            label="runtime",
            error=error,
        )

    def _capture_runtime_job_to_evolution(
        self,
        job: "WritingJob",
        *,
        error: str | None = None,
    ) -> None:
        """Best-effort runtime-job → evolution candidate write.

        Capture contract:
          - never raises; capture failures degrade to a debug log
          - skipped entirely when evolution.candidate_capture_enabled = false
          - CANCELLED jobs are not captured (extractor returns None)
          - existing complete_job / fail_job behavior unchanged otherwise
        """

        try:
            from evolution import (
                extract_from_job,
                get_evolution_service,
                is_candidate_capture_enabled,
            )
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug("evolution package unavailable; runtime capture skipped: %s", exc)
            return

        if not is_candidate_capture_enabled():
            return

        try:
            args = extract_from_job(job, error=error)
        except Exception as exc:
            self._logger.warning("runtime capture extractor failed: %s", exc)
            return
        if args is None:
            return

        try:
            service = get_evolution_service()
            service.capture(
                workspace_id=args.workspace_id,
                source_type=args.source_type,
                source_id=args.source_id,
                source_summary=args.source_summary,
                memory_type=args.memory_type,
                title=args.title,
                claim=args.claim,
                future_use=args.future_use,
                confidence=args.confidence,
                project_id=args.project_id,
                source_route=args.source_route,
                evidence_refs=args.evidence_refs,
                risk_level=args.risk_level,
            )
        except Exception as exc:
            self._logger.warning(
                "runtime capture write failed for job %s: %s", job.job_id, exc,
            )

    def _schedule_skill_capture(
        self,
        job: "WritingJob",
        result: "SkillRunResult",
    ) -> None:
        """Fire skill capture off the job-completion path."""

        try:
            from evolution import run_capture_in_background
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug(
                "evolution package unavailable; skill capture skipped: %s", exc
            )
            return
        run_capture_in_background(
            self._capture_skill_run_to_evolution, job, result, label="skill"
        )

    def _capture_skill_run_to_evolution(
        self,
        job: "WritingJob",
        result: "SkillRunResult",
    ) -> None:
        """Best-effort skill_run → evolution candidate write.

        Capture contract:
          - never raises; capture failures degrade to a warning log
          - skipped entirely when evolution.candidate_capture_enabled = false
          - SUCCESS / PARTIAL  → SKILL_DRAFT candidate (future promotion may
                                  promote to a managed disabled skill draft)
          - FAILED / TIMEOUT / CANCELLED → TOOL_RELIABILITY candidate
          - both candidates coexist with the broader runtime-job capture
            (different source_type so they never dedupe; reviewers see both)
        """

        try:
            from evolution import (
                extract_from_skill_run,
                get_evolution_service,
                is_candidate_capture_enabled,
            )
        except Exception as exc:  # pragma: no cover - evolution package missing
            self._logger.debug("evolution package unavailable; skill capture skipped: %s", exc)
            return

        if not is_candidate_capture_enabled():
            return

        try:
            args = extract_from_skill_run(result, job=job)
        except Exception as exc:
            self._logger.warning("skill capture extractor failed: %s", exc)
            return
        if args is None:
            return

        try:
            service = get_evolution_service()
            service.capture(
                workspace_id=args.workspace_id,
                source_type=args.source_type,
                source_id=args.source_id,
                source_summary=args.source_summary,
                memory_type=args.memory_type,
                title=args.title,
                claim=args.claim,
                future_use=args.future_use,
                confidence=args.confidence,
                project_id=args.project_id,
                source_route=args.source_route,
                evidence_refs=args.evidence_refs,
                risk_level=args.risk_level,
            )
        except Exception as exc:
            self._logger.warning(
                "skill capture write failed for job %s skill %s: %s",
                job.job_id, getattr(result, "skill_id", "?"), exc,
            )

    def _normalize_skill_run_result(self, job: WritingJob, result: SkillRunResult) -> SkillRunResult:
        """Rewrite skill results so the runtime job ID stays authoritative."""
        if result.job_id == job.job_id:
            return result

        metadata = dict(result.metadata)
        metadata.setdefault("source_skill_job_id", result.job_id)

        return SkillRunResult(
            job_id=job.job_id,
            skill_id=result.skill_id,
            status=result.status,
            input_text=result.input_text,
            output_text=result.output_text,
            timestamp=result.timestamp,
            execution_time_ms=result.execution_time_ms,
            warnings=list(result.warnings),
            metadata=metadata,
            structured_output=dict(result.structured_output),
            evidence_refs=list(result.evidence_refs),
            audit_id=result.audit_id,
        )

    def _store_skill_run_artifact(self, job: WritingJob, result: SkillRunResult) -> WritingArtifact:
        """Persist a skill result as a typed artifact."""
        artifact_type = ArtifactType.AUDIT_RECORD if result.is_failed() else ArtifactType.TRANSFORMED_TEXT
        artifact = WritingArtifact.create(
            job_id=job.job_id,
            session_id=job.session_id,
            artifact_type=artifact_type,
            content=result.to_dict(),
            created_by=result.skill_id,
            metadata={
                "execution_time_ms": result.execution_time_ms,
                "warnings": list(result.warnings),
                "skill_result_status": result.status.value,
                "source_skill_job_id": result.job_id,
                **dict(result.metadata),
            },
            mime_type="application/json",
        )
        self._store_artifact(artifact)
        return artifact

    async def _finalize_executor_result(self, job_id: str, executor_result: Any) -> WritingJob | None:
        """Finalize a job when an executor returns a concrete result."""
        job = self.get_job(job_id)
        if not job:
            return None

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return job

        if isinstance(executor_result, SkillRunResult):
            normalized_result = self._normalize_skill_run_result(job, executor_result)
            self._store_skill_run_artifact(job, normalized_result)
            self._schedule_skill_capture(job, normalized_result)

            if normalized_result.is_failed():
                error_message = (
                    normalized_result.output_text
                    or "; ".join(normalized_result.warnings)
                    or f"Skill execution failed: {normalized_result.status.value}"
                )
                await self.fail_job(job_id, error_message)
            else:
                await self.complete_job(job_id)
            return self.get_job(job_id)

        if isinstance(executor_result, dict):
            status_value = str(executor_result.get("status", "")).lower()
            if status_value in {"failed", "timeout", "cancelled"} or "error" in executor_result:
                error_message = str(
                    executor_result.get("error")
                    or executor_result.get("message")
                    or executor_result.get("output_text")
                    or executor_result
                )
                await self.fail_job(job_id, error_message)
            else:
                await self.complete_job(job_id, result=executor_result)
            return self.get_job(job_id)

        if isinstance(executor_result, str):
            await self.complete_job(job_id, result=executor_result)
            return self.get_job(job_id)

        return job

    def sync_job_to_memory(
        self,
        job_id: str,
        wing: str | None = None,
        room: str | None = None,
    ) -> dict[str, Any]:
        """
        Persist a terminal job into MemPalace when the adapter is available.

        Why:
            Long-term memory should never block job lifecycle transitions. This
            method isolates the sync step behind a best-effort adapter boundary.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        adapter = self._get_memory_adapter()
        if adapter is None:
            return {
                "success": False,
                "available": False,
                "reason": "mempalace adapter unavailable",
                "wing": wing or "",
                "room": room or "",
            }

        session = self.get_session(job.session_id)
        artifacts = self.get_job_artifacts(job_id)
        events = self.get_job_events(job_id)
        result = adapter.sync_runtime_job(
            job,
            session,
            artifacts,
            events,
            wing=wing,
            room=room,
        )
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {
            "success": False,
            "available": False,
            "reason": "unexpected mempalace sync response",
            "wing": wing or "",
            "room": room or "",
        }

    # ==========================================================================
    # Event Management
    # ==========================================================================

    def get_job_events(
        self,
        job_id: str,
        since_timestamp: str | None = None,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[WritingEvent]:
        """Get events for a job, optionally filtered by a polling cursor."""
        job = self.get_job(job_id)
        if not job:
            return []

        session_id = job.session_id
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        self._ensure_session_event_sequences(session_id)
        session_events = self._events.get(session_id, [])
        job_events = sorted(
            [e for e in session_events if e.job_id == job_id],
            key=lambda event: (event.sequence, event.timestamp, event.event_id),
        )

        if after_sequence is not None:
            job_events = [event for event in job_events if event.sequence > after_sequence]
        elif since_timestamp is not None:
            job_events = [
                event
                for event in job_events
                if event.timestamp > since_timestamp
                or (
                    event.timestamp == since_timestamp
                    and after_event_id is not None
                    and event.event_id > after_event_id
                )
            ]
        elif after_event_id is not None:
            cursor_index = next(
                (
                    index
                    for index, event in enumerate(job_events)
                    if event.event_id == after_event_id
                ),
                None,
            )
            if cursor_index is not None:
                job_events = job_events[cursor_index + 1 :]

        if limit is not None:
            job_events = job_events[:limit]

        return job_events

    def subscribe_to_events(self, session_id: str, callback: Callable[[WritingEvent], None]) -> None:
        """Subscribe to events in a session."""
        if session_id not in self._event_subscribers:
            self._event_subscribers[session_id] = []
        self._event_subscribers[session_id].append(callback)

    def _emit_event(self, session_id: str, event: WritingEvent) -> None:
        """Emit an event to all subscribers."""
        if session_id not in self._events:
            self._events[session_id] = []
        sequenced_event = self._with_event_sequence(event)
        self._events[session_id].append(sequenced_event)
        event_payload = sequenced_event.to_dict()
        event_payload.update(dict(event.data))
        self._append_transcript_event(session_id, event.event_type.value, event_payload)

        # Notify subscribers
        subscribers = self._event_subscribers.get(session_id, [])
        for callback in subscribers:
            try:
                callback(sequenced_event)
            except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:
                self._logger.error("Error in event subscriber: %s", exc)

    # ==========================================================================
    # Artifact Management
    # ==========================================================================

    def get_job_artifacts(self, job_id: str, artifact_type: ArtifactType | None = None) -> list[WritingArtifact]:
        """Get artifacts for a job, optionally filtered by type."""
        artifacts = self._artifacts.get(job_id, [])
        if artifact_type:
            artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
        return artifacts

    def add_job_artifact(
        self,
        job_id: str,
        *,
        artifact_type: ArtifactType,
        content: str | dict[str, Any],
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        mime_type: str = "application/json",
    ) -> WritingArtifact:
        """Attach a typed artifact to an existing runtime job.

        Args:
            job_id: Existing runtime job identifier.
            artifact_type: Stable artifact category used by runtime consumers.
            content: JSON object or text payload to store with the job.
            created_by: Optional actor identifier for audit provenance.
            metadata: JSON object with lightweight indexable fields.
            mime_type: MIME type for the artifact content.

        Returns:
            The immutable artifact record created for the job.

        Raises:
            ValueError: If the job is missing or the artifact shape is invalid.
        """
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            raise ValueError("job_id must not be empty")
        job = self.get_job(normalized_job_id)
        if job is None:
            raise ValueError(f"Job {normalized_job_id} not found")
        if not isinstance(artifact_type, ArtifactType):
            raise ValueError("artifact_type must be an ArtifactType")
        if not isinstance(content, (str, dict)):
            raise ValueError("content must be a string or object")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        normalized_mime_type = str(mime_type or "").strip()
        if not normalized_mime_type:
            raise ValueError("mime_type must not be empty")

        artifact = WritingArtifact.create(
            job_id=job.job_id,
            session_id=job.session_id,
            artifact_type=artifact_type,
            content=dict(content) if isinstance(content, dict) else content,
            created_by=created_by,
            metadata=dict(metadata or {}),
            mime_type=normalized_mime_type,
        )
        self._store_artifact(artifact)
        self._autosave_if_enabled()
        return artifact

    def _store_artifact(self, artifact: WritingArtifact) -> None:
        """Store an artifact (internal method)."""
        if artifact.job_id not in self._artifacts:
            self._artifacts[artifact.job_id] = []
        self._artifacts[artifact.job_id].append(artifact)
        self._append_transcript_event(artifact.session_id, "artifact_created", artifact.to_dict())

    # ==========================================================================
    # Approval Management
    # ==========================================================================

    def request_approval(
        self,
        job_id: str,
        session_id: str,
        reason: str,
        content_preview: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingApprovalRequest:
        """Request user approval for a job."""
        approval = WritingApprovalRequest.create(
            job_id=job_id,
            session_id=session_id,
            reason=reason,
            content_preview=content_preview,
            metadata=metadata,
        )
        self._approval_requests[approval.approval_id] = approval

        self._emit_event(
            session_id,
            WritingEvent.create(
                job_id=job_id,
                session_id=session_id,
                event_type=EventType.APPROVAL_REQUIRED,
                data={"approval_id": approval.approval_id, "reason": reason},
            ),
        )

        self._logger.info("Created approval request %s for job %s", approval.approval_id, job_id)
        self._autosave_if_enabled()
        return approval

    def get_approval_request(self, approval_id: str) -> WritingApprovalRequest | None:
        """Get an approval request by ID."""
        return self._approval_requests.get(approval_id)

    async def grant_approval(self, approval_id: str, response_by: str | None = None) -> WritingApprovalRequest:
        """Grant approval."""
        approval = self.get_approval_request(approval_id)
        if not approval:
            raise ValueError(f"Approval request {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot grant approval already in status {approval.status.value}")

        approval = approval.with_approval(response_by=response_by)
        self._approval_requests[approval_id] = approval

        self._emit_event(
            approval.session_id,
            WritingEvent.create(
                job_id=approval.job_id,
                session_id=approval.session_id,
                event_type=EventType.APPROVAL_GRANTED,
                data={"approval_id": approval_id},
            ),
        )

        self._logger.info("Granted approval %s", approval_id)
        self._autosave_if_enabled()
        return approval

    async def reject_approval(self, approval_id: str, response_by: str | None = None) -> WritingApprovalRequest:
        """Reject approval."""
        approval = self.get_approval_request(approval_id)
        if not approval:
            raise ValueError(f"Approval request {approval_id} not found")

        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot reject approval already in status {approval.status.value}")

        approval = approval.with_rejection(response_by=response_by)
        self._approval_requests[approval_id] = approval

        self._emit_event(
            approval.session_id,
            WritingEvent.create(
                job_id=approval.job_id,
                session_id=approval.session_id,
                event_type=EventType.APPROVAL_REJECTED,
                data={"approval_id": approval_id},
            ),
        )

        self._logger.info("Rejected approval %s", approval_id)
        self._autosave_if_enabled()
        return approval

    # ==========================================================================
    # Backward Compatibility - Legacy Action Execution
    # ==========================================================================

    async def execute_action(
        self,
        session_id: str,
        action_id: str,
        input_text: str,
        scope: str = "section",
        output_mode: str = "word_safe",
        executor: Callable[[WritingJob], Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a legacy action through the runtime.
        
        Creates a job, executes it, and returns compatibility-formatted result.
        Maintains backward compatibility with existing action execution flows.
        """
        job = self.create_job(
            session_id=session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=input_text,
            action_id=action_id,
            scope=scope,
            output_mode=output_mode,
            tags=["legacy_action"],
        )

        await self.start_job(job.job_id, executor=executor)

        final_job = self.get_job(job.job_id) or job
        if final_job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            await self.complete_job(job.job_id)
            final_job = self.get_job(job.job_id) or final_job

        artifacts = self.get_job_artifacts(job.job_id)
        output_text = ""
        if artifacts:
            first_artifact = artifacts[0]
            if isinstance(first_artifact.content, str):
                output_text = first_artifact.content
            elif isinstance(first_artifact.content, dict):
                output_text = (
                    first_artifact.content.get("output_text")
                    or first_artifact.content.get("error")
                    or first_artifact.content.get("text")
                    or str(first_artifact.content)
                )

        if not output_text and final_job.error:
            output_text = final_job.error

        status_value = final_job.status.value
        if final_job.status == JobStatus.COMPLETED:
            status_value = "succeeded"

        return {
            "job_id": job.job_id,
            "status": status_value,
            "input": input_text,
            "output": output_text,
            "action_id": action_id,
            **({"error": final_job.error} if final_job.status != JobStatus.COMPLETED and final_job.error else {}),
        }

    # ==========================================================================
    # State Export (for debugging and persistence preparation)
    # ==========================================================================

    def export_state(self) -> dict[str, Any]:
        """Export full runtime state (for snapshots and persistence)."""
        return {
            "sessions": {sid: s.to_dict() for sid, s in self._sessions.items()},
            "jobs": {jid: j.to_dict() for jid, j in self._jobs.items()},
            "job_queue": self._job_queue[:],
            "events": {
                sid: [e.to_dict() for e in events]
                for sid, events in self._events.items()
            },
            "artifacts": {
                jid: [a.to_dict() for a in artifacts]
                for jid, artifacts in self._artifacts.items()
            },
            "approval_requests": {
                aid: a.to_dict() for aid, a in self._approval_requests.items()
            },
            "checkpoints": {
                sid: [dict(checkpoint) for checkpoint in checkpoints]
                for sid, checkpoints in self._session_checkpoints.items()
            },
        }

    def import_state(self, state: dict[str, Any]) -> None:
        """Import runtime state (for recovery and restoration)."""
        if not isinstance(state, dict):
            raise TypeError("state must be a dictionary")

        sessions_raw = state.get("sessions", {})
        jobs_raw = state.get("jobs", {})
        job_queue_raw = state.get("job_queue", [])
        events_raw = state.get("events", {})
        artifacts_raw = state.get("artifacts", {})
        approvals_raw = state.get("approval_requests", state.get("approvals", {}))
        checkpoints_raw = state.get("checkpoints", {})

        if not isinstance(sessions_raw, dict):
            raise TypeError("sessions must be a mapping")
        if not isinstance(jobs_raw, dict):
            raise TypeError("jobs must be a mapping")
        if not isinstance(events_raw, dict):
            raise TypeError("events must be a mapping")
        if not isinstance(artifacts_raw, dict):
            raise TypeError("artifacts must be a mapping")
        if not isinstance(approvals_raw, dict):
            raise TypeError("approval_requests must be a mapping")
        if not isinstance(checkpoints_raw, dict):
            raise TypeError("checkpoints must be a mapping")
        if not isinstance(job_queue_raw, list):
            raise TypeError("job_queue must be a list")

        sessions: dict[str, WritingSession] = {}
        for session_id, payload in sessions_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("session payload must be a mapping")
            session = WritingSession(
                session_id=str(payload["session_id"]),
                user_id=None if payload.get("user_id") in (None, "") else str(payload.get("user_id")),
                mode=SessionMode(str(payload.get("mode", SessionMode.PROMPT.value))),
                created_at=str(payload.get("created_at")),
                settings=dict(payload.get("settings") or {}),
                tags=[str(tag) for tag in payload.get("tags", [])],
                metadata=dict(payload.get("metadata") or {}),
            )
            sessions[str(session_id)] = session

        jobs: dict[str, WritingJob] = {}
        for job_id, payload in jobs_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("job payload must be a mapping")
            job_kind, unknown_kind = _coerce_job_kind(payload.get("kind", JobKind.PROMPT_ACTION.value))
            metadata = dict(payload.get("metadata") or {})
            if unknown_kind:
                metadata.setdefault("unknown_job_kind", unknown_kind)
            job = WritingJob(
                job_id=str(payload["job_id"]),
                session_id=str(payload["session_id"]),
                kind=job_kind,
                status=JobStatus(str(payload.get("status", JobStatus.CREATED.value))),
                input_text=str(payload.get("input_text", "")),
                created_at=str(payload.get("created_at")),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                action_id=None if payload.get("action_id") in (None, "") else str(payload.get("action_id")),
                skill_id=None if payload.get("skill_id") in (None, "") else str(payload.get("skill_id")),
                scope=None if payload.get("scope") in (None, "") else str(payload.get("scope")),
                output_mode=None if payload.get("output_mode") in (None, "") else str(payload.get("output_mode")),
                error=None if payload.get("error") in (None, "") else str(payload.get("error")),
                tags=[str(tag) for tag in payload.get("tags", [])],
                metadata=metadata,
            )
            jobs[str(job_id)] = job

        self._sessions = sessions
        self._jobs = jobs
        self._job_queue = [str(job_id) for job_id in job_queue_raw if str(job_id) in jobs]
        if not self._job_queue:
            self._job_queue = list(jobs.keys())

        self._job_contexts = {}
        for job_id, job in jobs.items():
            ctx = JobExecutionContext(job=job)
            if job.status == JobStatus.PAUSED:
                ctx.is_paused = True
                ctx.pause_event.clear()
            if job.status == JobStatus.CANCELLED:
                ctx.is_cancelled = True
                ctx.cancel_event.set()
            self._job_contexts[job_id] = ctx
        self._job_tasks = {}

        events: dict[str, list[WritingEvent]] = {}
        for session_id, event_list in events_raw.items():
            if not isinstance(event_list, list):
                raise TypeError("event lists must be lists")
            restored_events: list[WritingEvent] = []
            for event_payload in event_list:
                if not isinstance(event_payload, dict):
                    raise TypeError("event payload must be a mapping")
                restored_events.append(
                    WritingEvent(
                        event_id=str(event_payload["event_id"]),
                        job_id=str(event_payload["job_id"]),
                        session_id=str(event_payload["session_id"]),
                        event_type=EventType(str(event_payload.get("event_type", EventType.JOB_CREATED.value))),
                        timestamp=str(event_payload.get("timestamp")),
                        sequence=self._coerce_event_sequence(event_payload.get("sequence")),
                        data=dict(event_payload.get("data") or {}),
                        metadata=dict(event_payload.get("metadata") or {}),
                    )
                )
            events[str(session_id)] = restored_events
        self._events = events
        for session_id in list(self._events.keys()):
            self._ensure_session_event_sequences(session_id)

        artifacts: dict[str, list[WritingArtifact]] = {}
        for job_id, artifact_list in artifacts_raw.items():
            if not isinstance(artifact_list, list):
                raise TypeError("artifact lists must be lists")
            restored_artifacts: list[WritingArtifact] = []
            for artifact_payload in artifact_list:
                if not isinstance(artifact_payload, dict):
                    raise TypeError("artifact payload must be a mapping")
                restored_artifacts.append(
                    WritingArtifact(
                        artifact_id=str(artifact_payload["artifact_id"]),
                        job_id=str(artifact_payload["job_id"]),
                        session_id=str(artifact_payload["session_id"]),
                        artifact_type=ArtifactType(str(artifact_payload.get("artifact_type", ArtifactType.METADATA.value))),
                        content=artifact_payload.get("content"),
                        created_at=str(artifact_payload.get("created_at")),
                        created_by=None if artifact_payload.get("created_by") in (None, "") else str(artifact_payload.get("created_by")),
                        metadata=dict(artifact_payload.get("metadata") or {}),
                        mime_type=str(artifact_payload.get("mime_type", "application/json")),
                    )
                )
            artifacts[str(job_id)] = restored_artifacts
        self._artifacts = artifacts

        approvals: dict[str, WritingApprovalRequest] = {}
        for approval_id, payload in approvals_raw.items():
            if not isinstance(payload, dict):
                raise TypeError("approval payload must be a mapping")
            approvals[str(approval_id)] = WritingApprovalRequest(
                approval_id=str(payload["approval_id"]),
                job_id=str(payload["job_id"]),
                session_id=str(payload["session_id"]),
                status=ApprovalStatus(str(payload.get("status", ApprovalStatus.PENDING.value))),
                requested_at=str(payload.get("requested_at")),
                reason=str(payload.get("reason", "")),
                content_preview=None if payload.get("content_preview") in (None, "") else str(payload.get("content_preview")),
                response_by=None if payload.get("response_by") in (None, "") else str(payload.get("response_by")),
                responded_at=None if payload.get("responded_at") in (None, "") else str(payload.get("responded_at")),
                metadata=dict(payload.get("metadata") or {}),
            )
        self._approval_requests = approvals
        checkpoints: dict[str, list[dict[str, Any]]] = {}
        for session_id, checkpoint_list in checkpoints_raw.items():
            if not isinstance(checkpoint_list, list):
                raise TypeError("checkpoint lists must be lists")
            restored_checkpoints: list[dict[str, Any]] = []
            for checkpoint_payload in checkpoint_list:
                if not isinstance(checkpoint_payload, dict):
                    raise TypeError("checkpoint payload must be a mapping")
                restored_checkpoints.append(
                    {
                        "checkpoint_id": str(checkpoint_payload["checkpoint_id"]),
                        "session_id": str(checkpoint_payload["session_id"]),
                        "event_id": str(checkpoint_payload["event_id"]),
                        "created_at": str(checkpoint_payload["created_at"]),
                        "kind": str(checkpoint_payload.get("kind", "auto")),
                        "metadata": dict(checkpoint_payload.get("metadata") or {}),
                    }
                )
            checkpoints[str(session_id)] = restored_checkpoints
        self._session_checkpoints = checkpoints
        self._session_transcripts = {session_id: [] for session_id in sessions.keys()}

        for session_id in sessions.keys():
            self._events.setdefault(session_id, [])
        for job_id in jobs.keys():
            self._artifacts.setdefault(job_id, [])
        self._logger.info("Imported runtime state with %s sessions and %s jobs", len(sessions), len(jobs))

    def persist_to_database(self) -> Path | None:
        """Persist the current runtime snapshot to SQLite."""
        if self._repository is None:
            return None

        self._repository.replace_state(self.export_state())
        return self._repository.db_path

    def load_from_database(self) -> bool:
        """Load runtime state from SQLite if the repository already has rows."""
        if self._repository is None:
            return False

        if not self._repository.is_healthy():
            self._logger.warning("Skipping SQLite runtime load because %s failed health checks", self._repository.db_path)
            return False

        if not self._repository.has_data():
            return False

        self.import_state(self._repository.load_state())
        self._hydrate_transcripts_from_repository()
        return True

    def _autosave_if_enabled(self) -> None:
        """Persist runtime state after mutating operations when autosave is enabled."""
        if self._autosave:
            self.persist_to_database()

    def _persist_state_after_event(self) -> None:
        """Persist the current state after an event or artifact mutation."""
        self._autosave_if_enabled()

    def _normalize_session_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        """Normalize workspace-bound session metadata for persistence and lookup."""
        payload = dict(metadata or {})
        explicit_root = payload.get("workspace_root")
        entry_cwd = Path(payload.get("entry_cwd") or explicit_root or Path.cwd()).expanduser().resolve()
        workspace_root = Path(explicit_root).expanduser().resolve() if explicit_root else _resolve_workspace_root(entry_cwd)
        payload["workspace_root"] = str(workspace_root)
        payload["entry_cwd"] = str(entry_cwd)
        payload["workspace_key"] = str(payload.get("workspace_key") or _stable_workspace_key(workspace_root))
        payload["title"] = str(payload.get("title") or "Untitled session")
        payload["status"] = str(payload.get("status") or "active")
        payload["updated_at"] = str(payload.get("updated_at") or utc_now_iso_z())
        payload.setdefault("head_event_id", None)
        payload.setdefault("head_checkpoint_id", None)
        payload.setdefault("parent_session_id", None)
        payload.setdefault("forked_from_turn_id", None)
        payload.setdefault("forked_from_checkpoint_id", None)
        return payload

    def _replace_session_metadata(self, session_id: str, **updates: Any) -> WritingSession:
        """Update a session metadata dict while preserving the immutable session object."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        metadata = dict(session.metadata)
        metadata.update(updates)
        updated_session = replace(session, metadata=metadata)
        self._sessions[session_id] = updated_session
        return updated_session

    def _refresh_session_title_from_first_prompt(self, session_id: str) -> None:
        """Replace placeholder titles with the first user-like transcript text."""
        session = self.get_session(session_id)
        if session is None:
            return
        current_title = str(session.metadata.get("title") or "").strip()
        if current_title and current_title.lower() != "untitled session":
            return
        first_prompt = ""
        for event in self._session_transcripts.get(session_id, []):
            payload = event.get("payload") if isinstance(event, dict) else None
            if not isinstance(payload, dict):
                continue
            if event.get("event_kind") not in {"job_created", "user", EventType.JOB_CREATED.value}:
                continue
            text = str(payload.get("input_text") or payload.get("text") or payload.get("content") or "").strip()
            if text:
                first_prompt = " ".join(text.split())[:30]
                break
        if first_prompt:
            self._replace_session_metadata(
                session_id,
                title=first_prompt,
                first_user_prompt=first_prompt,
            )

    def _append_transcript_event(
        self,
        session_id: str,
        event_kind: str,
        payload: dict[str, Any],
        *,
        parent_event_id: str | None = None,
        event_id: str | None = None,
        timestamp: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """Append an event to the transcript and move the active session head."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        transcript_event = {
            "event_id": event_id or f"evt_{os.urandom(8).hex()}",
            "session_id": session_id,
            "event_kind": event_kind,
            "timestamp": timestamp or utc_now_iso_z(),
            "workspace_key": session.metadata["workspace_key"],
            "parent_event_id": parent_event_id if parent_event_id is not None else session.metadata.get("head_event_id"),
            "payload": payload,
        }
        self._session_transcripts.setdefault(session_id, []).append(transcript_event)
        self._replace_session_metadata(
            session_id,
            head_event_id=transcript_event["event_id"],
            updated_at=transcript_event["timestamp"],
        )
        if event_kind in {"job_created", "user"} or (
            event_kind == EventType.JOB_CREATED.value and any(
                str(payload.get(key) or "").strip()
                for key in ("input_text", "text", "content")
            )
        ):
            self._refresh_session_title_from_first_prompt(session_id)
        if persist and self._repository is not None:
            self._repository.append_transcript_event(session_id, transcript_event)
        return transcript_event

    def _create_checkpoint(
        self,
        session_id: str,
        *,
        kind: str,
        source_job_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a checkpoint marker at the current transcript head."""
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        anchor_event_id = session.metadata.get("head_event_id")
        checkpoint_id = f"chk_{os.urandom(8).hex()}"
        checkpoint_event = self._append_transcript_event(
            session_id,
            "checkpoint_created",
            {
                "checkpoint_id": checkpoint_id,
                "kind": kind,
                **({"source_job_id": source_job_id} if source_job_id else {}),
            },
            parent_event_id=anchor_event_id,
        )
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "event_id": checkpoint_event["event_id"],
            "created_at": checkpoint_event["timestamp"],
            "kind": kind,
            "metadata": {
                "anchor_event_id": anchor_event_id,
                **({"source_job_id": source_job_id} if source_job_id else {}),
            },
        }
        self._session_checkpoints.setdefault(session_id, []).append(checkpoint)
        self._replace_session_metadata(session_id, head_checkpoint_id=checkpoint_id)
        return checkpoint

    def _ensure_transcript_loaded(self, session_id: str) -> None:
        """Load a transcript from disk when needed."""
        if self._session_transcripts.get(session_id):
            return
        if self._repository is None:
            return
        self._session_transcripts[session_id] = self._repository.load_transcript(session_id)

    def _get_lineage_to_event(self, session_id: str, event_id: str) -> list[dict[str, Any]]:
        """Follow parent pointers from an event back to the root."""
        self._ensure_transcript_loaded(session_id)
        event_index = {
            event["event_id"]: event
            for event in self._session_transcripts.get(session_id, [])
        }
        lineage: list[dict[str, Any]] = []
        current_event_id = event_id
        while current_event_id:
            event = event_index.get(current_event_id)
            if event is None:
                break
            lineage.append(event)
            current_event_id = event.get("parent_event_id")
        lineage.reverse()
        return lineage

    def _get_active_transcript(self, session_id: str) -> list[dict[str, Any]]:
        """Return the currently active transcript lineage."""
        session = self.get_session(session_id)
        if session is None:
            return []
        head_event_id = session.metadata.get("head_event_id")
        if not head_event_id:
            return []
        return self._get_lineage_to_event(session_id, head_event_id)

    def _get_checkpoint(self, session_id: str, checkpoint_id: str) -> dict[str, Any] | None:
        """Return a checkpoint record by ID for a session."""
        return next(
            (
                checkpoint
                for checkpoint in self._session_checkpoints.get(session_id, [])
                if checkpoint["checkpoint_id"] == checkpoint_id
            ),
            None,
        )

    def _hydrate_transcripts_from_repository(self) -> None:
        """Populate in-memory transcript caches after database rehydration."""
        if self._repository is None:
            return
        for session_id in self._sessions.keys():
            self._session_transcripts[session_id] = self._repository.load_transcript(session_id)

    def _get_memory_adapter(self) -> Any | None:
        """Resolve the optional MemPalace adapter lazily and cache the outcome."""
        if self._memory_adapter_resolved:
            return self._memory_adapter

        self._memory_adapter_resolved = True
        try:
            from layers.m_layer_mempalace_memory import (
                MempalaceMemoryAdapter,
                load_mempalace_settings,
            )

            self._memory_adapter = MempalaceMemoryAdapter(load_mempalace_settings())
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:  # pragma: no cover - optional integration path
            self._logger.warning("MemPalace adapter unavailable: %s", exc)
            self._memory_adapter = None
        return self._memory_adapter

    def _sync_job_to_memory_if_enabled(self, job_id: str) -> None:
        """Best-effort terminal job sync that never changes the job outcome."""
        adapter = self._get_memory_adapter()
        if adapter is None:
            return
        settings = getattr(adapter, "settings", None)
        if settings is None or not getattr(settings, "auto_sync_runtime_jobs", False):
            return

        try:
            sync_result = self.sync_job_to_memory(job_id)
        except _RUNTIME_RECOVERABLE_EXCEPTIONS as exc:  # pragma: no cover - defensive boundary
            self._logger.warning("MemPalace sync failed for job %s: %s", job_id, exc)
            return

        if sync_result.get("success"):
            if sync_result.get("duplicate"):
                self._logger.info(
                    "MemPalace sync skipped duplicate for job %s (%s/%s)",
                    job_id,
                    sync_result.get("wing", ""),
                    sync_result.get("room", ""),
                )
            else:
                self._logger.info(
                    "MemPalace sync stored job %s in %s/%s",
                    job_id,
                    sync_result.get("wing", ""),
                    sync_result.get("room", ""),
                )
            return

        reason = sync_result.get("reason")
        if sync_result.get("available", True):
            self._logger.warning("MemPalace sync did not complete for job %s: %s", job_id, reason)


@lru_cache(maxsize=1)
def _get_writing_runtime_singleton() -> WritingRuntime:
    return WritingRuntime(
        database_path=_default_runtime_db_path(),
        autosave=True,
    )


def get_writing_runtime() -> WritingRuntime:
    """Get or create the global WritingRuntime instance."""
    return _get_writing_runtime_singleton()

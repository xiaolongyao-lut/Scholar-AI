# -*- coding: utf-8 -*-
"""Persistence regression tests for the writing runtime."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from harness_protocols import ArtifactType, EventType, JobKind, JobStatus, SessionMode
from routers import agent_bridge_router
from writing_runtime import WritingRuntime

pytestmark = pytest.mark.persistence_full


def test_add_job_artifact_attaches_metadata_artifact(tmp_path: Path) -> None:
    """Public runtime artifact writes should survive persistence reload."""
    db_path = tmp_path / "writing_runtime_artifact.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(mode=SessionMode.SKILL, user_id="runtime-user")
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="Export bundle manifest",
    )

    artifact = runtime.add_job_artifact(
        job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={"schema_version": "test_manifest_v1", "ok": True},
        created_by="test",
        metadata={"kind": "test_manifest"},
    )

    assert artifact.session_id == session.session_id
    assert artifact.metadata["kind"] == "test_manifest"
    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_artifacts = loaded_runtime.get_job_artifacts(job.job_id, ArtifactType.METADATA)
    assert [item.artifact_id for item in loaded_artifacts] == [artifact.artifact_id]
    assert loaded_artifacts[0].content["schema_version"] == "test_manifest_v1"


@pytest.mark.persistence_smoke
@pytest.mark.asyncio
async def test_runtime_persists_sessions_jobs_events_and_artifacts_across_instances(tmp_path: Path) -> None:
    """SQLite-backed runtime state should survive recreation of the runtime object."""
    db_path = tmp_path / "writing_runtime_state.sqlite3"

    first_runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = first_runtime.create_session(
        mode=SessionMode.SKILL,
        user_id="runtime-user",
        tags=["sqlite"],
    )
    job = first_runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="Persist this job",
        action_id="action-1",
    )

    await first_runtime.start_job(job.job_id)
    await first_runtime.complete_job(job.job_id, result="Persisted result")
    approval = first_runtime.request_approval(
        job_id=job.job_id,
        session_id=session.session_id,
        reason="Manual review",
    )

    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_session = second_runtime.get_session(session.session_id)
    loaded_job = second_runtime.get_job(job.job_id)
    loaded_events = second_runtime.get_job_events(job.job_id)
    loaded_artifacts = second_runtime.get_job_artifacts(job.job_id)
    loaded_approval = second_runtime.get_approval_request(approval.approval_id)

    assert loaded_session is not None
    assert loaded_session.session_id == session.session_id
    assert loaded_session.user_id == "runtime-user"

    assert loaded_job is not None
    assert loaded_job.job_id == job.job_id
    assert loaded_job.status == JobStatus.COMPLETED

    assert [event.event_type for event in loaded_events] == [
        EventType.JOB_CREATED,
        EventType.JOB_STARTED,
        EventType.JOB_COMPLETED,
        EventType.APPROVAL_REQUIRED,
    ]
    assert [event.sequence for event in loaded_events] == [1, 2, 3, 4]
    assert second_runtime.get_job_events(job.job_id, after_sequence=2)[0].event_type == EventType.JOB_COMPLETED
    assert second_runtime.get_job_event_head_sequence(job.job_id) == 4

    assert loaded_artifacts
    assert loaded_artifacts[0].artifact_type == ArtifactType.TRANSFORMED_TEXT
    assert loaded_artifacts[0].content == "Persisted result"

    assert loaded_approval is not None
    assert loaded_approval.approval_id == approval.approval_id
    assert loaded_approval.reason == "Manual review"
    assert loaded_approval.status.value == "pending"


@pytest.mark.persistence_smoke
@pytest.mark.asyncio
async def test_runtime_import_backfills_missing_event_sequences() -> None:
    """Serialized pre-S9 runtime events without sequence values should remain cursor-safe."""
    first_runtime = WritingRuntime()
    session = first_runtime.create_session(mode=SessionMode.SKILL)
    job = first_runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="legacy sequence import",
    )
    await first_runtime.start_job(job.job_id)
    await first_runtime.complete_job(job.job_id, result="done")

    legacy_state = first_runtime.export_state()
    for event_list in legacy_state["events"].values():
        for event_payload in event_list:
            event_payload.pop("sequence", None)

    restored_runtime = WritingRuntime()
    restored_runtime.import_state(legacy_state)

    restored_events = restored_runtime.get_job_events(job.job_id)
    assert [event.sequence for event in restored_events] == [1, 2, 3]
    assert [event.event_type for event in restored_runtime.get_job_events(job.job_id, after_sequence=1)] == [
        EventType.JOB_STARTED,
        EventType.JOB_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_runtime_import_preserves_resource_ingest_and_tolerates_unknown_kind() -> None:
    """Runtime state import must load new known kinds and degrade unknown future kinds."""

    runtime = WritingRuntime()
    session = runtime.create_session(mode=SessionMode.PROMPT)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="scan folder",
        metadata={"project_id": "project-1"},
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result={"kind": "resource_ingest", "indexed": 1})
    state = runtime.export_state()

    unknown_job = dict(state["jobs"][job.job_id])
    unknown_job["job_id"] = "job_unknown_kind"
    unknown_job["kind"] = "future_kind"
    unknown_job["metadata"] = {"project_id": "future-project"}
    state["jobs"][unknown_job["job_id"]] = unknown_job
    state["job_queue"].append(unknown_job["job_id"])

    restored_runtime = WritingRuntime()
    restored_runtime.import_state(state)

    loaded_resource_job = restored_runtime.get_job(job.job_id)
    loaded_unknown_job = restored_runtime.get_job("job_unknown_kind")
    assert loaded_resource_job is not None
    assert loaded_resource_job.kind == JobKind.RESOURCE_INGEST
    assert loaded_unknown_job is not None
    assert loaded_unknown_job.kind == JobKind.PROMPT_ACTION
    assert loaded_unknown_job.metadata["unknown_job_kind"] == "future_kind"


@pytest.mark.asyncio
async def test_writing_workflow_state_persists_as_job_metadata_event_and_artifact(tmp_path: Path) -> None:
    """Writing workflow state should survive resume without parsing chat prose."""

    db_path = tmp_path / "writing_runtime_state.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(mode=SessionMode.SKILL, user_id="workflow-user")
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="Draft an evidence-grounded introduction",
        metadata={"project_id": "project-1"},
    )

    state = runtime.update_writing_workflow_state(
        job_id=job.job_id,
        phase="evidence_bound_draft",
        intake={
            "task_type": "review_introduction",
            "target_venue": "Journal of Additive Manufacturing Letters",
            "language": "zh",
        },
        evidence_refs=[
            {
                "ref_id": "chunk:alsi10mg-defects",
                "claim": "LPBF AlSi10Mg fatigue failures are linked to lack-of-fusion pores.",
                "support_status": "supported",
            }
        ],
        citation_bank=[
            {
                "citation_id": "cite:defects-2026",
                "ref_id": "chunk:alsi10mg-defects",
                "locator": "p.4",
            }
        ],
        lint_report={
            "passed": True,
            "score": 91,
            "checks": ["evidence_refs", "journal_style_profile"],
        },
        export_manifest={
            "format": "docx",
            "artifact_path": "workspace_artifacts/generated/output/review.docx",
            "style_profile": "custom_journal_of_additive_manufacturing_letters",
        },
        change_log=[
            {
                "stage": "evidence",
                "summary": "Bound the introduction claim to a chunk ref.",
            }
        ],
    )

    assert state["phase"] == "evidence_bound_draft"
    assert state["readiness"]["has_evidence_refs"] is True
    assert state["readiness"]["has_citation_bank"] is True
    assert state["readiness"]["has_lint_report"] is True
    assert state["readiness"]["has_export_manifest"] is True
    assert state["evidence_refs"][0]["ref_id"] == "chunk:alsi10mg-defects"

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_state = loaded_runtime.get_writing_workflow_state(job.job_id)
    loaded_job = loaded_runtime.get_job(job.job_id)
    loaded_events = loaded_runtime.get_job_events(job.job_id)
    loaded_artifacts = loaded_runtime.get_job_artifacts(job.job_id, ArtifactType.METADATA)

    assert loaded_job is not None
    assert loaded_job.metadata["writing_workflow_state"]["phase"] == "evidence_bound_draft"
    assert loaded_state == loaded_job.metadata["writing_workflow_state"]
    assert any(event.data.get("workflow_phase") == "evidence_bound_draft" for event in loaded_events)
    assert any(
        isinstance(artifact.content, dict)
        and artifact.content.get("kind") == "writing_workflow_state"
        and artifact.content.get("state", {}).get("phase") == "evidence_bound_draft"
        for artifact in loaded_artifacts
    )


@pytest.mark.asyncio
async def test_material_processing_task_persists_as_job_metadata_event_and_artifact(tmp_path: Path) -> None:
    """Material-processing tasks should persist explicit request/cache/result contracts."""

    db_path = tmp_path / "writing_runtime_material_processing.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(mode=SessionMode.PROMPT, user_id="material-user")
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="Process uploaded PDF",
        metadata={"project_id": "project-material-contract"},
    )

    task = runtime.update_material_processing_task(
        job.job_id,
        request={
            "schema_version": "material_processing_task_v1",
            "project_id": "project-material-contract",
            "material_id": "material-contract",
            "input_ref": {
                "ref_type": "uploaded_source_file",
                "material_id": "material-contract",
                "source_path_label": "paper.pdf",
                "content_digest": "sha256:abc123",
                "size_bytes": 12345,
            },
            "page_range": {"mode": "pages", "pages": [3, 1, 3]},
            "processing_mode": "fast_text",
            "cache": {"policy": "use", "content_digest": "sha256:abc123"},
            "output_targets": ["chunks", "locators", "text_sidecar"],
            "metadata": {"source": "pytest"},
        },
        status="queued",
        provenance={"source": "pytest.request"},
    )

    assert task["request"]["page_range"]["pages"] == [1, 3]
    assert task["cache"]["content_digest"] == "sha256:abc123"
    assert task["cache"]["parameter_digest"].startswith("sha256:")
    assert task["cache"]["cache_key"].startswith("material_processing:sha256:abc123:sha256:")

    updated = runtime.record_material_processing_task_result(
        job.job_id,
        status="completed",
        result={"status": "completed", "chunks": 4, "content_length": 2048},
        artifacts=[
            {
                "artifact_type": "chunk_index",
                "output_target": "chunks",
                "count": 4,
                "metadata": {"chunk_count": 4},
            },
            {
                "artifact_type": "extracted_text_record",
                "output_target": "text_sidecar",
                "count": 1,
                "metadata": {"content_length": 2048},
            },
        ],
        cache_decision="miss",
        provenance={"source": "pytest.result"},
    )

    assert updated["status"] == "completed"
    assert updated["cache"]["decision"] == "miss"
    assert updated["result"]["chunks"] == 4

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_task = loaded_runtime.get_material_processing_task(job.job_id)
    loaded_job = loaded_runtime.get_job(job.job_id)
    loaded_events = loaded_runtime.get_job_events(job.job_id)
    loaded_artifacts = loaded_runtime.get_job_artifacts(job.job_id, ArtifactType.METADATA)

    assert loaded_job is not None
    assert loaded_task == loaded_job.metadata["material_processing_task"]
    assert loaded_task["request"]["output_targets"] == ["chunks", "locators", "text_sidecar"]
    assert loaded_task["artifacts"][0]["artifact_type"] == "chunk_index"
    assert any(event.data.get("material_processing_status") == "completed" for event in loaded_events)
    assert any(
        isinstance(artifact.content, dict)
        and artifact.content.get("kind") == "material_processing_task"
        and artifact.content.get("state", {}).get("status") == "completed"
        for artifact in loaded_artifacts
    )


@pytest.mark.asyncio
async def test_research_projection_rebuilds_from_persisted_runtime_state(tmp_path: Path) -> None:
    """Research object/event projections should remain reproducible after SQLite reload."""

    db_path = tmp_path / "writing_runtime_projection.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="projection-user",
        metadata={"project_id": "project-persisted-projection", "title": "Persisted Projection"},
    )
    material_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="ingest project material",
        metadata={
            "project_id": "project-persisted-projection",
            "material_id": "material-persisted",
            "title": "Persisted paper.pdf",
            "source_path": "workspace_artifacts/input/persisted.pdf",
        },
    )
    await runtime.start_job(material_job.job_id)
    await runtime.complete_job(material_job.job_id, result={"kind": "resource_ingest", "indexed": 1})

    evidence_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SMART_READ,
        input_text="build persisted evidence pack",
        metadata={
            "project_id": "project-persisted-projection",
            "material_id": "material-persisted",
            "evidence_pack_id": "pack-persisted",
            "task_type": "evidence_pack_build",
        },
    )
    runtime.add_job_artifact(
        evidence_job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={"kind": "evidence_pack", "claims": 2},
        created_by="pytest",
        metadata={"evidence_pack_id": "pack-persisted", "project_id": "project-persisted-projection"},
    )
    await runtime.start_job(evidence_job.job_id)
    await runtime.complete_job(evidence_job.job_id, result={"kind": "evidence_pack", "pack_id": "pack-persisted"})

    agent_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="prepare synthesis",
        metadata={
            "project_id": "project-persisted-projection",
            "agent_request_id": "agent-persisted",
            "material_id": "material-persisted",
        },
    )
    approval = runtime.request_approval(
        job_id=agent_job.job_id,
        session_id=session.session_id,
        reason="Confirm persisted synthesis.",
        metadata={"project_id": "project-persisted-projection"},
    )

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    projection = loaded_runtime.build_research_projection(project_id="project-persisted-projection", limit=50)

    object_by_id = {item["object_id"]: item for item in projection["objects"]}
    assert object_by_id["research_project:project-persisted-projection"]["title"] == "Persisted Projection"
    assert object_by_id["research_material:material-persisted"]["status"] == "completed"
    assert object_by_id["evidence_pack:pack-persisted"]["object_type"] == "evidence_pack"
    assert object_by_id["agent_request:agent-persisted"]["confirmation_boundary"]["pending_approval_count"] == 1
    assert object_by_id[f"approval_gate:{approval.approval_id}"]["confirmation_boundary"][
        "requires_user_confirmation"
    ] is True
    assert projection["status_projection"]["effect_counts"]["jobs"] == 3
    assert projection["status_projection"]["pending_approval_count"] == 1
    assert {"material.ingest.completed", "evidence.pack.created", "approval.required"} <= {
        event["event_type"] for event in projection["events"]
    }


@pytest.mark.asyncio
async def test_workflow_passport_rebuilds_from_persisted_runtime_state(tmp_path: Path) -> None:
    """Workflow passports should remain reproducible after SQLite reload."""

    db_path = tmp_path / "writing_runtime_workflow_passport.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="passport-persisted-user",
        metadata={"project_id": "project-persisted-passport", "title": "Persisted Passport"},
    )
    material_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="ingest persisted material",
        metadata={"project_id": "project-persisted-passport", "material_id": "material-persisted-passport"},
    )
    runtime.update_material_processing_task(
        material_job.job_id,
        request={
            "schema_version": "material_processing_task_v1",
            "project_id": "project-persisted-passport",
            "material_id": "material-persisted-passport",
            "input_ref": {
                "ref_type": "uploaded_source_file",
                "material_id": "material-persisted-passport",
                "content_digest": "sha256:persisted-passport",
            },
            "processing_mode": "fast_text",
            "cache": {
                "policy": "use",
                "content_digest": "sha256:persisted-passport",
                "decision": "hit",
            },
            "output_targets": ["chunks", "locators", "text_sidecar"],
        },
        status="completed",
        result={"chunks": 3},
        artifacts=[
            {"artifact_type": "chunk_index", "output_target": "chunks", "count": 3},
            {"artifact_type": "locator_index", "output_target": "locators", "count": 3},
        ],
        provenance={"source": "pytest.persisted"},
    )
    await runtime.start_job(material_job.job_id)
    await runtime.complete_job(material_job.job_id, result={"kind": "resource_ingest"})

    writing_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="persisted export",
        metadata={"project_id": "project-persisted-passport", "export_artifact_id": "export-persisted-passport"},
    )
    runtime.update_writing_workflow_state(
        writing_job.job_id,
        phase="export_ready",
        intake={"project_id": "project-persisted-passport"},
        evidence_refs=[{"ref_id": "chunk:persisted"}],
        citation_bank=[{"citation_id": "cite:persisted"}],
        lint_report={"passed": True},
        export_manifest={"format": "docx", "filename": "persisted.docx"},
        change_log=[{"stage": "export", "summary": "ready"}],
    )
    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=writing_job.job_id,
        project_id="project-persisted-passport",
        require_ready=False,
        persist_refresh_receipt=True,
    )

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    passport = loaded_runtime.build_workflow_passport(project_id="project-persisted-passport", limit=50)

    stage_by_id = {stage["stage_id"]: stage for stage in passport["stages"]}
    assert passport["schema_version"] == "scholar_ai_workflow_passport_v1"
    assert passport["scope"]["project_id"] == "project-persisted-passport"
    assert stage_by_id["material_ingest"]["status"] == "complete"
    assert stage_by_id["material_ingest"]["gate"]["status"] == "pass"
    assert stage_by_id["draft"]["gate"]["status"] == "pass"
    assert stage_by_id["citation_review"]["gate"]["status"] == "pass"
    assert stage_by_id["export"]["gate"]["status"] == "unresolved"
    ingest_repro = stage_by_id["material_ingest"]["reproducibility"]
    assert ingest_repro["read_only"] is True
    assert ingest_repro["parameter_digest_count"] == 1
    assert ingest_repro["cache_key_count"] == 1
    assert ingest_repro["cache_refs"][0]["decision"] == "hit"
    assert ingest_repro["cache_refs"][0]["parameter_digest"].startswith("sha256:")
    assert stage_by_id["material_read"]["diagnostics"]["artifact_count"] >= 2
    assert {
        item["output_target"]
        for item in stage_by_id["material_read"]["reproducibility"]["artifact_refs"]
        if "output_target" in item
    } >= {"chunks", "locators"}
    export_repro = stage_by_id["export"]["reproducibility"]
    assert export_repro["preflight_receipts"][0]["ref_id"] == preflight["refresh_receipt_id"]
    assert "workflow_passport" in export_repro["projection_digest_keys"]
    assert any(
        probe["endpoint"] == f"/runtime/job/{writing_job.job_id}/workflow-replay-lineage"
        for probe in export_repro["replay_probe_refs"]
    )
    export_gate = stage_by_id["export"]["gate"]
    assert any("preflight unresolved check" in item for item in export_gate["unresolved"])
    gate = loaded_runtime.build_evidence_integrity_gate(project_id="project-persisted-passport")
    export_signal = next(
        signal
        for signal in gate["signals"]
        if signal["signal_id"] == "workflow_stage:export"
    )
    assert export_signal["status"] == "unresolved"
    assert export_signal["drilldown"]["source_ref"]["source_kind"] == "workflow_passport_stage"
    assert export_signal["drilldown"]["checked_facts"]["stage_id"] == "export"
    assert export_signal["drilldown"]["checked_facts"]["preflight_receipt_count"] == 1
    assert export_signal["drilldown"]["checked_facts"]["unresolved_count"] >= 1
    assert any(
        ref.get("ref_type") == "preflight_refresh_receipt"
        for ref in export_signal["drilldown"]["replay_refs"]
    )
    assert passport["provenance"]["object_count"] >= 2


@pytest.mark.asyncio
async def test_workflow_passport_does_not_mark_material_read_from_material_identity_only(tmp_path: Path) -> None:
    """Material read requires locator/chunk evidence, not only a material id."""

    runtime = WritingRuntime(database_path=tmp_path / "workflow_passport_material_only.sqlite3", autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="passport-material-only-user",
        metadata={"project_id": "project-material-only"},
    )
    material_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="created but not processed",
        metadata={"project_id": "project-material-only", "material_id": "material-only"},
    )
    await runtime.start_job(material_job.job_id)

    passport = runtime.build_workflow_passport(project_id="project-material-only", limit=50)

    stage_by_id = {stage["stage_id"]: stage for stage in passport["stages"]}
    assert stage_by_id["material_ingest"]["status"] == "in_progress"
    assert stage_by_id["material_ingest"]["gate"]["status"] == "unresolved"
    assert stage_by_id["material_read"]["status"] == "not_started"
    assert stage_by_id["material_read"]["gate"]["status"] == "not_applicable"


@pytest.mark.asyncio
async def test_evidence_integrity_gate_blocks_unsupported_and_keeps_unresolved_visible(tmp_path: Path) -> None:
    """Integrity gate must not render missing/offline checks as passed."""

    db_path = tmp_path / "evidence_integrity_gate.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="integrity-user",
        metadata={"project_id": "project-integrity", "title": "Integrity Project"},
    )
    material_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        input_text="ingest material without locators",
        metadata={"project_id": "project-integrity", "material_id": "material-integrity"},
    )
    await runtime.start_job(material_job.job_id)
    await runtime.complete_job(material_job.job_id, result={"kind": "resource_ingest"})

    writing_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export evidence-bound draft",
        metadata={"project_id": "project-integrity", "export_artifact_id": "export-integrity"},
    )
    runtime.update_writing_workflow_state(
        writing_job.job_id,
        phase="export_ready",
        intake={"project_id": "project-integrity"},
        evidence_refs=[{"ref_id": "chunk:missing-locator", "claim": "Unsupported claim"}],
        citation_bank=[{"citation_id": "cite:unsupported", "ref_id": "chunk:missing-locator"}],
        lint_report={
            "passed": False,
            "score": 65,
            "issues": [
                {
                    "code": "missing_evidence_refs",
                    "severity": "error",
                    "message": "Evidence refs are missing.",
                }
            ],
        },
        export_manifest={"format": "docx", "filename": "integrity.docx"},
        change_log=[{"stage": "export", "summary": "ready"}],
    )
    runtime.add_job_artifact(
        writing_job.job_id,
        artifact_type=ArtifactType.METADATA,
        content={
            "kind": "integrity_diagnostics",
            "retrieval_diagnostics": {
                "locator_coverage": {
                    "schema_version": "scholar-ai-evidence-locator-coverage/v1",
                    "total_refs": 1,
                    "project_ref_count": 1,
                    "non_project_ref_count": 0,
                    "material_locator_count": 0,
                    "page_locator_count": 0,
                    "bbox_locator_count": 0,
                    "missing_locator_count": 1,
                    "page_coverage_ratio": 0.0,
                    "bbox_coverage_ratio": 0.0,
                    "coverage_state": "missing",
                    "risk_level": "block",
                    "sample_missing_ref_ids": ["chunk:missing-locator"],
                    "notes": ["No page locator is available."],
                },
                "qrels_status": {
                    "schema_version": "retrieval-qrels-status/v1",
                    "status": "candidate",
                    "candidate_qrels_count": 2,
                    "reviewed_qrels_count": 0,
                    "canonical_qrels_count": 0,
                    "semantic_quality_claim_allowed": False,
                    "quality_claim": "candidate_qrels_review_required",
                    "notes": ["Candidate qrels require review."],
                },
            },
            "citation_verifications": [
                {
                    "verification_id": "verify-unsupported",
                    "project_id": "project-integrity",
                    "citation_id": "cite:unsupported",
                    "status": "unsupported",
                    "rationale": "Claim and evidence do not overlap.",
                    "source_kind": "local",
                    "source_labels": ["local-pdf"],
                },
                {
                    "verification_id": "verify-needs-review",
                    "project_id": "project-integrity",
                    "citation_id": "cite:needs-review",
                    "status": "needs_review",
                    "rationale": "Offline source requires human review.",
                    "source_kind": "local",
                },
            ],
        },
        created_by="pytest",
        metadata={"project_id": "project-integrity"},
    )

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    gate = loaded_runtime.build_evidence_integrity_gate(project_id="project-integrity", limit=50)

    assert gate["schema_version"] == "scholar_ai_evidence_integrity_gate_v1"
    assert gate["status"] == "block"
    assert gate["summary"]["unresolved_is_pass"] is False
    signals = {signal["signal_id"]: signal for signal in gate["signals"]}
    assert any(
        signal["category"] == "locator" and signal["status"] == "block"
        for signal in signals.values()
    )
    locator_signal = next(
        signal
        for signal in signals.values()
        if signal["category"] == "locator" and signal["status"] == "block"
    )
    locator_drilldown = locator_signal["drilldown"]
    assert locator_drilldown["schema_version"] == "scholar_ai_integrity_signal_drilldown_v1"
    assert locator_drilldown["source_ref"]["source_kind"] == "locator_coverage"
    assert locator_drilldown["source_ref"]["source_digest"].startswith("sha256:")
    assert locator_drilldown["source_ref"]["raw_path_exposed"] is False
    assert locator_drilldown["checked_facts"]["missing_locator_count"] == 1
    assert locator_drilldown["checked_facts"]["coverage_state"] == "missing"
    assert locator_drilldown["evidence_refs"][0]["ref_type"] == "locator_coverage"
    assert locator_drilldown["blocks_claims"] is True
    assert any(
        signal["category"] == "citation_verification" and signal["status"] == "block"
        for signal in signals.values()
    )
    citation_block = next(
        signal
        for signal in signals.values()
        if signal["category"] == "citation_verification" and signal["status"] == "block"
    )
    assert citation_block["drilldown"]["checked_facts"]["citation_id"] == "cite:unsupported"
    assert citation_block["drilldown"]["blocks_claims"] is True
    assert any(
        signal["category"] == "citation_verification" and signal["status"] == "unresolved"
        for signal in signals.values()
    )
    citation_unresolved = next(
        signal
        for signal in signals.values()
        if signal["category"] == "citation_verification" and signal["status"] == "unresolved"
    )
    assert citation_unresolved["drilldown"]["requires_human_review"] is True
    assert any(
        signal["category"] == "retrieval_quality" and signal["status"] == "unresolved"
        for signal in signals.values()
    )
    retrieval_signal = next(
        signal
        for signal in signals.values()
        if signal["category"] == "retrieval_quality" and signal["status"] == "unresolved"
    )
    assert retrieval_signal["drilldown"]["checked_facts"]["semantic_quality_claim_allowed"] is False
    assert any(
        signal["category"] == "writing_lint" and signal["status"] == "block"
        for signal in signals.values()
    )
    lint_signal = next(
        signal
        for signal in signals.values()
        if signal["category"] == "writing_lint" and signal["status"] == "block"
    )
    assert lint_signal["drilldown"]["checked_facts"]["issue_count"] == 1
    assert gate["summary"]["status_counts"]["block"] >= 3
    assert gate["summary"]["status_counts"]["unresolved"] >= 2
    assert gate["blockers"]
    assert gate["unresolved"]
    assert gate["enforcement"]["schema_version"] == "scholar_ai_workflow_enforcement_v1"
    export_claim = next(
        claim
        for claim in gate["enforcement"]["claims"]
        if claim["claim_id"] == "export_readiness"
    )
    assert export_claim["status"] == "blocked"
    assert export_claim["blockers"]
    assert gate["enforcement"]["summary"]["unresolved_is_ready"] is False
    serialized = str(gate)
    assert "C:\\Users\\xiao\\private" not in serialized
    assert "workspace_artifacts/private" not in serialized


@pytest.mark.persistence_smoke
def test_writing_readiness_claims_do_not_treat_export_ready_as_ready_without_integrity(tmp_path: Path) -> None:
    """Legacy export_ready phase remains persisted, but gate-derived claims block readiness."""

    db_path = tmp_path / "readiness_claims.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-readiness-claims"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export paper",
        metadata={"project_id": "project-readiness-claims"},
    )
    state = runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-readiness-claims"},
        evidence_refs=[{"ref_id": "chunk:claim"}],
        citation_bank=[{"citation_id": "cite:claim"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "claim.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )

    assert state["phase"] == "export_ready"
    assert state["readiness"]["has_export_manifest"] is True

    claims = runtime.build_writing_readiness_claims(job.job_id)
    export_claim = next(
        claim
        for claim in claims["claims"]
        if claim["claim_id"] == "export_readiness"
    )

    assert claims["schema_version"] == "scholar_ai_workflow_enforcement_v1"
    assert export_claim["status"] == "unresolved"
    assert export_claim["source_gate_status"] == "unresolved"
    assert export_claim["unresolved"]
    assert claims["summary"]["unresolved_is_ready"] is False


@pytest.mark.persistence_smoke
def test_action_preflight_requires_refresh_for_stale_workflow_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Command preflight should block stale gate snapshots before export actions."""

    import writing_runtime as writing_runtime_module

    db_path = tmp_path / "action_preflight_freshness.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-preflight-freshness"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export stale paper",
        metadata={"project_id": "project-preflight-freshness"},
    )
    monkeypatch.setattr(writing_runtime_module, "utc_now_iso_z", lambda: "2026-06-21T00:00:00Z")
    state = runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-preflight-freshness"},
        evidence_refs=[{"ref_id": "chunk:freshness", "material_id": "material-freshness"}],
        citation_bank=[{"citation_id": "cite:freshness", "ref_id": "chunk:freshness"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "freshness.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )

    monkeypatch.setattr(writing_runtime_module, "utc_now_iso_z", lambda: "2026-06-21T00:30:01Z")
    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-preflight-freshness",
        require_ready=True,
        workflow_state=state,
    )

    assert preflight["schema_version"] == "scholar_ai_action_preflight_v1"
    assert preflight["freshness"]["schema_version"] == "scholar_ai_action_preflight_freshness_v1"
    assert preflight["freshness"]["status"] == "stale"
    assert preflight["freshness"]["refresh_required"] is True
    assert preflight["refresh_required"] is True
    assert preflight["can_proceed"] is False
    assert preflight["summary"]["refresh_required"] is True
    assert preflight["summary"]["freshness_status"] == "stale"
    assert any("exceeding" in item for item in preflight["unresolved"])
    assert any(action.startswith("Rebuild the Workflow Passport") for action in preflight["freshness"]["refresh_actions"])


@pytest.mark.persistence_smoke
def test_action_preflight_persists_refresh_receipt_for_replay_evidence(tmp_path: Path) -> None:
    """Action preflight refresh should leave a bounded replay receipt."""

    db_path = tmp_path / "action_preflight_refresh_receipt.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-refresh-receipt"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export receipt paper",
        metadata={"project_id": "project-refresh-receipt"},
    )
    state = runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-refresh-receipt"},
        evidence_refs=[{"ref_id": "chunk:receipt", "material_id": "material-receipt"}],
        citation_bank=[{"citation_id": "cite:receipt", "ref_id": "chunk:receipt"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "receipt.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )

    preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-refresh-receipt",
        require_ready=False,
        workflow_state=state,
        persist_refresh_receipt=True,
    )

    receipt = preflight["refresh_receipt"]
    assert receipt["schema_version"] == "scholar_ai_preflight_refresh_receipt_v1"
    assert receipt["action_id"] == "writing.export_project"
    assert receipt["scope"]["project_id"] == "project-refresh-receipt"
    assert receipt["status"] in {"ready", "blocked", "unresolved", "stale"}
    assert receipt["validation"]["passport_schema_version"] == "scholar_ai_workflow_passport_v1"
    assert receipt["validation"]["evidence_integrity_gate_schema_version"] == "scholar_ai_evidence_integrity_gate_v1"
    assert receipt["validation"]["preflight_schema_version"] == "scholar_ai_action_preflight_v1"
    assert receipt["projection_digests"]["workflow_passport"].startswith("sha256:")
    assert receipt["projection_digests"]["evidence_integrity_gate"].startswith("sha256:")
    assert preflight["refresh_receipt_id"] == receipt["receipt_id"]
    assert any(item.get("ref_type") == "preflight_refresh_receipt" for item in preflight["evidence"])

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_job = loaded_runtime.get_job(job.job_id)
    assert loaded_job is not None
    assert loaded_job.metadata["preflight_refresh_receipts"][-1]["receipt_id"] == receipt["receipt_id"]
    receipt_artifacts = [
        artifact
        for artifact in loaded_runtime.get_job_artifacts(job.job_id, ArtifactType.METADATA)
        if artifact.metadata.get("kind") == "preflight_refresh_receipt"
    ]
    assert receipt_artifacts
    assert receipt_artifacts[-1].content["receipt_id"] == receipt["receipt_id"]


@pytest.mark.persistence_smoke
def test_workflow_replay_lineage_compares_persisted_refresh_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Replay lineage should summarize receipt history without mutating runtime state."""

    import writing_runtime as writing_runtime_module

    db_path = tmp_path / "workflow_replay_lineage.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-replay-lineage"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export lineage paper",
        metadata={"project_id": "project-replay-lineage"},
    )
    state = runtime.update_writing_workflow_state(
        job.job_id,
        phase="export_ready",
        intake={"project_id": "project-replay-lineage"},
        evidence_refs=[{"ref_id": "chunk:lineage", "material_id": "material-lineage"}],
        citation_bank=[{"citation_id": "cite:lineage", "ref_id": "chunk:lineage"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "lineage.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )

    monkeypatch.setattr(writing_runtime_module, "utc_now_iso_z", lambda: "2026-06-22T00:00:00Z")
    first_preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=job.job_id,
        project_id="project-replay-lineage",
        require_ready=False,
        workflow_state=state,
        persist_refresh_receipt=True,
    )
    first_receipt = dict(first_preflight["refresh_receipt"])
    second_receipt = {
        **first_receipt,
        "receipt_id": "preflight_refresh:manual-second",
        "generated_at": "2026-06-22T00:05:00Z",
        "status": "blocked",
        "can_proceed": False,
        "validation": {
            **dict(first_receipt["validation"]),
            "blocker_count": 2,
            "unresolved_count": 1,
        },
        "projection_digests": {
            **dict(first_receipt["projection_digests"]),
            "evidence_integrity_gate": "sha256:changed-gate",
        },
    }
    runtime.persist_preflight_refresh_receipt(job.job_id, second_receipt)

    lineage = runtime.build_workflow_replay_lineage(job.job_id)

    assert lineage["schema_version"] == "scholar_ai_workflow_replay_lineage_v1"
    assert lineage["job_id"] == job.job_id
    assert lineage["project_id"] == "project-replay-lineage"
    assert lineage["receipt_count"] == 2
    assert lineage["returned_count"] == 2
    assert lineage["latest_receipt_id"] == "preflight_refresh:manual-second"
    assert lineage["latest"]["status"] == "blocked"
    assert lineage["previous"]["receipt_id"] == first_receipt["receipt_id"]
    assert lineage["comparison"]["status_changed"] is True
    assert lineage["comparison"]["blocker_count_delta"] == 2 - first_receipt["validation"]["blocker_count"]
    assert "evidence_integrity_gate" in lineage["comparison"]["changed_digest_keys"]
    assert lineage["summary"]["lineage_is_read_only"] is True
    assert any(probe["endpoint"].endswith("/workflow-replay-lineage") for probe in lineage["resume_probes"])
    assert any("blocking checks" in message for message in lineage["blockers"])

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_lineage = loaded_runtime.build_workflow_replay_lineage(job.job_id)
    assert loaded_lineage["latest_receipt_id"] == "preflight_refresh:manual-second"
    assert loaded_lineage["summary"]["artifact_receipt_count"] >= 2


@pytest.mark.persistence_smoke
def test_workflow_replay_index_discovers_blocked_receipts_without_job_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Replay index should recover blocked attempts across jobs without mutation."""

    import writing_runtime as writing_runtime_module

    db_path = tmp_path / "workflow_replay_index.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-replay-index", "title": "Replay Index Project"},
    )
    export_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="export replay index",
        metadata={"project_id": "project-replay-index"},
    )
    handoff_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="handoff replay index",
        metadata={"project_id": "project-replay-index"},
    )
    other_session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-other-index"},
    )
    other_job = runtime.create_job(
        session_id=other_session.session_id,
        kind=JobKind.ARTIFACT_EXPORT,
        input_text="other export",
        metadata={"project_id": "project-other-index"},
    )
    state = runtime.update_writing_workflow_state(
        export_job.job_id,
        phase="export_ready",
        intake={"project_id": "project-replay-index"},
        evidence_refs=[{"ref_id": "chunk:index", "material_id": "material-index"}],
        citation_bank=[{"citation_id": "cite:index", "ref_id": "chunk:index"}],
        lint_report={"passed": True, "issues": []},
        export_manifest={"format": "docx", "filename": "index.docx"},
        change_log=[{"stage": "export", "summary": "export manifest exists"}],
    )

    monkeypatch.setattr(writing_runtime_module, "utc_now_iso_z", lambda: "2026-06-22T00:10:00Z")
    first_preflight = runtime.build_action_preflight(
        action_id="writing.export_project",
        required_claim_id="export_readiness",
        session_id=session.session_id,
        job_id=export_job.job_id,
        project_id="project-replay-index",
        require_ready=False,
        workflow_state=state,
        persist_refresh_receipt=True,
    )
    blocked_receipt = {
        **dict(first_preflight["refresh_receipt"]),
        "receipt_id": "preflight_refresh:index-blocked",
        "generated_at": "2026-06-22T00:15:00Z",
        "status": "blocked",
        "can_proceed": False,
        "validation": {
            **dict(first_preflight["refresh_receipt"]["validation"]),
            "blocker_count": 3,
            "unresolved_count": 1,
        },
        "projection_digests": {
            **dict(first_preflight["refresh_receipt"]["projection_digests"]),
            "evidence_integrity_gate": "sha256:index-blocked",
        },
    }
    runtime.persist_preflight_refresh_receipt(export_job.job_id, blocked_receipt)

    handoff_receipt = {
        **blocked_receipt,
        "receipt_id": "preflight_refresh:index-handoff-unresolved",
        "generated_at": "2026-06-22T00:11:00Z",
        "action_id": "agent.handoff_card",
        "required_claim_id": "handoff_readiness",
        "status": "unresolved",
        "validation": {
            **dict(blocked_receipt["validation"]),
            "blocker_count": 0,
            "unresolved_count": 2,
        },
    }
    runtime.persist_preflight_refresh_receipt(handoff_job.job_id, handoff_receipt)
    other_receipt = {
        **blocked_receipt,
        "receipt_id": "preflight_refresh:index-other-ready",
        "generated_at": "2026-06-22T00:12:00Z",
        "scope": {"project_id": "project-other-index", "job_id": other_job.job_id, "session_id": other_session.session_id},
        "status": "ready",
        "can_proceed": True,
        "validation": {**dict(blocked_receipt["validation"]), "blocker_count": 0, "unresolved_count": 0},
    }
    runtime.persist_preflight_refresh_receipt(other_job.job_id, other_receipt)
    job_count_before = len(runtime._jobs)
    artifact_count_before = sum(len(items) for items in runtime._artifacts.values())

    replay_index = runtime.build_workflow_replay_index(project_id="project-replay-index", limit=10)

    assert replay_index["schema_version"] == "scholar_ai_workflow_replay_index_v1"
    assert replay_index["scope"]["project_id"] == "project-replay-index"
    assert replay_index["matching_job_count"] == 2
    assert replay_index["returned_count"] == 2
    assert replay_index["summary"]["requires_exact_job_id"] is False
    assert replay_index["summary"]["index_is_read_only"] is True
    assert replay_index["summary"]["blocked_job_count"] == 1
    assert replay_index["items"][0]["job_id"] == export_job.job_id
    assert replay_index["items"][0]["latest_status"] == "blocked"
    assert replay_index["items"][0]["latest_blocker_count"] == 3
    assert any(probe["endpoint"] == f"/runtime/job/{export_job.job_id}/workflow-replay-lineage" for probe in replay_index["items"][0]["resume_probes"])
    assert all(item["project_id"] == "project-replay-index" for item in replay_index["items"])
    assert len(runtime._jobs) == job_count_before
    assert sum(len(items) for items in runtime._artifacts.values()) == artifact_count_before

    unresolved_index = runtime.build_workflow_replay_index(
        session_id=session.session_id,
        status="unresolved",
        action_id="agent.handoff_card",
        limit=5,
    )
    assert unresolved_index["matching_job_count"] == 1
    assert unresolved_index["items"][0]["job_id"] == handoff_job.job_id
    assert unresolved_index["items"][0]["latest_required_claim_id"] == "handoff_readiness"

    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_index = loaded_runtime.build_workflow_replay_index(project_id="project-replay-index", limit=10)
    assert loaded_index["matching_job_count"] == 2
    assert loaded_index["items"][0]["latest_receipt_id"] == "preflight_refresh:index-blocked"


@pytest.mark.asyncio
async def test_agent_handoff_card_persists_resume_metadata_and_artifact(tmp_path: Path) -> None:
    """Agent handoff cards should survive runtime reload as metadata and artifact."""

    db_path = tmp_path / "agent_handoff_card.sqlite3"
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        user_id="handoff-user",
        metadata={"project_id": "project-handoff", "title": "Handoff Project"},
    )
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="read this paper",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq_persisted",
            "agent_host": "codex",
            "intent": "single_paper_deep_read",
            "project_id": "project-handoff",
            "resource_refs": [
                {
                    "ref_id": "material:handoff",
                    "kind": "material",
                    "project_id": "project-handoff",
                    "read_endpoint": "/api/agent-bridge/resource/material:handoff",
                }
            ],
        },
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(
        job.job_id,
        result={"kind": "agent_result", "text": "done", "request_id": "agentreq_persisted"},
        artifact_metadata={"agent_request_id": "agentreq_persisted"},
    )

    card = runtime.build_agent_handoff_card(job.job_id, persist=True)

    assert card["request_id"] == "agentreq_persisted"
    assert card["action_preflight"]["refresh_receipt"]["schema_version"] == "scholar_ai_preflight_refresh_receipt_v1"
    assert card["action_preflight"]["refresh_receipt_id"] == card["action_preflight"]["refresh_receipt"]["receipt_id"]
    assert card["replay_recovery"]["schema_version"] == "scholar_ai_agent_handoff_replay_recovery_v1"
    assert card["replay_recovery"]["current_receipt"]["receipt_id"] == card["action_preflight"]["refresh_receipt_id"]
    assert card["replay_recovery"]["lineage"]["latest_receipt_id"] == card["action_preflight"]["refresh_receipt_id"]
    assert card["replay_recovery"]["lineage"]["lineage_is_read_only"] is True
    assert card["replay_recovery"]["index"]["index_is_read_only"] is True
    assert card["replay_recovery"]["index"]["requires_exact_job_id"] is False
    assert card["replay_recovery"]["highest_priority_attempt"]["job_id"] == job.job_id
    assert all(probe["read_only"] is True for probe in card["replay_recovery"]["resume_probes"])
    assert "Replay recovery: highest-priority job" in card["resume_prompt"]
    assert any(
        item.get("ref_type") == "preflight_refresh_receipt"
        for item in card["completed_evidence"]
    )
    loaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    loaded_job = loaded_runtime.get_job(job.job_id)
    assert loaded_job is not None
    loaded_card = loaded_job.metadata["agent_handoff_card"]
    assert loaded_card["schema_version"] == "scholar_ai_agent_handoff_card_v1"
    assert loaded_card["resource_refs"][0]["ref_id"] == "material:handoff"
    assert loaded_card["replay_recovery"]["current_receipt"]["receipt_id"] == loaded_card["action_preflight"]["refresh_receipt_id"]
    assert any(probe["endpoint"] == "/runtime/workflow-passport" for probe in loaded_card["resume_probes"])
    assert any(probe["endpoint"] == f"/runtime/job/{job.job_id}/workflow-replay-lineage" for probe in loaded_card["resume_probes"])
    assert any(probe["endpoint"] == "/runtime/workflow-replay-index" for probe in loaded_card["resume_probes"])
    receipt_probe = next(
        probe
        for probe in loaded_card["resume_probes"]
        if probe["label"] == "Inspect preflight refresh receipt"
    )
    assert receipt_probe["endpoint"] == f"/runtime/job/{job.job_id}/preflight-refresh-receipt"
    assert "receipt_id=preflight_refresh%3A" in receipt_probe["url"]
    artifacts = loaded_runtime.get_job_artifacts(job.job_id, ArtifactType.METADATA)
    card_artifacts = [artifact for artifact in artifacts if artifact.metadata.get("kind") == "agent_handoff_card"]
    assert card_artifacts
    assert card_artifacts[-1].content["request_id"] == "agentreq_persisted"


@pytest.mark.asyncio
async def test_agent_bridge_result_and_failure_persist_agent_handoff_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Terminal agent bridge writes should leave recoverable handoff cards."""

    runtime = WritingRuntime(autosave=False)
    monkeypatch.setattr(agent_bridge_router, "get_runtime", lambda: (runtime, SessionMode))
    session = runtime.create_session(
        mode=SessionMode.HYBRID,
        metadata={"project_id": "project-agent-bridge"},
    )
    result_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="read material",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq_result",
            "agent_host": "codex",
            "intent": "single_paper_deep_read",
            "project_id": "project-agent-bridge",
            "resource_refs": [
                {
                    "ref_id": "material:agent-bridge",
                    "kind": "material",
                    "project_id": "project-agent-bridge",
                    "read_endpoint": "/api/agent-bridge/resource/material:agent-bridge",
                }
            ],
        },
    )
    failure_job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.AGENT_REQUEST,
        input_text="failing material",
        metadata={
            "agent_bridge": True,
            "agent_request_id": "agentreq_failure",
            "agent_host": "codex",
            "intent": "diagnose_failure",
            "project_id": "project-agent-bridge",
        },
    )

    result_payload = await agent_bridge_router.write_agent_result(
        "agentreq_result",
        agent_bridge_router.AgentResultRequest(
            text="done",
            evidence_refs=[{"ref_id": "chunk:1", "page": 2}],
        ),
    )
    failure_payload = await agent_bridge_router.fail_agent_request(
        "agentreq_failure",
        agent_bridge_router.AgentFailRequest(error="agent stopped by test"),
    )

    result_card = result_payload.job.metadata["agent_handoff_card"]
    failure_card = failure_payload.metadata["agent_handoff_card"]
    assert result_card["schema_version"] == "scholar_ai_agent_handoff_card_v1"
    assert result_card["status"] == "completed"
    assert result_card["resource_refs"][0]["ref_id"] == "material:agent-bridge"
    assert any(probe["endpoint"] == "/runtime/evidence-integrity-gate" for probe in result_card["resume_probes"])
    assert any("PDFMathTranslate" in action for action in result_card["forbidden_actions"])
    assert failure_card["status"] == "failed"
    assert any("agent stopped by test" in blocker for blocker in failure_card["blockers"])
    result_artifacts = runtime.get_job_artifacts(result_job.job_id, ArtifactType.METADATA)
    failure_artifacts = runtime.get_job_artifacts(failure_job.job_id, ArtifactType.METADATA)
    assert any(artifact.metadata.get("kind") == "agent_handoff_card" for artifact in result_artifacts)
    assert any(artifact.metadata.get("kind") == "agent_handoff_card" for artifact in failure_artifacts)


def _workspace_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace_root = tmp_path / "workspace"
    entry_cwd = workspace_root / "notes"
    entry_cwd.mkdir(parents=True)
    db_path = workspace_root / ".modular" / "sessions" / "index.sqlite3"
    return workspace_root, entry_cwd, db_path


def _workspace_metadata(workspace_root: Path, entry_cwd: Path) -> dict[str, str]:
    normalized_root = str(workspace_root.resolve())
    return {
        "workspace_root": normalized_root,
        "entry_cwd": str(entry_cwd.resolve()),
        "title": "Persistent workspace session",
        "workspace_key": sha256(normalized_root.encode("utf-8")).hexdigest(),
    }


@pytest.mark.asyncio
async def test_runtime_resume_restores_workspace_bound_session_timeline_and_checkpoints(tmp_path: Path) -> None:
    """A persisted workspace session should resume from the last active transcript head."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    first_runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = first_runtime.create_session(
        mode=SessionMode.SKILL,
        user_id="workspace-user",
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )
    first_job = first_runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="First persisted run",
        skill_id="skill-one",
    )
    await first_runtime.start_job(first_job.job_id)
    await first_runtime.complete_job(first_job.job_id, result="first-result")

    transcript_path = workspace_root / ".modular" / "sessions" / "transcripts" / f"{session.session_id}.jsonl"
    assert transcript_path.exists(), "expected append-only transcript file to be created"

    second_runtime = WritingRuntime(database_path=db_path, autosave=True)

    current_session = second_runtime.get_current_session(workspace_root=str(workspace_root))
    assert current_session is not None
    assert current_session.session_id == session.session_id
    assert current_session.metadata["workspace_key"] == sha256(str(workspace_root.resolve()).encode("utf-8")).hexdigest()

    resumed = second_runtime.resume_session(session.session_id)
    assert resumed["session"]["session_id"] == session.session_id
    assert resumed["head_event_id"]
    assert resumed["head_checkpoint_id"]

    timeline_page = second_runtime.get_session_timeline(session.session_id, limit=3)
    assert [item["event_kind"] for item in timeline_page["items"][:2]] == [
        "session_created",
        "checkpoint_created",
    ]
    assert timeline_page["next_cursor"] is not None

    remaining_page = second_runtime.get_session_timeline(
        session.session_id,
        after_event_id=timeline_page["next_cursor"],
        limit=20,
    )
    assert any(item["event_kind"] == "job_completed" for item in remaining_page["items"])

    checkpoints = second_runtime.list_checkpoints(session.session_id)
    assert len(checkpoints) >= 2
    assert checkpoints[-1]["checkpoint_id"] == resumed["head_checkpoint_id"]


@pytest.mark.asyncio
async def test_runtime_rewind_and_fork_preserve_append_only_parent_history(tmp_path: Path) -> None:
    """Rewind should move the active head back, and fork should branch without mutating the parent."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    for ordinal in range(2):
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=f"step-{ordinal}",
            action_id=f"action-{ordinal}",
        )
        await runtime.start_job(job.job_id)
        await runtime.complete_job(job.job_id, result=f"result-{ordinal}")

    checkpoints = runtime.list_checkpoints(session.session_id)
    rewind_target = checkpoints[1]

    rewind_result = runtime.rewind_session(session.session_id, rewind_target["checkpoint_id"])
    assert rewind_result["head_checkpoint_id"] == rewind_target["checkpoint_id"]

    rewound_timeline = runtime.get_session_timeline(session.session_id, limit=50)
    assert not any(
        item["payload"].get("job_id") == "action-1" or item["payload"].get("input_text") == "step-1"
        for item in rewound_timeline["items"]
    )
    assert any(item["event_kind"] == "session_rewound" for item in rewound_timeline["items"])

    fork_result = runtime.fork_session(
        session.session_id,
        rewind_target["checkpoint_id"],
        title="Forked branch",
    )
    forked_session = runtime.get_session(fork_result["session"]["session_id"])
    assert forked_session is not None
    assert forked_session.metadata["parent_session_id"] == session.session_id
    assert forked_session.metadata["forked_from_checkpoint_id"] == rewind_target["checkpoint_id"]

    forked_job = runtime.create_job(
        session_id=forked_session.session_id,
        kind=JobKind.SKILL_ACTION,
        input_text="branch-only",
        skill_id="branch-skill",
    )
    await runtime.start_job(forked_job.job_id)
    await runtime.complete_job(forked_job.job_id, result="branch-result")

    parent_timeline = runtime.get_session_timeline(session.session_id, limit=50)
    fork_timeline = runtime.get_session_timeline(forked_session.session_id, limit=50)
    assert not any(item["payload"].get("input_text") == "branch-only" for item in parent_timeline["items"])
    assert any(item["payload"].get("input_text") == "branch-only" for item in fork_timeline["items"])


@pytest.mark.asyncio
async def test_runtime_repair_truncates_damaged_transcript_tail(tmp_path: Path) -> None:
    """Broken JSONL tails should be discarded back to the last valid transcript event."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)
    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="repair-me",
        action_id="repair-action",
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result="repair-result")

    transcript_path = workspace_root / ".modular" / "sessions" / "transcripts" / f"{session.session_id}.jsonl"
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write('{"event_id":"broken-tail"')

    reloaded_runtime = WritingRuntime(database_path=db_path, autosave=True)
    repaired_timeline = reloaded_runtime.get_session_timeline(session.session_id, limit=50)
    assert repaired_timeline["items"]

    repaired_lines = transcript_path.read_text(encoding="utf-8").splitlines()
    assert repaired_lines
    last_payload = json.loads(repaired_lines[-1])
    assert last_payload["event_kind"] != "broken-tail"


@pytest.mark.asyncio
async def test_large_payload_spill_and_resume(tmp_path: Path) -> None:
    """Large payloads (>64KB) should spill to blob storage and rehydrate on resume."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)

    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    # Create a large payload (100KB) that should trigger spill
    large_content = "x" * (100 * 1024)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text=f"large-payload-{len(large_content)}-bytes",
        action_id="large-action",
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result=large_content)

    # Verify blob spill occurred
    blobs_dir = workspace_root / ".modular" / "sessions" / "blobs"
    assert blobs_dir.exists(), "blobs directory should be created for spilled payloads"
    spilled_blobs = list(blobs_dir.rglob("*.json"))
    assert len(spilled_blobs) > 0, "expected at least one spilled blob"

    # Resume and verify rehydration
    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    timeline = second_runtime.get_session_timeline(session.session_id, limit=50)

    completed_event = next(
        (item for item in timeline["items"] if item["event_kind"] == "job_completed"),
        None,
    )
    assert completed_event is not None

    # Verify payload is fully rehydrated (not just blob_ref placeholder)
    payload = completed_event.get("payload", {})
    if isinstance(payload, dict) and payload.get("inlined") is False:
        pytest.fail("Expected rehydrated payload, got blob_ref placeholder in timeline")


@pytest.mark.asyncio
async def test_mixed_payload_sizes_with_rehydration(tmp_path: Path) -> None:
    """Mixed small and large payloads should handle spill/rehydrate correctly."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)

    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    # Mix of small and large payloads
    payloads = [
        ("small-1", "x" * 1000),
        ("large-1", "y" * (80 * 1024)),
        ("small-2", "z" * 500),
        ("large-2", "w" * (100 * 1024)),
    ]

    for i, (name, content) in enumerate(payloads):
        job = runtime.create_job(
            session_id=session.session_id,
            kind=JobKind.PROMPT_ACTION,
            input_text=f"payload-{name}",
            action_id=f"action-{i}",
        )
        await runtime.start_job(job.job_id)
        await runtime.complete_job(job.job_id, result=content)

    # Verify all payloads are rehydrated on resume
    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    timeline = second_runtime.get_session_timeline(session.session_id, limit=100)

    completed_events = [item for item in timeline["items"] if item["event_kind"] == "job_completed"]
    assert len(completed_events) == 4

    for event in completed_events:
        payload = event.get("payload", {})
        if isinstance(payload, dict) and payload.get("inlined") is False:
            pytest.fail(f"Event {event['event_id']} has unresolved blob_ref in timeline")


@pytest.mark.asyncio
async def test_corrupted_blob_graceful_degradation(tmp_path: Path) -> None:
    """Missing/corrupted blobs should preserve blob_ref placeholder without crashing."""
    workspace_root, entry_cwd, db_path = _workspace_paths(tmp_path)
    runtime = WritingRuntime(database_path=db_path, autosave=True)

    session = runtime.create_session(
        mode=SessionMode.SKILL,
        metadata=_workspace_metadata(workspace_root, entry_cwd),
    )

    # Create and spill a large payload
    large_content = "x" * (100 * 1024)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PROMPT_ACTION,
        input_text="corruption-test",
        action_id="corrupt-action",
    )
    await runtime.start_job(job.job_id)
    await runtime.complete_job(job.job_id, result=large_content)

    # Corrupt the blob files
    blobs_dir = workspace_root / ".modular" / "sessions" / "blobs"
    for blob_file in blobs_dir.rglob("*.json"):
        blob_file.write_text("invalid json {{{")

    # Resume should not crash, just preserve blob_refs
    second_runtime = WritingRuntime(database_path=db_path, autosave=True)
    timeline = second_runtime.get_session_timeline(session.session_id, limit=50)

    # Should still return events, even if payloads are degraded
    assert len(timeline["items"]) > 0
    assert any(item["event_kind"] == "job_completed" for item in timeline["items"])

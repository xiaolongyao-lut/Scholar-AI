"""Test H5/H10: Writing submission and export API (2026-05-27).

Verify reviewer submission and project export endpoints.
"""

import base64
import sys
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))


class TestReviewerSubmission:
    """H5: Reviewer submission."""

    def test_submit_for_review_endpoint_exists(self):
        """POST /api/writing/submit endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        methods = {r.path: r.methods for r in router.routes}
        assert "/api/writing/submit" in routes
        assert "POST" in methods.get("/api/writing/submit", set())

    def test_submit_for_review_creates_local_package(self):
        """POST /api/writing/submit creates a local submission manifest."""
        from literature_assistant.core.python_adapter_server import app

        client = TestClient(app)
        created = client.post(
            "/api/writing/projects",
            json={
                "title": "Reviewer Package Project",
                "description": "Regression for H5",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        section = client.post(
            "/resources/section",
            json={
                "project_id": project_id,
                "title": "Results",
                "order": 0,
                "description": "Main findings",
            },
        )
        assert section.status_code == 200

        draft = client.post(
            "/resources/draft",
            json={
                "project_id": project_id,
                "section_id": section.json()["section_id"],
                "title": "Results draft",
                "content": "Draft text for reviewer submission.",
            },
        )
        assert draft.status_code == 200

        material = client.post(
            "/resources/material",
            json={
                "project_id": project_id,
                "title": "Reviewer source paper",
                "summary": "Source material used by the draft.",
                "type": "reference",
            },
        )
        assert material.status_code == 200

        submitted = client.post(
            "/api/writing/submit",
            json={
                "project_id": project_id,
                "reviewer_email": "reviewer@example.com",
                "message": "Please review evidence coverage.",
                "include_drafts": True,
                "include_materials": True,
            },
        )
        assert submitted.status_code == 200
        body = submitted.json()
        assert body["project_id"] == project_id
        assert body["status"] == "submitted"
        assert body["reviewer_email"] == "reviewer@example.com"
        assert body["submission_id"].startswith("sub_")
        assert body["package_path"]

        package_dir = Path(body["package_path"])
        assert package_dir.exists()
        manifest = package_dir / "submission_manifest.json"
        readme = package_dir / "README.md"
        assert manifest.exists()
        assert readme.exists()

        manifest_body = json.loads(manifest.read_text(encoding="utf-8"))
        assert manifest_body["submission_id"] == body["submission_id"]
        assert manifest_body["project"]["title"] == "Reviewer Package Project"
        assert len(manifest_body["sections"]) == 1
        assert len(manifest_body["drafts"]) == 1
        assert len(manifest_body["materials"]) == 1


class TestProjectExport:
    """H10: Project export."""

    def test_export_project_endpoint_exists(self):
        """POST /api/writing/export endpoint exists."""
        from routers.writing_router import router
        routes = [r.path for r in router.routes]
        methods = {r.path: r.methods for r in router.routes}
        assert "/api/writing/export" in routes
        assert "POST" in methods.get("/api/writing/export", set())

    def test_export_project_post_returns_markdown_and_json(self):
        """POST /api/writing/export delegates to the live resources exporter."""
        from literature_assistant.core.python_adapter_server import app

        client = TestClient(app)
        created = client.post(
            "/api/writing/projects",
            json={
                "title": "Export Alias Project",
                "description": "Regression for canonical writing export",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        markdown = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "markdown",
                "include_evidence": True,
                "include_citations": True,
            },
        )
        assert markdown.status_code == 200
        markdown_body = markdown.json()
        assert markdown_body["format"] == "markdown"
        assert markdown_body["project_id"] == project_id
        assert markdown_body["content"] == "# Export Alias Project"

        json_export = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "json",
                "include_evidence": True,
                "include_citations": True,
            },
        )
        assert json_export.status_code == 200
        json_body = json_export.json()
        assert json_body["format"] == "json"
        assert json_body["project_id"] == project_id
        assert json_body["project"]["title"] == "Export Alias Project"

    def test_export_project_records_runtime_workflow_state(self, monkeypatch, tmp_path):
        """Writing export should persist workflow state without changing response shape."""
        from harness_protocols import JobKind, SessionMode
        from literature_assistant.core.python_adapter_server import app
        from writing_runtime import WritingRuntime
        import routers.writing_router as writing_router_module

        runtime = WritingRuntime(database_path=tmp_path / "writing-export-runtime.sqlite3", autosave=True)
        monkeypatch.setattr(writing_router_module, "get_writing_runtime", lambda: runtime)

        client = TestClient(app)
        created = client.post(
            "/api/writing/projects",
            json={
                "title": "Runtime Export State Project",
                "description": "Regression for workflow-state export wiring",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        section = client.post(
            "/resources/section",
            json={
                "project_id": project_id,
                "title": "Findings",
                "order": 0,
                "description": "Evidence section",
            },
        )
        assert section.status_code == 200
        draft = client.post(
            "/resources/draft",
            json={
                "project_id": project_id,
                "section_id": section.json()["section_id"],
                "title": "Findings draft",
                "content": "Evidence-backed export text [@runtime2026].",
            },
        )
        assert draft.status_code == 200

        response = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "json",
                "include_evidence": True,
                "include_citations": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["format"] == "json"
        assert "runtime_job_id" not in body
        assert "workflow_state" not in body

        jobs = [
            job
            for session in runtime.list_sessions(include_archived=True)
            for job in runtime.list_jobs(session.session_id)
            if job.kind == JobKind.ARTIFACT_EXPORT and job.metadata.get("project_id") == project_id
        ]
        assert len(jobs) == 1
        state = runtime.get_writing_workflow_state(jobs[0].job_id)
        assert state is not None
        assert state["phase"] == "export_ready"
        assert state["intake"]["project_id"] == project_id
        assert state["export_manifest"]["format"] == "json"
        assert state["export_manifest"]["filename"].endswith(".json")
        assert state["readiness"]["has_export_manifest"] is True
        assert state["lint_report"]["writing_audit_present"] is True
        assert state["change_log"][0]["stage"] == "export"
        bundle_artifacts = [
            artifact
            for artifact in runtime.get_job_artifacts(jobs[0].job_id)
            if artifact.metadata.get("kind") == "writing_export_bundle_manifest"
        ]
        assert len(bundle_artifacts) == 1
        bundle_manifest = bundle_artifacts[0].content
        assert isinstance(bundle_manifest, dict)
        assert bundle_manifest["schema_version"] == "writing_export_bundle_manifest_v1"
        assert bundle_manifest["bundle"]["entry_document"] == body["filename"]
        assert bundle_manifest["project"]["project_id"] == project_id
        assert bundle_manifest["counts"]["evidence_rows"] == len(body["evidence_rows"])
        assert bundle_manifest["resources"][0]["role"] == "entry_document"
        assert state["export_manifest"]["bundle_manifest_artifact_id"] == bundle_artifacts[0].artifact_id
        session = runtime.get_session(jobs[0].session_id)
        assert session is not None
        assert session.mode == SessionMode.SKILL

    def test_export_project_action_preflight_blocks_when_required(self, monkeypatch, tmp_path):
        """Explicit action preflight should block export readiness overclaims."""
        from literature_assistant.core.python_adapter_server import app
        from writing_runtime import WritingRuntime
        import routers.writing_router as writing_router_module

        runtime = WritingRuntime(database_path=tmp_path / "writing-export-preflight.sqlite3", autosave=True)
        monkeypatch.setattr(writing_router_module, "get_writing_runtime", lambda: runtime)

        client = TestClient(app)
        created = client.post(
            "/api/writing/projects",
            json={
                "title": "Blocked Export Project",
                "description": "Regression for action preflight",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        blocked = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "json",
                "include_evidence": True,
                "include_citations": True,
                "require_action_preflight": True,
            },
        )

        assert blocked.status_code == 409
        detail = blocked.json()
        assert detail["error"] == "action_preflight_blocked"
        preflight = detail["action_preflight"]
        assert preflight["schema_version"] == "scholar_ai_action_preflight_v1"
        assert preflight["action_id"] == "writing.export_project"
        assert preflight["required_claim_id"] == "export_readiness"
        assert preflight["require_ready"] is True
        assert preflight["can_proceed"] is False
        assert preflight["status"] in {"blocked", "unresolved"}
        assert preflight["summary"]["unresolved_is_ready"] is False
        assert preflight["freshness"]["schema_version"] == "scholar_ai_action_preflight_freshness_v1"
        assert preflight["refresh_required"] is False

    def test_export_project_action_preflight_attaches_when_not_required(self, monkeypatch, tmp_path):
        """Legacy export remains compatible while exposing the action preflight."""
        from literature_assistant.core.python_adapter_server import app
        from writing_runtime import WritingRuntime
        import routers.writing_router as writing_router_module

        runtime = WritingRuntime(database_path=tmp_path / "writing-export-preflight-observe.sqlite3", autosave=True)
        monkeypatch.setattr(writing_router_module, "get_writing_runtime", lambda: runtime)

        client = TestClient(app)
        created = client.post(
            "/api/writing/projects",
            json={
                "title": "Observable Export Project",
                "description": "Regression for non-blocking action preflight",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        exported = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "json",
                "include_evidence": True,
                "include_citations": True,
            },
        )

        assert exported.status_code == 200
        body = exported.json()
        assert body["format"] == "json"
        assert body["action_preflight"]["schema_version"] == "scholar_ai_action_preflight_v1"
        assert body["action_preflight"]["require_ready"] is False
        assert body["action_preflight"]["summary"]["unresolved_is_ready"] is False
        assert body["action_preflight"]["freshness"]["schema_version"] == "scholar_ai_action_preflight_freshness_v1"
        assert body["action_preflight"]["refresh_required"] is False

    def test_export_project_post_returns_word_latex_and_pdf(self):
        """POST /api/writing/export returns generated academic export formats."""
        from literature_assistant.core.python_adapter_server import app

        client = TestClient(app)
        created = client.post(
            "/api/writing/projects",
            json={
                "title": "Multi Format Export Project",
                "description": "Regression for generated export files",
                "user_id": "tester",
            },
        )
        assert created.status_code == 200
        project_id = created.json()["project_id"]

        section = client.post(
            "/resources/section",
            json={
                "project_id": project_id,
                "title": "Methods & Results",
                "order": 1,
                "description": "A section requiring LaTeX escaping.",
            },
        )
        assert section.status_code == 200
        section_id = section.json()["section_id"]
        draft = client.post(
            "/resources/draft",
            json={
                "project_id": project_id,
                "section_id": section_id,
                "title": "Draft_100%",
                "content": (
                    "Alpha & beta reach 100% coverage.\n\n"
                    "This paragraph is deliberately long enough to trigger "
                    "a review finding without a citation anchor."
                ),
            },
        )
        assert draft.status_code == 200
        material = client.post(
            "/resources/material",
            json={
                "project_id": project_id,
                "title": "Source & Evidence",
                "summary": "Evidence summary with 50% ratio and A_B notation.",
                "type": "paper",
            },
        )
        assert material.status_code == 200

        latex = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "latex",
                "include_evidence": True,
                "include_citations": True,
            },
        )
        assert latex.status_code == 200
        latex_body = latex.json()
        assert latex_body["format"] == "latex"
        assert latex_body["filename"].endswith(".tex")
        assert "\\documentclass" in latex_body["content"]
        assert "Multi Format Export Project" in latex_body["content"]
        assert "Methods \\& Results" in latex_body["content"]
        assert "Alpha \\& beta reach 100\\% coverage." in latex_body["content"]
        assert "Draft\\_100\\%" not in latex_body["content"]
        assert "证据表" not in latex_body["content"]
        assert "审计提示" not in latex_body["content"]

        word = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "word",
                "include_evidence": True,
                "include_citations": True,
            },
        )
        assert word.status_code == 200
        word_body = word.json()
        assert word_body["format"] == "word"
        assert word_body["filename"].endswith(".docx")
        assert word_body["media_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        assert "Multi Format Export Project" in word_body["content"]
        assert "Alpha & beta reach 100% coverage." in word_body["content"]
        assert "证据表" not in word_body["content"]
        assert "审计提示" not in word_body["content"]
        assert base64.b64decode(word_body["content_base64"])[:2] == b"PK"
        assert Path(word_body["file_path"]).exists()

        pdf = client.post(
            "/api/writing/export",
            json={
                "project_id": project_id,
                "format": "pdf",
                "include_evidence": True,
                "include_citations": True,
            },
        )
        assert pdf.status_code == 200
        pdf_body = pdf.json()
        assert pdf_body["format"] == "pdf"
        assert pdf_body["filename"].endswith(".pdf")
        assert pdf_body["media_type"] == "application/pdf"
        assert base64.b64decode(pdf_body["content_base64"])[:4] == b"%PDF"
        assert "Alpha & beta reach 100% coverage." in pdf_body["content"]
        assert "Multi Format Export Project" in pdf_body["content"]
        assert "证据表" not in pdf_body["content"]
        assert "审计提示" not in pdf_body["content"]
        assert Path(pdf_body["file_path"]).exists()


class TestSubmissionExportModels:
    """Submission and export data models."""

    def test_submit_for_review_request_model_exists(self):
        """SubmitForReviewRequest model exists."""
        from models.resources import SubmitForReviewRequest
        assert SubmitForReviewRequest is not None

    def test_submission_response_payload_model_exists(self):
        """SubmissionResponsePayload model exists."""
        from models.resources import SubmissionResponsePayload
        assert SubmissionResponsePayload is not None

    def test_export_project_request_model_exists(self):
        """ExportProjectRequest model exists."""
        from models.resources import ExportProjectRequest
        assert ExportProjectRequest is not None

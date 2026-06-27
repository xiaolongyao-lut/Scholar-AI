"""Test G2: Wiki page CRUD operations (2026-05-26).

Verify POST/PUT/DELETE /api/wiki/pages endpoints.
"""

import sys
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from python_adapter_server import app, get_local_api_capability_token
from literature_assistant.core.wiki.review_queue import ReviewQueue
from writing_runtime import WritingRuntime


@pytest.fixture
def client():
    """TestClient for API testing."""
    return TestClient(app)


@pytest.fixture
def mock_wiki_service():
    """Mock WikiService for testing."""
    with patch("wiki.service.get_wiki_service") as mock_get:
        service = MagicMock()
        mock_get.return_value = service
        yield service


@pytest.fixture
def mock_wiki_enabled():
    """Mock wiki_enabled to return True."""
    with patch("routers.wiki_router.wiki_enabled", return_value=True):
        yield


class TestWikiPageCreate:
    """G2: POST /api/wiki/pages endpoint."""

    def test_create_page_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful create returns slug."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="synthesis-test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T00:00:00Z",
        )
        mock_wiki_service.create_page.return_value = page

        resp = client.post(
            "/api/wiki/pages",
            json={
                "title": "Test Page",
                "kind": "synthesis",
                "body": "Test content",
                "status": "draft",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["slug"] == "synthesis-test-page"

    def test_create_page_already_exists(self, client, mock_wiki_service, mock_wiki_enabled):
        """Create duplicate page returns 409."""
        mock_wiki_service.create_page.side_effect = ValueError("Page already exists: synthesis-test")

        resp = client.post(
            "/api/wiki/pages",
            json={
                "title": "Test",
                "kind": "synthesis",
                "body": "Content",
            },
        )
        assert resp.status_code == 409

    def test_create_page_invalid_kind(self, client, mock_wiki_service, mock_wiki_enabled):
        """Create with invalid kind returns 400."""
        mock_wiki_service.create_page.side_effect = ValueError("'invalid' is not a valid WikiPageKind")

        resp = client.post(
            "/api/wiki/pages",
            json={
                "title": "Test",
                "kind": "invalid",
                "body": "Content",
            },
        )
        assert resp.status_code == 400

    def test_create_page_wiki_disabled(self, client, mock_wiki_service):
        """Create when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.post(
                "/api/wiki/pages",
                json={
                    "title": "Test",
                    "kind": "synthesis",
                    "body": "Content",
                },
            )
            assert resp.status_code == 404


class TestWikiPageUpdate:
    """G2: PUT /api/wiki/pages/{slug} endpoint."""

    def test_update_page_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful update returns slug."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="synthesis-test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Updated Title",
            body="Updated content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T01:00:00Z",
        )
        mock_wiki_service.update_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/synthesis-test-page",
            json={
                "title": "Updated Title",
                "body": "Updated content",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["slug"] == "synthesis-test-page"

    def test_update_page_not_found(self, client, mock_wiki_service, mock_wiki_enabled):
        """Update non-existent page returns 404."""
        mock_wiki_service.update_page.side_effect = ValueError("Page not found: nonexistent")

        resp = client.put(
            "/api/wiki/pages/nonexistent",
            json={"title": "New Title"},
        )
        assert resp.status_code == 404

    def test_update_page_partial(self, client, mock_wiki_service, mock_wiki_enabled):
        """Partial update only changes specified fields."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        page = WikiPage(
            stable_slug="synthesis-test-page",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.final,
            title="Test Page",
            body="Test content",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-05-26T00:00:00Z",
            updated_at_iso="2026-05-26T01:00:00Z",
        )
        mock_wiki_service.update_page.return_value = page

        resp = client.put(
            "/api/wiki/pages/synthesis-test-page",
            json={"status": "final"},
        )
        assert resp.status_code == 200

        # Verify only status was passed to service
        mock_wiki_service.update_page.assert_called_once()
        call_kwargs = mock_wiki_service.update_page.call_args.kwargs
        assert call_kwargs["status"] == "final"
        assert call_kwargs["title"] is None
        assert call_kwargs["body"] is None

    def test_update_page_wiki_disabled(self, client, mock_wiki_service):
        """Update when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.put(
                "/api/wiki/pages/test-page",
                json={"title": "New Title"},
            )
            assert resp.status_code == 404


class TestWikiPageDelete:
    """G2: DELETE /api/wiki/pages/{slug} endpoint."""

    def test_delete_page_success(self, client, mock_wiki_service, mock_wiki_enabled):
        """Successful delete returns slug."""
        mock_wiki_service.delete_page.return_value = None

        resp = client.delete("/api/wiki/pages/synthesis-test-page")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["slug"] == "synthesis-test-page"

    def test_delete_page_not_found(self, client, mock_wiki_service, mock_wiki_enabled):
        """Delete non-existent page returns 404."""
        mock_wiki_service.delete_page.side_effect = ValueError("Page not found: nonexistent")

        resp = client.delete("/api/wiki/pages/nonexistent")
        assert resp.status_code == 404

    def test_delete_page_wiki_disabled(self, client, mock_wiki_service):
        """Delete when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.delete("/api/wiki/pages/test-page")
            assert resp.status_code == 404


class TestWikiImport:
    """G16: POST /api/wiki/import local Markdown import endpoint."""

    def test_import_markdown_dry_run_plans_create(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Dry-run validates local Markdown and returns the planned wiki page."""
        source = tmp_path / "import-note.md"
        source.write_text("# Imported Note\n\nEvidence-backed note.", encoding="utf-8")
        mock_wiki_service.get_page.return_value = None

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post("/api/wiki/import", json={"source_paths": [str(source)]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["dry_run"] is True
        assert data["imported"] == 0
        assert data["skipped"] == 1
        assert data["errored"] == 0
        assert data["pages"][0]["title"] == "Imported Note"
        assert data["pages"][0]["slug"] == "synthesis-imported-note"
        assert data["pages"][0]["action"] == "planned_create"
        mock_wiki_service.create_page.assert_not_called()

    def test_import_markdown_apply_creates_private_page(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Apply mode creates a private page with import provenance."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "source-note.md"
        source.write_text("# Source Note\n\nImported body.", encoding="utf-8")
        review_queue_path = tmp_path / "runtime" / "review_queue.jsonl"
        mock_wiki_service.get_page.return_value = None
        mock_wiki_service.create_page.return_value = WikiPage(
            stable_slug="synthesis-source-note",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Source Note",
            body="Imported body.",
            evidence_refs=(),
            source_hashes=("hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
            "routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path
        ):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={
                    "source_paths": [str(source)],
                    "dry_run": False,
                    "confirm_write": True,
                    "status": "final",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 1
        assert data["pages"][0]["action"] == "created"
        assert data["pages"][0]["review_item_id"] == "import-synthesis-source-note"
        call_kwargs = mock_wiki_service.create_page.call_args.kwargs
        assert call_kwargs["title"] == "Source Note"
        assert call_kwargs["kind"] == "synthesis"
        assert call_kwargs["status"] == "draft"
        assert call_kwargs["body"] == "# Source Note\n\nImported body."
        assert call_kwargs["extra"]["permissions"]["owner"] == "owner123"
        assert call_kwargs["extra"]["permissions"]["visibility"] == "private"
        assert call_kwargs["extra"]["entry_source"] == "local_markdown_import"
        assert call_kwargs["extra"]["import_source"]["type"] == "local_markdown"
        assert call_kwargs["extra"]["import_source"]["path"] == "source-note.md"
        assert len(call_kwargs["source_hashes"]) == 1
        review_items = ReviewQueue(review_queue_path).list_items()
        assert len(review_items) == 1
        item = review_items[0]
        assert item.item_id == "import-synthesis-source-note"
        assert item.status.value == "pending"
        assert item.kind.value == "draft"
        assert item.page_path == "synthesis/synthesis-source-note.md"
        assert item.source == "local_markdown_import"
        assert item.metadata["entry_source"] == "local_markdown_import"
        assert item.metadata["requested_status"] == "final"
        assert item.metadata["approval_surface"] == "wiki_review_queue"
        assert item.metadata["runtime_action_family"] == "wiki_candidate"
        assert item.metadata["workflow_passport"]["stage_id"] == "wiki_candidate"
        assert item.metadata["workflow_passport"]["source_ref"] == {
            "source_kind": "wiki_page_draft",
            "source_id": "synthesis/synthesis-source-note.md",
        }
        assert item.metadata["evidence_integrity_gate"]["status"] == "block"
        assert item.metadata["evidence_integrity_gate"]["blocking_claim_id"] == "wiki_import_review_approval"
        assert item.metadata["agent_handoff_recovery"]["resume_tool"] == "literature.wiki_import"
        assert "auto_approve_import" in item.metadata["agent_handoff_recovery"]["forbidden_actions"]

    def test_import_markdown_apply_requires_confirm_write(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        tmp_path,
    ):
        """Write mode requires a second explicit local-write confirmation."""

        source = tmp_path / "unconfirmed.md"
        source.write_text("# Unconfirmed\n\nShould remain dry.", encoding="utf-8")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={"source_paths": [str(source)], "dry_run": False},
        )

        assert resp.status_code == 400
        assert "confirm_write=true" in resp.json()["error"]["message"]
        mock_wiki_service.get_page.assert_not_called()
        mock_wiki_service.create_page.assert_not_called()

    def test_import_markdown_apply_records_runtime_action_lifecycle(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        monkeypatch,
        tmp_path,
    ):
        """Apply mode must create recoverable runtime action, gate, and handoff refs."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        runtime = WritingRuntime(autosave=False)
        source = tmp_path / "runtime-note.md"
        source.write_text("# Runtime Note\n\nImported body.", encoding="utf-8")
        review_queue_path = tmp_path / "runtime" / "review_queue.jsonl"
        mock_wiki_service.get_page.return_value = None
        mock_wiki_service.create_page.return_value = WikiPage(
            stable_slug="synthesis-runtime-note",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Runtime Note",
            body="Imported body.",
            evidence_refs=(),
            source_hashes=("hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
            "routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path
        ), patch("routers.wiki_router.get_writing_runtime", lambda: runtime):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={
                    "source_paths": [str(source)],
                    "dry_run": False,
                    "confirm_write": True,
                    "status": "review",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        item_payload = data["pages"][0]
        assert data["imported"] == 1
        assert item_payload["runtime_session_id"].startswith("session_")
        assert item_payload["runtime_job_id"].startswith("job_")
        assert item_payload["runtime_approval_id"]

        job = runtime.get_job(item_payload["runtime_job_id"])
        assert job is not None
        assert job.kind.value == "agent_request"
        assert job.metadata["manual_wiki_import"] is True
        assert job.metadata["output_targets"]["wiki_candidate"] is True
        assert job.metadata["knowledge_capture"]["requires_review_queue_approval"] is True
        assert job.metadata["wiki_import"]["review_item_id"] == "import-synthesis-runtime-note"

        review_item = ReviewQueue(review_queue_path).get("import-synthesis-runtime-note")
        assert review_item is not None
        assert review_item.metadata["runtime_job_id"] == item_payload["runtime_job_id"]
        assert review_item.metadata["runtime_approval_id"] == item_payload["runtime_approval_id"]
        assert review_item.metadata["runtime_recovery"]["agent_handoff_card"].endswith("/agent-handoff-card")

        lifecycle = runtime.build_research_action_lifecycle(job_id=item_payload["runtime_job_id"], limit=10)
        action_by_type = {action["action_type"]: action for action in lifecycle["actions"]}
        assert {"wiki_candidate", "agent_handoff", "approval_gate"} <= set(action_by_type)
        assert action_by_type["wiki_candidate"]["status"] == "pending_approval"
        assert action_by_type["wiki_candidate"]["approval"]["requires_user_confirmation"] is True
        assert any(ref["ref_type"] == "wiki_ref" for ref in action_by_type["wiki_candidate"]["effect_refs"])
        assert any(ref["ref_type"] == "resource_ref" for ref in action_by_type["wiki_candidate"]["effect_refs"])
        assert lifecycle["summary"]["requires_user_confirmation"] is True
        assert lifecycle["summary"]["read_only"] is True

        passport = runtime.build_workflow_passport(job_id=item_payload["runtime_job_id"], limit=50)
        agent_stage = next(stage for stage in passport["stages"] if stage["stage_id"] == "agent_handoff")
        assert agent_stage["gate"]["requires_user_confirmation"] is True
        assert any(
            ref["action_type"] == "wiki_candidate"
            for ref in agent_stage["reproducibility"]["research_action_refs"]
        )

        gate = runtime.build_evidence_integrity_gate(job_id=item_payload["runtime_job_id"], limit=50)
        assert any(ref["requires_user_confirmation"] is True for ref in gate["summary"]["research_action_refs"])
        assert gate["summary"]["research_action_count"] >= 1
        assert gate["blocking_action_boundary"]["local_read_only_probes"][0]["read_only"] is True

        handoff = runtime.build_agent_handoff_card(item_payload["runtime_job_id"])
        assert handoff["action_lifecycle_recovery"]["pending_confirmation_count"] >= 1
        assert any(
            ref["action_type"] == "wiki_candidate"
            for ref in handoff["action_lifecycle_recovery"]["action_refs"]
        )
        serialized = str(handoff) + str(lifecycle)
        assert str(source) not in serialized

    def test_import_markdown_apply_rolls_back_created_page_when_review_queue_fails(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        tmp_path,
    ):
        """A review-queue failure must not leave a created import draft behind."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "broken-review.md"
        source.write_text("# Broken Review\n\nImported body.", encoding="utf-8")
        queue_dir = tmp_path / "runtime"
        queue_dir.mkdir()
        review_queue_path = queue_dir / "review_queue.jsonl"
        review_queue_path.mkdir()
        mock_wiki_service.get_page.return_value = None
        mock_wiki_service.create_page.return_value = WikiPage(
            stable_slug="synthesis-broken-review",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Broken Review",
            body="Imported body.",
            evidence_refs=(),
            source_hashes=("hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
            "routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path
        ):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={"source_paths": [str(source)], "dry_run": False, "confirm_write": True},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errored"] == 1
        assert "Failed to create pending import review entry" in data["pages"][0]["error"]
        mock_wiki_service.delete_page.assert_called_once_with("synthesis-broken-review")

    def test_import_markdown_overwrite_rolls_back_update_when_review_queue_fails(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        tmp_path,
    ):
        """Overwrite mode restores the previous page if the review queue write fails."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "existing.md"
        source.write_text("# Existing\n\nReplacement body.", encoding="utf-8")
        queue_dir = tmp_path / "runtime"
        queue_dir.mkdir()
        review_queue_path = queue_dir / "review_queue.jsonl"
        review_queue_path.mkdir()
        existing_page = WikiPage(
            stable_slug="synthesis-existing",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.final,
            title="Existing",
            body="Original body.",
            evidence_refs=({"chunk_id": "c1", "material_id": "m1", "text": "e", "compressed_text": "", "quote": "", "label": ""},),
            source_hashes=("old-hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
            extra={
                "permissions": {
                    "owner": "owner123",
                    "visibility": "private",
                    "shared_with": [],
                }
            },
        )
        updated_page = existing_page.evolve(
            status=WikiPageStatus.draft,
            body="Replacement body.",
            source_hashes=("new-hash",),
        )
        mock_wiki_service.get_page.return_value = existing_page
        mock_wiki_service.update_page.return_value = updated_page

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
            "routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path
        ):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={
                    "source_paths": [str(source)],
                    "dry_run": False,
                    "confirm_write": True,
                    "overwrite": True,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errored"] == 1
        assert "Failed to create pending import review entry" in data["pages"][0]["error"]
        rollback_kwargs = mock_wiki_service.update_page.call_args_list[-1].kwargs
        assert rollback_kwargs == {
            "slug": "synthesis-existing",
            "title": "Existing",
            "body": "Original body.",
            "status": "final",
            "evidence_refs": [
                {"chunk_id": "c1", "material_id": "m1", "text": "e", "compressed_text": "", "quote": "", "label": ""}
            ],
            "source_hashes": ["old-hash"],
            "extra": existing_page.extra,
        }

    def test_import_markdown_apply_rolls_back_when_runtime_action_fails(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        tmp_path,
    ):
        """Runtime tracking is required for successful write-path import."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "runtime-failure.md"
        source.write_text("# Runtime Failure\n\nImported body.", encoding="utf-8")
        review_queue_path = tmp_path / "runtime" / "review_queue.jsonl"
        mock_wiki_service.get_page.return_value = None
        mock_wiki_service.create_page.return_value = WikiPage(
            stable_slug="synthesis-runtime-failure",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Runtime Failure",
            body="Imported body.",
            evidence_refs=(),
            source_hashes=("hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
            "routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path
        ), patch(
            "routers.wiki_router._record_wiki_import_runtime_action",
            side_effect=ValueError("runtime unavailable"),
        ):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={"source_paths": [str(source)], "dry_run": False, "confirm_write": True},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errored"] == 1
        assert "Failed to create pending import runtime action" in data["pages"][0]["error"]
        assert ReviewQueue(review_queue_path).list_items() == []
        mock_wiki_service.delete_page.assert_called_once_with("synthesis-runtime-failure")

    def test_import_markdown_apply_rolls_back_review_item_when_runtime_metadata_update_fails(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        tmp_path,
    ):
        """A half-recorded runtime action must not leave a page, session, or review item behind."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        runtime = WritingRuntime(autosave=False)
        source = tmp_path / "metadata-failure.md"
        source.write_text("# Metadata Failure\n\nImported body.", encoding="utf-8")
        review_queue_path = tmp_path / "runtime" / "review_queue.jsonl"
        mock_wiki_service.get_page.return_value = None
        mock_wiki_service.create_page.return_value = WikiPage(
            stable_slug="synthesis-metadata-failure",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.draft,
            title="Metadata Failure",
            body="Imported body.",
            evidence_refs=(),
            source_hashes=("hash",),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
            "routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path
        ), patch("routers.wiki_router.get_writing_runtime", lambda: runtime), patch(
            "routers.wiki_router.ReviewQueue.update_metadata",
            side_effect=OSError("metadata write failed"),
        ):
            resp = client.post(
                "/api/wiki/import?user_id=owner123",
                json={"source_paths": [str(source)], "dry_run": False, "confirm_write": True},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errored"] == 1
        assert "Failed to create pending import runtime action" in data["pages"][0]["error"]
        assert ReviewQueue(review_queue_path).list_items() == []
        assert runtime.list_sessions() == []
        mock_wiki_service.delete_page.assert_called_once_with("synthesis-metadata-failure")

    def test_import_markdown_skips_existing_without_overwrite(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Existing slugs are skipped by default to avoid overwriting local wiki pages."""
        from wiki.models import WikiPage, WikiPageKind, WikiPageStatus

        source = tmp_path / "existing.md"
        source.write_text("# Existing\n\nReplacement body.", encoding="utf-8")
        mock_wiki_service.get_page.return_value = WikiPage(
            stable_slug="synthesis-existing",
            kind=WikiPageKind.synthesis,
            status=WikiPageStatus.final,
            title="Existing",
            body="Original body.",
            evidence_refs=(),
            source_hashes=(),
            created_at_iso="2026-06-05T00:00:00Z",
            updated_at_iso="2026-06-05T00:00:00Z",
        )

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post(
                "/api/wiki/import",
                json={"source_paths": [str(source)], "dry_run": False, "confirm_write": True},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["skipped"] == 1
        assert data["pages"][0]["action"] == "skipped_exists"
        mock_wiki_service.update_page.assert_not_called()

    @pytest.mark.parametrize(
        ("protected_parts", "description"),
        [
            ((".git", "refs"), "git internals"),
            ((".rollback_snapshots", "manual"), "rollback snapshots"),
            (("github", "reference"), "reference repositories"),
        ],
    )
    def test_import_markdown_blocks_protected_workspace_paths(
        self,
        client,
        mock_wiki_service,
        mock_wiki_enabled,
        tmp_path,
        protected_parts,
        description,
    ):
        """Import refuses protected workspace paths even when they are under the repo root."""
        protected_dir = tmp_path.joinpath(*protected_parts)
        protected_dir.mkdir(parents=True)
        source = protected_dir / "note.md"
        source.write_text("# Reference\n\nProtected.", encoding="utf-8")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post("/api/wiki/import", json={"source_paths": [str(source)]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 0
        assert data["errored"] == 1
        assert "protected workspace area" in data["pages"][0]["error"]
        assert data["pages"][0]["source_path"].endswith("note.md")
        mock_wiki_service.create_page.assert_not_called()

    def test_import_markdown_rejects_non_markdown_source(self, client, mock_wiki_service, mock_wiki_enabled, tmp_path):
        """Only Markdown files are accepted for the reduced G16 local slice."""
        source = tmp_path / "note.txt"
        source.write_text("Plain text", encoding="utf-8")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            resp = client.post("/api/wiki/import", json={"source_paths": [str(source)]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["errored"] == 1
        assert "Markdown .md file" in data["pages"][0]["error"]

    def test_import_markdown_apply_writes_page_with_real_service(self, client, mock_wiki_enabled, tmp_path):
        """Apply mode can write a real generated wiki page in an isolated store."""
        import routers.agent_bridge_router as agent_bridge_router
        import routers.knowledge_router as knowledge_router
        from wiki.page_store import WikiPageStore
        from wiki.service import WikiService
        from wiki.source_registry import WikiRegistry
        from source_vault import SourceVault

        wiki_root = tmp_path / "wiki"
        runtime_root = tmp_path / "runtime"
        review_queue_path = runtime_root / "review_queue.jsonl"
        vault = SourceVault(
            db_path=tmp_path / "source_vault" / "source_vault.sqlite3",
            storage_root=tmp_path / "source_vault",
        )
        registry = WikiRegistry(runtime_root / "wiki.db", source_vault=vault)
        service = WikiService(WikiPageStore(wiki_root, create=True))
        source = tmp_path / "local-source.md"
        source.write_text("# Local Source\n\nBody from local note.", encoding="utf-8")
        headers = {"X-LitAssist-Capability": get_local_api_capability_token()}

        app.dependency_overrides[knowledge_router.get_source_vault] = lambda: vault
        try:
            with patch("routers.wiki_router.REPO_ROOT", tmp_path), patch(
                "routers.wiki_router.wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts)
            ), patch("routers.wiki_router.wiki_review_queue_path", lambda: review_queue_path), patch(
                "routers.wiki_router._wiki_import_registry", lambda: registry
            ), patch(
                "routers.agent_bridge_router.wiki_generated_root", lambda *parts: wiki_root.joinpath(*parts)
            ), patch("routers.agent_bridge_router.SourceVault", lambda: vault), patch(
                "routers.knowledge_router._agent_bridge_router.SourceVault", lambda: vault
            ), patch(
                "wiki.service.get_wiki_service", return_value=service
            ):
                resp = client.post(
                    "/api/wiki/import?user_id=owner123",
                    json={
                        "source_paths": [str(source)],
                        "dry_run": False,
                        "confirm_write": True,
                        "status": "final",
                    },
                    headers=headers,
                )

                assert resp.status_code == 200
                data = resp.json()
                assert data["imported"] == 1
                page_payload = data["pages"][0]
                assert page_payload["review_item_id"] == "import-synthesis-local-source"
                assert page_payload["import_source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
                assert page_payload["path"] == "synthesis/synthesis-local-source.md"
                assert page_payload["ref_id"] == "wiki:synthesis/synthesis-local-source.md"
                assert page_payload["chunk_id"].startswith("wiki:synthesis/synthesis-local-source.md#")
                assert page_payload["read_endpoint"] == "/api/agent-bridge/resource/wiki:synthesis/synthesis-local-source.md"
                assert page_payload["source_registry_id"].startswith("local_markdown_import-local-source-")
                assert page_payload["source_vault_status"] == "mirrored"
                assert page_payload["source_vault_source_id"].startswith("src_")
                assert page_payload["source_vault_chunk_id"]
                assert page_payload["source_vault_ref_id"] == f"source_vault:chunk:{page_payload['source_vault_chunk_id']}"
                assert page_payload["source_vault_read_endpoint"] == (
                    f"/api/agent-bridge/resource/{page_payload['source_vault_ref_id']}"
                )
                assert page_payload["span_start"] == 0
                assert page_payload["span_end"] > 0
                page_file = wiki_root / "synthesis" / "synthesis-local-source.md"
                assert page_file.exists()
                text = page_file.read_text(encoding="utf-8")
                assert page_payload["source_hash"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
                assert page_payload["content_hash"] == hashlib.sha256(
                    "# Local Source\n\nBody from local note.".encode("utf-8")
                ).hexdigest()
                assert "Body from local note." in text
                assert '"owner": "owner123"' in text
                assert '"visibility": "private"' in text
                assert '"type": "local_markdown"' in text
                assert '"entry_source": "local_markdown_import"' in text
                assert '"status": "draft"' in text
                assert '"status": "final"' not in text
                review_items = ReviewQueue(review_queue_path).list_items()
                assert [item.source for item in review_items] == ["local_markdown_import"]
                assert review_items[0].metadata["requested_status"] == "final"
                assert review_items[0].metadata["evidence_integrity_gate"]["status"] == "block"
                assert review_items[0].metadata["agent_handoff_recovery"]["review_queue_probe"] == (
                    "/api/wiki/review?status=pending&kind=draft"
                )

                list_response = client.get("/api/wiki/pages?user_id=owner123", headers=headers)
                assert list_response.status_code == 200
                assert list_response.json()["pages"] == []

                resource_response = client.get(
                    page_payload["read_endpoint"],
                    params={"max_chars": 100},
                    headers=headers,
                )
                assert resource_response.status_code == 200
                resource_payload = resource_response.json()
                assert resource_payload["ref_id"] == page_payload["ref_id"]
                assert resource_payload["kind"] == "wiki"
                assert "Body from local note." in resource_payload["content"]
                assert resource_payload["metadata"]["knowledge_ref_schema_version"] == "scholar-ai-wiki-knowledge-ref/v1"
                assert resource_payload["metadata"]["source_path"] == page_payload["path"]
                assert resource_payload["metadata"]["source_hash"] == page_payload["source_hash"]
                assert resource_payload["metadata"]["import_source_hash"] == page_payload["import_source_hash"]
                assert resource_payload["metadata"]["import_source_path"] == "local-source.md"
                assert resource_payload["metadata"]["import_source_type"] == "local_markdown"
                assert resource_payload["metadata"]["entry_source"] == "local_markdown_import"
                assert resource_payload["metadata"]["content_hash"] == page_payload["content_hash"]
                assert resource_payload["metadata"]["span_end"] == page_payload["span_end"]
                assert resource_payload["metadata"]["read_endpoint"] == page_payload["read_endpoint"]

                packages_response = client.get("/api/knowledge/packages", headers=headers)
                assert packages_response.status_code == 200
                source_vault_package = {
                    package["package_id"]: package
                    for package in packages_response.json()["packages"]
                }["source_vault"]
                assert source_vault_package["loaded"] is True
                assert source_vault_package["manifest"]["empty_runtime"] is False
                assert source_vault_package["manifest"]["total_sources"] == 1
                assert source_vault_package["manifest"]["chunk_count"] == 1
                assert source_vault_package["manifest"]["loaded_ref_count"] == 1

                conformance_response = client.get("/api/knowledge/runtime-conformance", headers=headers)
                assert conformance_response.status_code == 200
                source_vault_conformance = {
                    package["package_id"]: package
                    for package in conformance_response.json()["packages"]
                }["source_vault"]
                assert source_vault_conformance["overall_status"] == "proved"
                source_items = {
                    item["requirement"]: item
                    for item in source_vault_conformance["conformance"]
                }
                assert source_items["authoritative_source"]["status"] == "proved"
                assert source_items["structured_runtime_artifact"]["status"] == "proved"
                assert source_items["searchable_index"]["status"] == "proved"
                assert source_items["bounded_context_loading"]["status"] == "proved"
                assert source_items["prompt_assembly_context_receipt"]["status"] == "proved"

                source_vault_search = client.get(
                    "/api/knowledge/source-vault/search",
                    params={"q": "Body from local note", "limit": 1},
                    headers=headers,
                )
                assert source_vault_search.status_code == 200
                source_vault_hit = source_vault_search.json()["results"][0]
                assert source_vault_hit["ref_id"] == page_payload["source_vault_ref_id"]
                assert source_vault_hit["source_id"] == page_payload["source_vault_source_id"]
                assert source_vault_hit["metadata"]["legacy_store"] == "wiki_chunks"
                assert source_vault_hit["metadata"]["legacy_source_id"] == page_payload["source_registry_id"]

                source_vault_resource = client.get(
                    page_payload["source_vault_read_endpoint"],
                    params={"max_chars": 200},
                    headers=headers,
                )
                assert source_vault_resource.status_code == 200
                source_vault_resource_payload = source_vault_resource.json()
                assert source_vault_resource_payload["kind"] == "source_vault"
                assert "Body from local note." in source_vault_resource_payload["content"]
                assert source_vault_resource_payload["metadata"]["source_id"] == page_payload["source_vault_source_id"]
                assert source_vault_resource_payload["metadata"]["legacy_source_id"] == page_payload["source_registry_id"]

                receipt_response = client.post(
                    "/api/knowledge/context-receipt",
                    json={
                        "ref_ids": [page_payload["source_vault_ref_id"]],
                        "prompt_name": "wiki_import_source_vault_loaded_proof",
                        "max_chars_per_ref": 200,
                    },
                    headers=headers,
                )
                assert receipt_response.status_code == 200
                receipt_payload = receipt_response.json()
                assert "Body from local note." in receipt_payload["assembled_context_preview"]
                receipt = receipt_payload["resource_read_receipts"][0]
                assert receipt["ref_id"] == page_payload["source_vault_ref_id"]
                assert receipt["kind"] == "source_vault"
                assert receipt["metadata"]["source_id"] == page_payload["source_vault_source_id"]
                assert receipt["metadata"]["legacy_source_id"] == page_payload["source_registry_id"]
        finally:
            app.dependency_overrides.pop(knowledge_router.get_source_vault, None)


class TestWikiServiceCRUD:
    """G2: WikiService CRUD methods."""

    def test_create_page_generates_slug(self, tmp_path):
        """create_page generates stable slug from title and kind."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(
            title="My Test Page",
            kind="synthesis",
            body="Test content",
        )

        assert page.stable_slug == "synthesis-my-test-page"
        assert page.title == "My Test Page"
        assert page.body == "Test content"
        assert page.kind.value == "synthesis"
        assert page.status.value == "draft"

    def test_create_page_duplicate_raises_error(self, tmp_path):
        """create_page raises ValueError for duplicate slug."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        service.create_page(title="Test", kind="synthesis", body="Content 1")

        with pytest.raises(ValueError, match="already exists"):
            service.create_page(title="Test", kind="synthesis", body="Content 2")

    def test_update_page_modifies_fields(self, tmp_path):
        """update_page modifies specified fields only."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(title="Test", kind="synthesis", body="Original")
        original_created = page.created_at_iso

        updated = service.update_page(page.stable_slug, body="Updated", status="final")

        assert updated.body == "Updated"
        assert updated.status.value == "final"
        assert updated.title == "Test"  # Unchanged
        assert updated.created_at_iso == original_created  # Unchanged
        assert updated.updated_at_iso != original_created  # Changed

    def test_update_page_records_version_history(self, tmp_path):
        """Create/update/delete append local version metadata sidecars."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(title="Versioned", kind="synthesis", body="Original")
        updated = service.update_page(page.stable_slug, body="Updated")
        service.delete_page(updated.stable_slug)

        versions = service.list_page_versions(page.stable_slug)
        assert [item["version"] for item in versions] == [1, 2, 3]
        assert [item["action"] for item in versions] == ["create", "update", "delete"]
        assert versions[0]["body_hash"] != versions[1]["body_hash"]

    def test_delete_page_removes_file(self, tmp_path):
        """delete_page removes page file."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        page = service.create_page(title="Test", kind="synthesis", body="Content")
        page_file = tmp_path / "synthesis" / f"{page.stable_slug}.md"
        assert page_file.exists()

        service.delete_page(page.stable_slug)
        assert not page_file.exists()

    def test_delete_page_not_found_raises_error(self, tmp_path):
        """delete_page raises ValueError for non-existent page."""
        from wiki.service import WikiService
        from wiki.page_store import WikiPageStore

        store = WikiPageStore(tmp_path, create=True)
        service = WikiService(store)

        with pytest.raises(ValueError, match="not found"):
            service.delete_page("nonexistent")

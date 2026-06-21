"""Test G15: Wiki export endpoint (2026-05-26).

Verify POST /api/wiki/export creates Markdown zip archive.
"""

import sys
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Add literature_assistant/core to sys.path
core_path = Path(__file__).parent.parent / "literature_assistant" / "core"
if str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from python_adapter_server import app


@pytest.fixture
def client():
    """TestClient for API testing."""
    return TestClient(app)


@pytest.fixture
def mock_wiki_enabled():
    """Mock wiki_enabled to return True."""
    with patch("routers.wiki_router.wiki_enabled", return_value=True):
        yield


class TestWikiExportEndpoint:
    """G15: POST /api/wiki/export endpoint."""

    def test_export_success_default_path(self, client, mock_wiki_enabled, tmp_path):
        """Successful export with default path returns output_path."""
        with patch("routers.wiki_router._page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
                resp = client.post("/api/wiki/export")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["page_count"] == 0
                assert "wiki_export_" in data["output_path"]
                assert data["errors"] == []

    def test_export_success_custom_path(self, client, mock_wiki_enabled, tmp_path):
        """Successful export with custom filename under wiki_exports."""
        custom_path = tmp_path / "wiki_exports" / "custom_export.zip"

        with patch("routers.wiki_router._page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
                resp = client.post("/api/wiki/export?output_path=custom_export.zip")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["output_path"] == str(custom_path)

    def test_export_success_okf_format(self, client, mock_wiki_enabled, tmp_path):
        """Successful OKF export writes a local compatible bundle archive."""
        from wiki.page_store import WikiPageStore, render_page

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        store = WikiPageStore(tmp_path / "wiki", create=True)
        store.write_rendered(
            render_page(
                Path("synthesis/page1.md"),
                {
                    "id": "synthesis/page1",
                    "kind": "synthesis",
                    "title": "Alpha Synthesis",
                    "status": "final",
                    "description": "A bounded local synthesis.",
                    "updated_at_iso": "2026-06-21T00:00:00Z",
                    "tags": ["rag", "wiki"],
                },
                "# Alpha Synthesis\n\nGrounded local note.",
            )
        )

        with patch("routers.wiki_router._reviewed_page_store", return_value=store):
            with patch("routers.wiki_router.output_path", side_effect=output_root):
                resp = client.post("/api/wiki/export?format=okf&output_path=okf_export.zip")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["page_count"] == 1
        assert data["output_path"] == str(tmp_path / "generated" / "output" / "wiki-okf" / "okf_export.zip")
        with zipfile.ZipFile(data["output_path"], "r") as zf:
            names = set(zf.namelist())
            assert {"index.md", "log.md", "manifest.json", "wiki/synthesis/page1.md"} <= names

    def test_export_okf_default_path_uses_generated_output_root(self, client, mock_wiki_enabled, tmp_path):
        """OKF endpoint default exports belong under workspace_artifacts/generated/output."""

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        with patch("routers.wiki_router._reviewed_page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.output_path", side_effect=output_root):
                resp = client.post("/api/wiki/export?format=okf")

        assert resp.status_code == 200
        data = resp.json()
        expected_root = tmp_path / "generated" / "output" / "wiki-okf"
        assert Path(data["output_path"]).parent == expected_root
        assert Path(data["output_path"]).name.startswith("wiki_okf_export_")
        assert Path(data["output_path"]).suffix == ".zip"

    def test_export_project_okf_endpoint_writes_explicit_records_bundle(self, client, mock_wiki_enabled, tmp_path):
        """Project OKF endpoint exports only caller-provided process artifact records."""
        from wiki.export import parse_okf_frontmatter

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        payload = {
            "output_path": "project_bundle.zip",
            "project_id": "project_abc",
            "materials": [
                {
                    "material_id": "material-1",
                    "title": "Alpha Trial.pdf",
                    "summary": "Registered local material metadata.",
                    "source_path": r"C:\Users\xiao\private\Alpha Trial.pdf",
                    "full_text": "raw paper text",
                    "api_key": "sk-proj-secret",
                }
            ],
            "evidence": [{"evidence_pack_ref": "pack-1", "preview": "Bounded refs."}],
            "answers": [{"conversation_id": "conversation-1", "summary": "Answer summary."}],
            "tasks": [{"task_id": "task-1", "status": "active"}],
            "reviews": [{"review_id": "review-1", "next_action": "Human review pending."}],
            "exports": [{"export_id": "export-1", "filename": "alpha.docx"}],
        }

        with patch("routers.wiki_router.output_path", side_effect=output_root):
            resp = client.post("/api/wiki/export/project-okf", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["success"] is True
        assert data["page_count"] == 6
        assert data["output_path"] == str(tmp_path / "generated" / "output" / "project-okf" / "project_bundle.zip")
        assert data["manifest"]["counts"]["groups"]["materials"] == 1

        with zipfile.ZipFile(data["output_path"], "r") as zf:
            names = set(zf.namelist())
            assert "materials/material-1.md" in names
            bundle_text = "\n".join(zf.read(name).decode("utf-8") for name in names if name.endswith(".md"))
            assert "raw paper text" not in bundle_text
            assert "sk-proj-secret" not in bundle_text
            assert r"C:\Users\xiao" not in bundle_text
            frontmatter, _body = parse_okf_frontmatter(zf.read("materials/material-1.md").decode("utf-8"))
            assert frontmatter["type"] == "scholar-ai-material"
            assert frontmatter["project_id"] == "project_abc"
            assert frontmatter["scholar_ai_record"]["summary"] == "Registered local material metadata."
            assert any(item["reason"] == "private_text" for item in frontmatter["scholar_ai_redactions"])

    def test_export_project_okf_endpoint_collects_safe_live_project_records(self, client, mock_wiki_enabled, tmp_path):
        """Live project collection exports bounded local metadata without raw private content."""
        from wiki.export import parse_okf_frontmatter
        from wiki.review_queue import ReviewItem, ReviewItemKind, ReviewItemStatus
        from writing_resources import WritingResourceStore

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        store = WritingResourceStore()
        project = store.create_project("Alpha Project", description="Project summary.", tags=["local"])
        material = store.create_material(
            project_id=project.project_id,
            title="Alpha Trial.pdf",
            summary="Registered local material metadata.",
            metadata={"source_path": r"C:\Users\xiao\private\Alpha Trial.pdf"},
        )
        draft = store.create_draft(
            project_id=project.project_id,
            title="Alpha Answer Draft",
            content="raw answer body must not be exported",
            citation_anchors=[
                {
                    "id": "anchor-1",
                    "materialId": material.material_id,
                    "token": "[1]",
                    "startOffset": 0,
                    "endOffset": 3,
                    "ordinal": 1,
                }
            ],
        )
        asset = store.create_figure_asset(
            project_id=project.project_id,
            kind="figure",
            caption="Alpha figure",
            numbering="Figure 1",
            asset_path=r"C:\Users\xiao\private\figure.png",
            material_id=material.material_id,
            source_page=2,
            width=640,
            height=480,
            format="png",
        )
        review_item = ReviewItem(
            item_id="review-live-1",
            kind=ReviewItemKind.warning,
            title="Alpha review",
            page_path="wiki/synthesis/alpha.md",
            summary="Human review pending.",
            status=ReviewItemStatus.pending,
            created_at="2026-06-21T00:00:00+00:00",
            source="wiki",
            metadata={"project_id": project.project_id},
        )
        chunk_store = {
            material.material_id: [
                {
                    "chunk_id": "chunk-alpha-1",
                    "material_id": material.material_id,
                    "title": "Alpha Trial.pdf",
                    "page": 3,
                    "chunk_type": "body",
                    "text": "raw chunk body must not be exported",
                    "source_relative_path": "source_files/alpha.pdf",
                }
            ]
        }
        payload = {
            "output_path": "live_project_bundle.zip",
            "project_id": project.project_id,
            "include_live_project_records": True,
            "max_live_records": 20,
            "tasks": [{"task_id": "explicit-task-1", "status": "active"}],
        }

        with patch("routers.resources_router.get_writing_resource_store", return_value=store):
            with patch("routers.resources_router._load_chunk_store", return_value=chunk_store):
                with patch("routers.wiki_router.ReviewQueue") as review_queue_cls:
                    review_queue_cls.return_value.list_items.return_value = [review_item]
                    with patch("routers.wiki_router.output_path", side_effect=output_root):
                        resp = client.post("/api/wiki/export/project-okf", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["page_count"] == 6
        assert data["manifest"]["counts"]["groups"] == {
            "answers": 1,
            "evidence": 1,
            "exports": 1,
            "materials": 1,
            "reviews": 1,
            "tasks": 1,
        }
        assert any("live project records" in warning for warning in data["warnings"])

        with zipfile.ZipFile(data["output_path"], "r") as zf:
            names = set(zf.namelist())
            assert f"materials/{material.material_id}.md" in names
            assert "evidence/chunk-alpha-1.md" in names
            assert f"answers/{draft.draft_id}.md" in names
            assert "reviews/review-live-1.md" in names
            assert f"exports/{asset.asset_id}.md" in names
            bundle_text = "\n".join(zf.read(name).decode("utf-8") for name in sorted(names) if name.endswith(".md"))
            assert "raw answer body must not be exported" not in bundle_text
            assert "raw chunk body must not be exported" not in bundle_text
            assert r"C:\Users\xiao" not in bundle_text
            material_frontmatter, _body = parse_okf_frontmatter(
                zf.read(f"materials/{material.material_id}.md").decode("utf-8")
            )
            assert material_frontmatter["material_id"] == material.material_id
            answer_frontmatter, _body = parse_okf_frontmatter(
                zf.read(f"answers/{draft.draft_id}.md").decode("utf-8")
            )
            assert answer_frontmatter["scholar_ai_record"]["citation_anchor_count"] == 1

    def test_export_project_okf_endpoint_collects_runtime_metadata_without_private_text(
        self,
        client,
        mock_wiki_enabled,
        tmp_path,
    ):
        """Live runtime collection exports chat and agent metadata without raw bodies."""
        import discussion_task_store as discussion_task_store_module
        from literature_assistant.core.chat.history_store import ChatHistoryStore
        from wiki.export import parse_okf_frontmatter
        from writing_resources import WritingResourceStore

        class _EnumValue:
            def __init__(self, value: str):
                self.value = value

        class _FakeSession:
            session_id = "session-alpha"
            metadata = {"project_id": "unused"}

        class _FakeJob:
            job_id = "job-alpha"
            session_id = "session-alpha"
            kind = _EnumValue("agent_request")
            status = _EnumValue("completed")
            input_text = "raw agent prompt must not be exported"
            created_at = "2026-06-21T01:00:00Z"
            started_at = "2026-06-21T01:01:00Z"
            completed_at = "2026-06-21T01:02:00Z"
            metadata: dict[str, object] = {}

        class _FakeArtifact:
            artifact_type = _EnumValue("metadata")
            content = "raw runtime artifact body must not be exported"
            metadata = {"private_path": r"C:\Users\xiao\private\artifact.md"}

        class _FakeRuntime:
            def __init__(self, job: _FakeJob):
                self.job = job

            def list_sessions(self, include_archived: bool = False) -> list[_FakeSession]:
                assert include_archived is True
                return [_FakeSession()]

            def list_jobs(self, session_id: str):
                assert session_id == "session-alpha"
                return [self.job]

            def get_job_artifacts(self, job_id: str):
                assert job_id == "job-alpha"
                return [_FakeArtifact()]

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        store = WritingResourceStore()
        project = store.create_project("Runtime Project", description="Project summary.")
        chat_db = tmp_path / "chat-history" / "chat_history.db"
        chat_store = ChatHistoryStore(chat_db)
        chat_store.create_conversation(
            conversation_id="conversation-runtime",
            project_id=project.project_id,
            title="Runtime Chat",
            mode="literature_qa",
            created_at="2026-06-21T00:00:00Z",
        )
        chat_store.append_node(
            conversation_id="conversation-runtime",
            node_id="node-runtime-answer",
            role="assistant",
            node_type="message",
            created_at="2026-06-21T00:01:00Z",
            content_text="raw chat transcript must not be exported",
            evidence_refs=[
                {
                    "chunk_id": "chunk-secret",
                    "material_id": "material-secret",
                    "quote": "raw evidence quote must not be exported",
                }
            ],
        )
        job = _FakeJob()
        job.metadata = {
            "agent_bridge": True,
            "agent_request_id": "agentreq-alpha",
            "project_id": project.project_id,
            "intent": "single_paper_deep_read",
            "agent_host": "mcp",
            "source": "mcp",
            "resource_refs": [{"ref_id": "material:alpha"}],
            "evidence_refs": [{"ref_id": "chunk-secret"}],
            "wiki_refs": [{"slug": "alpha"}],
            "graph_patch_refs": [{"id": "edge-alpha"}],
            "metadata": {
                "task_id": "paper_task_alpha",
                "task_schema_version": "scholar-ai-single-paper-task/v1",
                "task_title": "Alpha Trial",
                "missing_fields": ["doi"],
                "task_manifest": {
                    "task_id": "paper_task_alpha",
                    "paper": {"title": "Alpha Trial", "doi": "待补充"},
                },
            },
            "agent_result_ready": True,
            "agent_result": {"text": "raw final agent result must not be exported"},
            "knowledge_consumers": {
                "wiki": {"status": "created"},
                "graph": {"status": "metadata_only"},
                "evolution": {"status": "scheduled"},
            },
        }
        discussion_store = discussion_task_store_module.DiscussionTaskStore(
            persistence_path=tmp_path / "discussion" / "tasks.json",
        )
        discussion_store.register(
            "discussion-alpha",
            config={
                "project_id": project.project_id,
                "query": "Discuss alpha evidence",
                "agents": [{"id": "reviewer"}],
                "evidence_mode": "from_project",
                "evidence_top_k": 3,
            },
        )
        discussion_store.append_event(
            "discussion-alpha",
            {
                "event": "agent_done",
                "turn_index": 1,
                "trace": {"answer": "raw discussion trace must not be exported"},
            },
        )
        discussion_store.append_event(
            "discussion-alpha",
            {
                "event": "done",
                "result": {"final_answer": "raw discussion final answer must not be exported"},
            },
        )
        payload = {
            "output_path": "runtime_metadata_bundle.zip",
            "project_id": project.project_id,
            "include_live_project_records": True,
            "max_live_records": 20,
        }

        with patch("routers.resources_router.get_writing_resource_store", return_value=store):
            with patch("routers.resources_router._load_chunk_store", return_value={}):
                with patch("routers.wiki_router.ReviewQueue") as review_queue_cls:
                    review_queue_cls.return_value.list_items.return_value = []
                    with patch(
                        "literature_assistant.core.chat.history_store.default_chat_history_db_path",
                        return_value=chat_db,
                    ):
                        with patch("routers.agent_bridge_router.get_runtime", return_value=(_FakeRuntime(job), object())):
                            with patch.object(
                                discussion_task_store_module,
                                "get_discussion_task_store",
                                return_value=discussion_store,
                            ):
                                with patch("routers.wiki_router.output_path", side_effect=output_root):
                                    resp = client.post("/api/wiki/export/project-okf", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["page_count"] == 4
        assert data["manifest"]["counts"]["groups"] == {"answers": 3, "tasks": 1}

        with zipfile.ZipFile(data["output_path"], "r") as zf:
            names = set(zf.namelist())
            assert "answers/conversation-runtime.md" in names
            assert "answers/job-alpha.md" in names
            assert "answers/discussion-alpha.md" in names
            assert "tasks/paper_task_alpha.md" in names
            bundle_text = "\n".join(zf.read(name).decode("utf-8") for name in sorted(names) if name.endswith(".md"))
            assert "raw chat transcript must not be exported" not in bundle_text
            assert "raw evidence quote must not be exported" not in bundle_text
            assert "raw agent prompt must not be exported" not in bundle_text
            assert "raw final agent result must not be exported" not in bundle_text
            assert "raw runtime artifact body must not be exported" not in bundle_text
            assert "raw discussion trace must not be exported" not in bundle_text
            assert "raw discussion final answer must not be exported" not in bundle_text
            assert r"C:\Users\xiao" not in bundle_text
            chat_frontmatter, _body = parse_okf_frontmatter(
                zf.read("answers/conversation-runtime.md").decode("utf-8")
            )
            assert chat_frontmatter["scholar_ai_record"]["node_count"] == 1
            assert chat_frontmatter["scholar_ai_record"]["evidence_ref_count"] == 1
            task_frontmatter, _body = parse_okf_frontmatter(
                zf.read("tasks/paper_task_alpha.md").decode("utf-8")
            )
            assert task_frontmatter["scholar_ai_record"]["single_paper_task"] is True
            assert task_frontmatter["scholar_ai_record"]["resource_ref_count"] == 1
            discussion_frontmatter, _body = parse_okf_frontmatter(
                zf.read("answers/discussion-alpha.md").decode("utf-8")
            )
            assert discussion_frontmatter["scholar_ai_record"]["agent_count"] == 1
            assert discussion_frontmatter["scholar_ai_record"]["live_trace_count"] == 1
            assert discussion_frontmatter["scholar_ai_record"]["has_final_result"] is True

    def test_export_project_okf_endpoint_requires_project_for_live_collection(self, client, mock_wiki_enabled, tmp_path):
        """Live project collection is project-scoped and cannot run globally."""

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        with patch("routers.wiki_router.output_path", side_effect=output_root):
            resp = client.post("/api/wiki/export/project-okf", json={"include_live_project_records": True})

        assert resp.status_code == 400
        assert "project_id is required" in json.dumps(resp.json(), ensure_ascii=False)

    def test_export_project_okf_endpoint_rejects_unsafe_output_path(self, client, mock_wiki_enabled, tmp_path):
        """Project OKF output_path is a filename, not an arbitrary local write path."""

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        with patch("routers.wiki_router.output_path", side_effect=output_root):
            resp = client.post("/api/wiki/export/project-okf", json={"output_path": "../escape.zip"})

        assert resp.status_code == 400

    def test_export_project_okf_endpoint_disabled_does_not_write_archive(self, client, tmp_path):
        """Disabled wiki returns a bounded response without creating project OKF files."""

        def output_root(*parts: str) -> Path:
            return tmp_path.joinpath("generated", "output", *parts)

        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            with patch("routers.wiki_router.output_path", side_effect=output_root):
                resp = client.post("/api/wiki/export/project-okf", json={"materials": [{"material_id": "m1"}]})

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["success"] is False
        assert data["warnings"]
        assert not (tmp_path / "generated" / "output" / "project-okf").exists()

    def test_export_rejects_path_traversal_output_path(self, client, mock_wiki_enabled, tmp_path):
        """Endpoint output_path is a filename only, not an arbitrary write path."""
        with patch("routers.wiki_router._page_store") as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.list_pages.return_value = []

            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
                resp = client.post("/api/wiki/export?output_path=../escape.zip")

        assert resp.status_code == 400

    def test_export_wiki_disabled(self, client):
        """Export when wiki disabled returns 404."""
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.post("/api/wiki/export")
            assert resp.status_code == 404


class TestWikiOkfInspectEndpoint:
    """Read-only OKF import planning endpoint."""

    def test_okf_inspect_validates_local_archive_without_import(self, client, mock_wiki_enabled, tmp_path):
        """A local OKF zip can be inspected without exposing absolute paths."""
        archive_path = tmp_path / "okf" / "good.zip"
        archive_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "wiki/page.md",
                "---\ntype: scholar-ai-wiki-page\ntitle: Local Page\n---\n\n# Local Page\n",
            )

        with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path):
            resp = client.post("/api/wiki/import/okf/inspect", json={"archive_path": str(archive_path)})

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["dry_run"] is True
        assert data["archive_path"] == "okf/good.zip"
        assert data["inspection"]["archive_path"] == "okf/good.zip"
        assert data["inspection"]["success"] is True
        assert data["inspection"]["concept_count"] == 1

    def test_okf_inspect_disabled_does_not_read_archive(self, client, tmp_path):
        """Disabled wiki returns a bounded warning instead of reading local files."""
        missing_path = tmp_path / "missing.zip"
        with patch("routers.wiki_router.wiki_enabled", return_value=False):
            resp = client.post("/api/wiki/import/okf/inspect", json={"archive_path": str(missing_path)})

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["dry_run"] is True
        assert data["inspection"] == {}
        assert data["warnings"]

    def test_okf_inspect_rejects_github_reference_archives(self, client, mock_wiki_enabled, tmp_path):
        """The inspect endpoint must not turn read-only reference repos into import sources."""
        archive_path = tmp_path / "github" / "reference.zip"
        archive_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("wiki/page.md", "---\ntype: scholar-ai-wiki-page\n---\n\nBody.\n")

        with patch("routers.wiki_router.REPO_ROOT", tmp_path):
            with patch("routers.wiki_router.WORKSPACE_ARTIFACTS_ROOT", tmp_path / "workspace_artifacts"):
                with patch("routers.wiki_router.WORKSPACE_REFERENCES_ROOT", tmp_path / "workspace_references"):
                    resp = client.post("/api/wiki/import/okf/inspect", json={"archive_path": str(archive_path)})

        assert resp.status_code == 400
        assert "protected workspace area" in json.dumps(resp.json(), ensure_ascii=False)


class TestWikiExportFunction:
    """G15: export_wiki_markdown function."""

    def test_export_creates_zip_with_pages(self, tmp_path):
        """export_wiki_markdown creates zip with all pages."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        # Create test pages
        store = WikiPageStore(tmp_path / "wiki", create=True)
        (tmp_path / "wiki" / "synthesis").mkdir(parents=True)
        (tmp_path / "wiki" / "synthesis" / "page1.md").write_text("# Page 1\nContent 1")
        (tmp_path / "wiki" / "concept").mkdir(parents=True)
        (tmp_path / "wiki" / "concept" / "page2.md").write_text("# Page 2\nContent 2")

        # Export
        output_path = tmp_path / "export.zip"
        result = export_wiki_markdown(store, output_path)

        assert result["success"] is True
        assert result["page_count"] == 2
        assert result["output_path"] == str(output_path)
        assert result["errors"] == []

        # Verify zip contents
        assert output_path.exists()
        with zipfile.ZipFile(output_path, "r") as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            assert "synthesis/page1.md" in names
            assert "concept/page2.md" in names
            assert zf.read("synthesis/page1.md").decode() == "# Page 1\nContent 1"
            assert zf.read("concept/page2.md").decode() == "# Page 2\nContent 2"
            manifest = json.loads(zf.read("manifest.json").decode())
            assert manifest["schema_version"] == "wiki_export_bundle_manifest_v1"
            assert manifest["bundle"]["kind"] == "wiki_markdown_page_bundle"
            assert manifest["counts"]["pages"] == 2
            assert sorted(page["path"] for page in manifest["pages"]) == [
                "concept/page2.md",
                "synthesis/page1.md",
            ]

    def test_export_empty_wiki(self, tmp_path):
        """export_wiki_markdown handles empty wiki."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        store = WikiPageStore(tmp_path / "wiki", create=True)
        output_path = tmp_path / "export.zip"

        result = export_wiki_markdown(store, output_path)

        assert result["success"] is True
        assert result["page_count"] == 0
        assert output_path.exists()

    def test_export_creates_parent_directory(self, tmp_path):
        """export_wiki_markdown creates parent directory if missing."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        store = WikiPageStore(tmp_path / "wiki", create=True)
        output_path = tmp_path / "nested" / "dir" / "export.zip"

        result = export_wiki_markdown(store, output_path)

        assert result["success"] is True
        assert output_path.exists()
        assert output_path.parent.exists()

    def test_export_rejects_directory_path(self, tmp_path):
        """export_wiki_markdown raises ValueError for directory path."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown

        store = WikiPageStore(tmp_path / "wiki", create=True)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with pytest.raises(ValueError, match="must be a file path"):
            export_wiki_markdown(store, output_dir)

    def test_export_okf_bundle_converts_wiki_pages(self, tmp_path):
        """export_wiki_okf_bundle writes OKF YAML frontmatter without mutating pages."""
        from wiki.export import export_wiki_okf_bundle, inspect_okf_bundle_archive, parse_okf_frontmatter
        from wiki.page_store import WikiPageStore, render_page

        store = WikiPageStore(tmp_path / "wiki", create=True)
        store.write_rendered(
            render_page(
                Path("synthesis/page1.md"),
                {
                    "id": "synthesis/page1",
                    "kind": "synthesis",
                    "title": "Alpha Synthesis",
                    "status": "final",
                    "description": "A bounded local synthesis.",
                    "updated_at_iso": "2026-06-21T00:00:00Z",
                    "tags": ["rag", "wiki"],
                    "evidence_refs": [{"chunk_id": "chunk-1", "material_id": "material-1"}],
                },
                "# Alpha Synthesis\n\nGrounded local note.",
            )
        )

        output_path = tmp_path / "okf.zip"
        result = export_wiki_okf_bundle(
            store,
            output_path,
            project_id="project_abc",
            generated_at_iso="2026-06-21T01:02:03Z",
        )

        assert result["success"] is True
        assert result["page_count"] == 1
        assert output_path.exists()
        with zipfile.ZipFile(output_path, "r") as zf:
            names = set(zf.namelist())
            assert {"index.md", "log.md", "manifest.json", "wiki/synthesis/page1.md"} <= names
            frontmatter, body = parse_okf_frontmatter(zf.read("wiki/synthesis/page1.md").decode("utf-8"))
            assert frontmatter["type"] == "scholar-ai-wiki-page"
            assert frontmatter["schema_version"] == "scholar-ai-okf-profile/v1"
            assert frontmatter["okf_version"] == "0.1"
            assert frontmatter["project_id"] == "project_abc"
            assert frontmatter["wiki_path"] == "synthesis/page1.md"
            assert frontmatter["scholar_ai_frontmatter"]["id"] == "synthesis/page1"
            assert "literature-assistant:auto:start" not in body
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest["schema_version"] == "scholar-ai-okf-bundle-manifest/v1"
            assert manifest["counts"]["concepts"] == 1

        inspection = inspect_okf_bundle_archive(output_path)
        assert inspection["success"] is True
        assert inspection["concept_count"] == 1
        assert inspection["errors"] == []

    def test_export_project_artifact_okf_bundle_covers_process_record_groups(self, tmp_path):
        """Project artifact OKF export covers contract groups without reading live stores."""
        from wiki.export import (
            export_project_artifact_okf_bundle,
            inspect_okf_bundle_archive,
            parse_okf_frontmatter,
        )

        output_path = tmp_path / "project-okf.zip"
        result = export_project_artifact_okf_bundle(
            {
                "materials": [
                    {
                        "material_id": "material-1",
                        "title": "Alpha Trial.pdf",
                        "summary": "Registered local material metadata.",
                        "source_path": r"C:\Users\xiao\private\Alpha Trial.pdf",
                        "full_text": "raw full paper body must not be exported",
                        "api_key": "sk-proj-secret",
                        "tags": ["paper"],
                    }
                ],
                "evidence": [
                    {
                        "evidence_pack_ref": "pack-1",
                        "query": "alpha endpoint",
                        "preview": "Two bounded evidence refs.",
                        "chunk_text": "chunk body must not be exported",
                    }
                ],
                "answers": [
                    {
                        "conversation_id": "conversation-1",
                        "title": "Answer about Alpha",
                        "summary": "Bounded answer summary.",
                        "raw_provider_payload": {"choices": [{"text": "provider internals"}]},
                    }
                ],
                "tasks": [
                    {
                        "task_id": "task-1",
                        "task_goal": "Single paper deep read",
                        "status": "active",
                        "private_path_ref": r"C:\Users\xiao\papers\alpha.pdf",
                    }
                ],
                "reviews": [
                    {
                        "review_id": "review-1",
                        "page_path": "wiki/synthesis/alpha.md",
                        "next_action": "Human review pending.",
                        "token": "private-token",
                    }
                ],
                "exports": [
                    {
                        "export_id": "export-1",
                        "filename": "alpha.docx",
                        "description": "DOCX export metadata.",
                        "file_path": r"C:\Users\xiao\exports\alpha.docx",
                    }
                ],
            },
            output_path,
            project_id="project_abc",
            generated_at_iso="2026-06-21T02:03:04Z",
        )

        assert result["success"] is True
        assert result["page_count"] == 6
        assert result["errors"] == []
        assert result["manifest"]["counts"]["groups"] == {
            "answers": 1,
            "evidence": 1,
            "exports": 1,
            "materials": 1,
            "reviews": 1,
            "tasks": 1,
        }

        with zipfile.ZipFile(output_path, "r") as zf:
            names = set(zf.namelist())
            assert {
                "index.md",
                "log.md",
                "manifest.json",
                "materials/material-1.md",
                "evidence/pack-1.md",
                "answers/conversation-1.md",
                "tasks/task-1.md",
                "reviews/review-1.md",
                "exports/export-1.md",
            } <= names
            bundle_text = "\n".join(zf.read(name).decode("utf-8") for name in sorted(names) if name.endswith(".md"))
            assert "raw full paper body must not be exported" not in bundle_text
            assert "chunk body must not be exported" not in bundle_text
            assert "provider internals" not in bundle_text
            assert "sk-proj-secret" not in bundle_text
            assert r"C:\Users\xiao" not in bundle_text

            frontmatter, body = parse_okf_frontmatter(zf.read("materials/material-1.md").decode("utf-8"))
            assert frontmatter["type"] == "scholar-ai-material"
            assert frontmatter["project_id"] == "project_abc"
            assert frontmatter["material_id"] == "material-1"
            assert frontmatter["schema_version"] == "scholar-ai-okf-profile/v1"
            assert frontmatter["scholar_ai_record"]["summary"] == "Registered local material metadata."
            assert "source_path" not in frontmatter["scholar_ai_record"]
            assert "full_text" not in frontmatter["scholar_ai_record"]
            assert "api_key" not in frontmatter["scholar_ai_record"]
            assert any(item["reason"] == "private_path" for item in frontmatter["scholar_ai_redactions"])
            assert "Safe Metadata" in body

        inspection = inspect_okf_bundle_archive(output_path)
        assert inspection["success"] is True
        assert inspection["concept_count"] == 6
        assert sorted(document["type"] for document in inspection["documents"]) == [
            "scholar-ai-answer",
            "scholar-ai-evidence",
            "scholar-ai-export",
            "scholar-ai-material",
            "scholar-ai-review",
            "scholar-ai-task",
        ]

    def test_export_project_artifact_okf_bundle_rejects_unknown_groups(self, tmp_path):
        """Only documented Scholar AI process artifact groups can be exported."""
        from wiki.export import export_project_artifact_okf_bundle

        with pytest.raises(ValueError, match="unsupported OKF project record group"):
            export_project_artifact_okf_bundle({"unknown": []}, tmp_path / "project-okf.zip")

    def test_validate_okf_document_warns_for_soft_conformance_gaps(self):
        """OKF validation warns for optional fields and broken links without failing."""
        from wiki.export import validate_okf_markdown_document

        text = "---\ntype: scholar-ai-wiki-page\n---\n\nSee [Missing](missing.md).\n"
        result = validate_okf_markdown_document("wiki/page.md", text, known_paths={"wiki/page.md"})

        assert result["errors"] == []
        assert any("optional frontmatter field" in warning for warning in result["warnings"])
        assert any("link target is not present" in warning for warning in result["warnings"])

    def test_validate_okf_document_errors_without_type(self):
        """OKF validation treats missing type as a hard conformance error."""
        from wiki.export import validate_okf_markdown_document

        text = "---\ntitle: Missing type\n---\n\nBody.\n"
        result = validate_okf_markdown_document("wiki/missing-type.md", text)

        assert any("requires non-empty frontmatter field: type" in error for error in result["errors"])

    def test_inspect_okf_bundle_archive_reports_unsafe_member(self, tmp_path):
        """OKF archive inspection is read-only and rejects escaping zip members."""
        from wiki.export import inspect_okf_bundle_archive

        archive_path = tmp_path / "unsafe.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("../escape.md", "---\ntype: scholar-ai-wiki-page\n---\n\nBody.\n")

        inspection = inspect_okf_bundle_archive(archive_path)

        assert inspection["success"] is False
        assert any("must stay inside the bundle" in error for error in inspection["errors"])

    def test_export_handles_read_errors(self, tmp_path):
        """export_wiki_markdown continues on individual page read errors."""
        from wiki.page_store import WikiPageStore
        from wiki.export import export_wiki_markdown
        from unittest.mock import MagicMock

        store = WikiPageStore(tmp_path / "wiki", create=True)
        (tmp_path / "wiki" / "synthesis").mkdir(parents=True)
        (tmp_path / "wiki" / "synthesis" / "page1.md").write_text("Content 1")

        # Mock read_page to fail for one page
        original_read = store.read_page
        def mock_read(path):
            if "page1" in str(path):
                raise IOError("Read failed")
            return original_read(path)
        store.read_page = mock_read

        output_path = tmp_path / "export.zip"
        result = export_wiki_markdown(store, output_path)

        assert result["success"] is False
        assert result["page_count"] == 0
        assert len(result["errors"]) > 0
        assert "Read failed" in result["errors"][0]

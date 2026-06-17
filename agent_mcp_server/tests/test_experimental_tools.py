"""Tests for disabled-by-default experimental MCP tools."""

import base64
from pathlib import Path
from typing import Any

import pytest

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.tools.experimental import ExperimentalTools


class FakeRuntimeTools:
    """Runtime tool fake used by experiment wrappers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_materials(self, project_id: str) -> dict[str, Any]:
        self.calls.append(("list_materials", {"project_id": project_id}))
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": [{"material_id": "mat-1", "title": "Paper 1", "summary": "Alpha summary"}],
        }

    def search_literature(self, project_id: str, query: str, top_k: int = 10) -> dict[str, Any]:
        self.calls.append(("search_literature", {"project_id": project_id, "query": query, "top_k": top_k}))
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": {
                "project_id": project_id,
                "query": query,
                "results": [
                    {
                        "material_id": "mat-1",
                        "chunk_id": "chunk-1",
                        "title": "Paper 1",
                        "content": "This is source text.",
                        "score": 1.0,
                    }
                ],
            },
        }

    def get_material_file_base64(self, material_id: str) -> dict[str, Any]:
        self.calls.append(("get_material_file_base64", {"material_id": material_id}))
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": {
                "data": base64.b64encode(b"hello sk-ant-" + b"api" + b"A" * 60).decode("ascii"),
                "size": 65,
                "mime": "text/plain",
                "name": "note.txt",
            },
        }

    def list_figure_table_candidates(
        self,
        project_id: str,
        limit: int = 20,
        pixel_only: bool = False,
        render_pdf_fallback: bool = True,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "list_figure_table_candidates",
                {
                    "project_id": project_id,
                    "limit": limit,
                    "pixel_only": pixel_only,
                    "render_pdf_fallback": render_pdf_fallback,
                },
            )
        )
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": [{"id": "fig-1", "kind": "figure", "caption": "Figure 1"}],
        }

    def chat_ask(
        self,
        query: str,
        context: list[str] | None = None,
        project_id: str | None = None,
        ai_cost_profile: str = "aggressive",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "chat_ask",
                {
                    "query": query,
                    "context": context or [],
                    "project_id": project_id,
                    "ai_cost_profile": ai_cost_profile,
                },
            )
        )
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": {"answer": "# 中文翻译\n\n译文", "model": "test-chat"},
        }


def make_tools(tmp_path: Path, enabled: bool = False) -> ExperimentalTools:
    """Create experimental tools with a temp artifact root."""

    return ExperimentalTools(
        repo_root=tmp_path,
        runtime=FakeRuntimeTools(),
        audit=AuditLog(tmp_path / "workspace_artifacts/agent_mcp_workflows/.audit"),
        enabled=enabled,
    )


def test_experimental_tools_disabled_by_default(tmp_path: Path) -> None:
    """High-risk tools return structured disabled errors until explicitly enabled."""

    tools = make_tools(tmp_path, enabled=False)

    assert tools.ocr_material("mat-1")["error_code"] == "experimental_tools_disabled"
    assert tools.prepare_visual_review("project-1", "query")["error_code"] == "experimental_tools_disabled"
    assert tools.translate_pack("project-1", "中文")["error_code"] == "experimental_tools_disabled"
    assert tools.run_python_sandbox({"code": "print('x')"})["error_code"] == "experimental_tools_disabled"
    assert tools.export_project_pack("project-1")["error_code"] == "experimental_tools_disabled"


def test_run_python_sandbox_executes_bounded_pure_python(tmp_path: Path) -> None:
    """Enabled Python sandbox supports small pure-compute scripts."""

    tools = make_tools(tmp_path, enabled=True)

    result = tools.run_python_sandbox(
        {
            "code": "import math\nresult = {'total': sum(input_data['items']), 'root': math.sqrt(16)}",
            "input_data": {"items": [1, 2, 3]},
            "timeout_sec": 5,
        }
    )

    assert result["is_error"] is False
    assert result["data"]["run"]["result"] == {"total": 6, "root": 4.0}


@pytest.mark.parametrize(
    "code, expected",
    [
        ("import os\nresult = os.getcwd()", "import not allowed"),
        ("import subprocess\nresult = 1", "import not allowed"),
        ("result = open('x.txt', 'w')", "call not allowed"),
        ("result = (1).__class__", "attribute not allowed"),
    ],
)
def test_run_python_sandbox_blocks_dangerous_code(
    tmp_path: Path,
    code: str,
    expected: str,
) -> None:
    """Sandbox blocks filesystem, shell, and object-introspection escapes."""
    tools = make_tools(tmp_path, enabled=True)

    result = tools.run_python_sandbox({"code": code})

    assert result["is_error"] is True
    assert result["error_code"] == "python_sandbox_failed"
    assert expected in result["message"]


def test_export_project_pack_writes_redacted_artifact_when_enabled(tmp_path: Path) -> None:
    """The first enabled Slice 6 tool only writes a local metadata pack."""

    tools = make_tools(tmp_path, enabled=True)

    result = tools.export_project_pack("project-1", include_search_preview=True, query="secret sk-" + "test1234567890")

    assert result["is_error"] is False
    assert result["data"]["path"].endswith(".json")
    artifact_path = tmp_path / "workspace_artifacts/agent_mcp_workflows" / result["data"]["path"]
    assert artifact_path.exists()
    text = artifact_path.read_text(encoding="utf-8")
    assert "sk-test" not in text
    assert "project-1" in text


def test_ocr_material_text_file_writes_redacted_artifact(tmp_path: Path) -> None:
    """OCR tool can process backend-served text files and redact output."""
    tools = make_tools(tmp_path, enabled=True)

    result = tools.ocr_material("mat-1")

    assert result["is_error"] is False
    artifact_path = tmp_path / "workspace_artifacts/agent_mcp_workflows" / result["data"]["path"]
    text = artifact_path.read_text(encoding="utf-8")
    assert "sk-ant-api" not in text
    assert "hello" in text


def test_prepare_visual_review_includes_backend_candidates(tmp_path: Path) -> None:
    """Visual review pack combines retrieval and backend-prepared candidates."""
    tools = make_tools(tmp_path, enabled=True)

    result = tools.prepare_visual_review("project-1", "figure layout", top_k=3)

    assert result["is_error"] is False
    artifact_path = tmp_path / "workspace_artifacts/agent_mcp_workflows" / result["data"]["path"]
    payload = artifact_path.read_text(encoding="utf-8")
    assert "visual_review_pack" in payload
    assert "fig-1" in payload


def test_translate_pack_uses_backend_chat_and_writes_markdown(tmp_path: Path) -> None:
    """Translation pack delegates model spend to backend chat and writes artifacts."""
    tools = make_tools(tmp_path, enabled=True)

    result = tools.translate_pack("project-1", "中文", query="source text", top_k=2, use_model=True)

    assert result["is_error"] is False
    markdown = tmp_path / "workspace_artifacts/agent_mcp_workflows" / result["data"]["markdown"]["path"]
    assert markdown.read_text(encoding="utf-8").startswith("# 中文翻译")

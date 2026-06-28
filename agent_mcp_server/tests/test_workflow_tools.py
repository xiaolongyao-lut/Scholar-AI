"""Tests for controlled workflow and artifact tools."""

from pathlib import Path
from typing import Any

import pytest

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.tools.workflow import WorkflowTools
from lit_assistant_mcp.workflow_runtime.expressions import ExpressionEvaluator
from lit_assistant_mcp.workflow_runtime.workspace import ArtifactWorkspace


def _ok(data: Any) -> dict[str, Any]:
    return {"is_error": False, "error_code": None, "message": None, "data": data}


def test_expression_evaluator_select_map_filter_group_join_template() -> None:
    """Expression subset supports bounded workflow data shaping."""
    evaluator = ExpressionEvaluator()
    context = {
        "input": {},
        "vars": {},
        "steps": {
            "search": {
                "result": {
                    "data": {
                        "matches": [
                            {"title": "Alpha", "score": 0.9, "group": "a"},
                            {"title": "Beta", "score": 0.3, "group": "b"},
                            {"title": "Again", "score": 0.7, "group": "a"},
                        ]
                    }
                }
            }
        },
    }

    selected = evaluator.evaluate("$steps.search.result.data.matches", context)
    filtered = evaluator.evaluate(
        {
            "$filter": {
                "from": "$steps.search.result.data.matches",
                "where": {"field": "$vars.item.score", "op": ">=", "value": 0.7},
            }
        },
        context,
    )
    mapped = evaluator.evaluate(
        {
            "$map": {
                "from": {"$select": "$steps.search.result.data.matches"},
                "template": {"$template": {"template": "- {title}", "vars": {"title": "$vars.item.title"}}},
            }
        },
        context,
    )
    grouped = evaluator.evaluate(
        {"$groupBy": {"from": "$steps.search.result.data.matches", "key": "$vars.item.group"}},
        context,
    )
    joined = evaluator.evaluate({"$join": {"items": mapped, "separator": "\n"}}, context)

    assert len(selected) == 3
    assert [item["title"] for item in filtered] == ["Alpha", "Again"]
    assert "- Alpha" in joined
    assert {group["key"] for group in grouped} == {"a", "b"}


def test_artifact_workspace_blocks_traversal_and_audit_read(tmp_path: Path) -> None:
    """Artifact paths must stay inside the workflow artifact root."""
    workspace = ArtifactWorkspace(repo_root=tmp_path)
    workspace.write_text("reports/one.md", "hello", overwrite=False)

    assert workspace.read_text("reports/one.md")["content"] == "hello"
    with pytest.raises(ValueError):
        workspace.write_text("../escape.md", "nope")
    with pytest.raises(ValueError):
        workspace.read_text(".audit/2026-01-01.jsonl")


def test_create_plan_returns_skeleton_without_artifact_write(tmp_path: Path) -> None:
    """Plan skeleton generation must not create workflow artifacts."""
    tools = WorkflowTools(
        workspace=ArtifactWorkspace(repo_root=tmp_path),
        tool_registry={"mock.ok": lambda: _ok({"ok": True})},
    )

    result = tools.create_plan("Check local workflow")

    assert result["is_error"] is False
    assert result["data"]["workflow"]["id"] == "check-local-workflow"
    assert result["data"]["allowed_tools"] == ["mock.ok"]
    assert tools.workspace.list_artifacts() == []


def test_write_json_workflow_stays_bounded_and_controls_overwrite(tmp_path: Path) -> None:
    """JSON workflow writes stay under the artifact workspace and gate replacement."""
    tools = WorkflowTools(
        workspace=ArtifactWorkspace(repo_root=tmp_path),
        tool_registry={"mock.ok": lambda: _ok({"ok": True})},
    )
    workflow = {"id": "demo", "steps": [{"id": "ok", "tool": "mock.ok"}]}

    result = tools.write_json_workflow("plans/demo.json", workflow, overwrite=False)

    assert result["is_error"] is False
    assert result["data"]["path"] == "plans/demo.json"
    assert tools.workspace.read_json("plans/demo.json") == workflow
    with pytest.raises(FileExistsError):
        tools.write_json_workflow("plans/demo.json", {"id": "replacement"}, overwrite=False)
    overwrite_result = tools.write_json_workflow(
        "plans/demo.json",
        {"id": "replacement"},
        overwrite=True,
    )
    assert overwrite_result["is_error"] is False
    assert tools.workspace.read_json("plans/demo.json") == {"id": "replacement"}
    with pytest.raises(ValueError):
        tools.write_json_workflow("../escape.json", workflow, overwrite=False)


def test_workflow_run_can_write_markdown_artifact(tmp_path: Path) -> None:
    """JSON workflow can invoke registered tools and artifact writer only."""
    workspace = ArtifactWorkspace(repo_root=tmp_path)
    tools: WorkflowTools
    registry = {
        "mock.search": lambda query: _ok({"query": query, "matches": [{"title": "Paper A"}]}),
    }
    tools = WorkflowTools(workspace=workspace, tool_registry=registry)
    tools.tool_registry["artifact.write_markdown"] = tools.write_markdown
    tools.interpreter.tool_registry["artifact.write_markdown"] = tools.write_markdown

    result = tools.run_json_workflow(
        workflow={
            "id": "demo",
            "steps": [
                {"id": "search", "tool": "mock.search", "args": {"query": "layout"}},
                {
                    "id": "write",
                    "tool": "artifact.write_markdown",
                    "args": {
                        "path": "reports/layout.md",
                        "content": {
                            "$template": {
                                "template": "# {title}",
                                "vars": {"title": "$steps.search.result.data.matches.0.title"},
                            }
                        },
                    },
                },
            ],
        }
    )

    assert result["is_error"] is False
    assert workspace.read_text("reports/layout.md")["content"] == "# Paper A"


def test_workflow_rejects_unregistered_tools(tmp_path: Path) -> None:
    """Workflow interpreter may call only explicitly registered tools."""
    tools = WorkflowTools(
        workspace=ArtifactWorkspace(repo_root=tmp_path),
        tool_registry={"mock.ok": lambda: _ok({"ok": True})},
    )

    result = tools.run_json_workflow(
        workflow={"steps": [{"id": "bad", "tool": "os.system", "args": {"cmd": "whoami"}}]}
    )

    assert result["is_error"] is True
    assert result["error_code"] == "workflow_tool_not_allowed"


def test_workflow_tools_audit_redacts_secret_preview(tmp_path: Path) -> None:
    """Workflow audit previews should pass through the shared redactor."""
    audit_root = tmp_path / "workspace_artifacts" / "agent_mcp_workflows" / ".audit"
    tools = WorkflowTools(
        workspace=ArtifactWorkspace(repo_root=tmp_path),
        tool_registry={"mock.ok": lambda: _ok({"ok": True})},
        audit=AuditLog(audit_root),
    )

    result = tools.write_markdown("secrets.md", "token sk-ant-" + "api" + "A" * 60, overwrite=False)

    assert result["is_error"] is False
    log_text = next(audit_root.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "sk-ant-api" not in log_text
    assert "redacted" in log_text

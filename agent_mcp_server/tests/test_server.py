"""Tests for FastMCP server registration."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.policy import PathPolicy
from lit_assistant_mcp.server import (
    EXPERIMENTAL_MCP_TOOL_NAMES,
    EXPERIMENTAL_TOOLS_ENV,
    MCP_TOOL_PROFILE_ENV,
    MINIMAL_MCP_TOOL_NAMES,
    NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
    NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
    NATIVE_HANDOFF_WIDGET_PROBE_TOOL_NAME,
    NATIVE_HANDOFF_WIDGET_TOOL_NAME,
    SIDEBAR_APP_RESOURCE_MIME_TYPE,
    SIDEBAR_APP_RESOURCE_URI,
    SIDEBAR_APP_STATUS_TOOL_NAME,
    create_mcp_server,
    find_repo_root,
)
from lit_assistant_mcp.tools.source import SourceTools


REPO_ROOT = Path(__file__).resolve().parents[2]
ACQUISITION_TOOL_NAMES = frozenset(
    {
        "literature.acquisition_status",
        "literature.acquisition_search",
        "literature.acquisition_search_run",
        "literature.acquisition_download_queue",
        "literature.acquisition_download_run",
        "literature.acquisition_download_control",
        "literature.acquisition_gate_resolve",
        "literature.acquisition_artifact_import",
        "literature.acquisition_import_receipt",
    }
)


class LatestHandoffRuntime:
    """Minimal runtime double for testing widget default request binding."""

    def __init__(self) -> None:
        self.latest_calls: list[str | None] = []

    def codex_handoff_latest(self, project_id: str | None = None) -> dict[str, Any]:
        self.latest_calls.append(project_id)
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": {
                "schema_version": "scholar-ai-codex-handoff-latest/v1",
                "found": True,
                "request_id": "agentreq_latest",
                "project_id": "project-latest",
                "receipt_id": "sidebar_agentreq_latest",
                "ref_count": 2,
            },
            "truncated": False,
        }

    def __getattr__(self, _name: str) -> Any:
        def _tool_stub(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"is_error": False, "error_code": None, "message": None, "data": {}, "truncated": False}

        return _tool_stub


class WorkflowProbeRuntime(LatestHandoffRuntime):
    """Runtime double that records forbidden workflow probe dispatches."""

    def __init__(self) -> None:
        super().__init__()
        self.ocr_probe_calls = 0

    def ocr_execution_probe(self, **_kwargs: Any) -> dict[str, Any]:
        """Record an OCR execution request without calling a backend."""

        self.ocr_probe_calls += 1
        return {
            "is_error": False,
            "error_code": None,
            "message": None,
            "data": {"executed": True},
            "truncated": False,
        }


def test_find_repo_root_accepts_public_source_tree_anchor(tmp_path: Path, monkeypatch) -> None:
    """Public clones do not include local-only AI workspace guides."""

    (tmp_path / "SOURCE_RELEASE_POLICY.md").write_text("# policy\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = \"scholar-ai\"\n", encoding="utf-8")
    (tmp_path / "agent_mcp_server").mkdir()
    (tmp_path / "literature_assistant").mkdir()
    monkeypatch.setenv("LITERATURE_ASSISTANT_REPO_ROOT", str(tmp_path))

    assert find_repo_root() == tmp_path.resolve()


def _assert_read_only_annotations(tool: object) -> None:
    """Assert a tool declares the non-mutating MCP annotation contract."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


def _assert_execution_probe_annotations(tool: object) -> None:
    """Assert OCR execution is explicit, non-destructive, and non-idempotent."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True


def _assert_open_world_local_write_annotations(tool: object) -> None:
    """Assert a tool declares local writes that may call configured providers."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True


def _assert_local_write_annotations(tool: object) -> None:
    """Assert a tool declares bounded local writes without external mutation."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False


def _assert_idempotent_local_write_annotations(tool: object) -> None:
    """Assert a repeatable local write tool declares idempotent MCP metadata."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


def _assert_destructive_local_write_annotations(tool: object) -> None:
    """Assert a tool declares local writes that may replace artifacts or terminal state."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is True
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False


def _assert_open_world_destructive_write_annotations(tool: object) -> None:
    """Assert a tool declares replace-capable writes that may call configured providers."""

    annotations = getattr(tool, "annotations", None)
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is True
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is True


def test_server_registers_source_and_runtime_tools(monkeypatch) -> None:
    """FastMCP server exposes source, runtime, and workflow-spine tool names."""
    monkeypatch.setenv(EXPERIMENTAL_TOOLS_ENV, "1")
    server = create_mcp_server(tool_profile="full")

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}

    assert {
        "source.list_tree",
        "source.search",
        "source.read_file",
        "source.read_symbols",
        "source.inspect_routes",
        "source.find_references",
        "source.explain_entrypoints",
        "literature.agent_sidebar_url",
        "literature.launch_desktop",
        "literature.config_status",
        "literature.sidebar_app_status",
        "literature.codex_handoff_widget",
        "literature.native_handoff_widget_probe",
        "literature.health_check",
        "literature.zotero_attachment_health",
        "literature.list_projects",
        "literature.list_materials",
        "literature.read_material",
        "literature.get_material_chunks",
        "literature.search_refs",
        "literature.knowledge_packages",
        "literature.knowledge_runtime_conformance",
        "literature.ocr_status",
        "literature.ocr_engines",
        "literature.ocr_health",
        "literature.ocr_execution_probe",
        "literature.knowledge_context_receipt",
        "literature.wiki_status",
        "literature.wiki_doctor",
        "literature.wiki_search",
        "literature.skill_package_status",
        "literature.skill_package_search",
        "literature.source_vault_status",
        "literature.source_vault_search",
        "literature.source_vault_read",
        "literature.academic_english_status",
        "literature.academic_english_search",
        "literature.bridge_lexicon_status",
        "literature.bridge_lexicon_read",
        "literature.bridge_lexicon_search",
        "literature.scoring_rules_status",
        "literature.scoring_rules_read",
        "literature.scoring_rules_search",
        "literature.product_docs_status",
        "literature.product_docs_read",
        "literature.product_docs_search",
        "literature.evidence_pack_build",
        "literature.qrels_review_bundle",
        "literature.chat_ask_persisting",
        "literature.answer_receipt_list",
        "literature.answer_receipt_read",
        "literature.answer_receipt_markdown",
        "literature.answer_receipt_revalidate",
        "literature.project_scan_folder",
        "literature.figures_candidates",
        "literature.figures_generate",
        "literature.citations_sources",
        "literature.citations_detect_overlap",
        "literature.academic_writing_lint",
        "literature.outline_generate",
        "literature.export_annotations_markdown",
        "literature.export_docx",
        "literature.journal_style_spec_draft",
        "literature.journal_style_spec_confirm",
        "literature.agent_bridge_status",
        "literature.agent_workspace_status",
        "literature.agent_workspace_requirement",
        "literature.agent_request_create",
        "literature.wiki_import",
        "literature.single_paper_task_create",
        "literature.single_paper_completion_check",
        "literature.agent_request_list",
        "literature.agent_request_read",
        "literature.agent_handoff_card",
        "literature.behavior_eval_pack",
        "literature.workflow_passport",
        "literature.evidence_integrity_gate",
        "literature.agent_resource_read",
        "literature.agent_progress",
        "literature.agent_result",
        "literature.agent_fail",
        "literature.research_action_lifecycle",
        "literature.workflow_refresh_receipt",
        "literature.workflow_replay_lineage",
        "literature.workflow_replay_index",
        "literature.ocr_material",
        "literature.prepare_visual_review",
        "literature.translate_pack",
        "literature.export_project_pack",
        "workflow.create_plan",
        "workflow.write_json_workflow",
        "workflow.run_json_workflow",
        "workflow.run_python_sandbox",
        "artifact.write_markdown",
        "artifact.read_artifact",
        "artifact.list_artifacts",
    }.issubset(tool_names)
    assert "literature.search_literature" not in tool_names
    assert "literature.ingest_then_search" not in tool_names

    tools_by_name = {tool.name: tool for tool in server._tool_manager.list_tools()}
    read_only_tool_names = [
        "source.list_tree",
        "source.search",
        "source.read_file",
        "source.read_symbols",
        "source.inspect_routes",
        "source.find_references",
        "source.explain_entrypoints",
        "literature.agent_sidebar_url",
        "literature.config_status",
        "literature.sidebar_app_status",
        "literature.codex_handoff_widget",
        "literature.native_handoff_widget_probe",
        "literature.health_check",
        "literature.list_projects",
        "literature.list_materials",
        "literature.read_material",
        "literature.get_material_chunks",
        "literature.search_refs",
        "literature.knowledge_packages",
        "literature.knowledge_runtime_conformance",
        "literature.ocr_status",
        "literature.ocr_engines",
        "literature.ocr_health",
        "literature.knowledge_context_receipt",
        "literature.wiki_status",
        "literature.wiki_doctor",
        "literature.wiki_search",
        "literature.academic_english_search",
        "literature.skill_package_status",
        "literature.skill_package_search",
        "literature.source_vault_status",
        "literature.source_vault_search",
        "literature.source_vault_read",
        "literature.academic_english_status",
        "literature.bridge_lexicon_status",
        "literature.bridge_lexicon_read",
        "literature.bridge_lexicon_search",
        "literature.scoring_rules_status",
        "literature.scoring_rules_read",
        "literature.scoring_rules_search",
        "literature.product_docs_status",
        "literature.product_docs_read",
        "literature.evidence_pack_build",
        "literature.answer_receipt_list",
        "literature.answer_receipt_read",
        "literature.answer_receipt_markdown",
        "literature.figures_candidates",
        "literature.citations_sources",
        "literature.citations_detect_overlap",
        "literature.academic_writing_lint",
        "literature.export_annotations_markdown",
        "literature.agent_bridge_status",
        "literature.single_paper_completion_check",
        "literature.agent_request_list",
        "literature.agent_request_read",
        "literature.agent_handoff_card",
        "literature.workflow_passport",
        "literature.evidence_integrity_gate",
        "literature.research_action_lifecycle",
        "literature.workflow_refresh_receipt",
        "literature.workflow_replay_lineage",
        "literature.workflow_replay_index",
        "literature.product_docs_search",
        "literature.agent_resource_read",
        "literature.agent_workspace_status",
        "literature.agent_workspace_requirement",
        "workflow.create_plan",
        "artifact.read_artifact",
        "artifact.list_artifacts",
    ]
    for tool_name in read_only_tool_names:
        _assert_read_only_annotations(tools_by_name[tool_name])
    _assert_execution_probe_annotations(tools_by_name["literature.ocr_execution_probe"])
    _assert_local_write_annotations(tools_by_name["literature.launch_desktop"])

    wiki_import_annotations = tools_by_name["literature.wiki_import"].annotations
    assert wiki_import_annotations is not None
    assert wiki_import_annotations.readOnlyHint is False
    assert wiki_import_annotations.destructiveHint is True
    assert wiki_import_annotations.idempotentHint is False
    assert wiki_import_annotations.openWorldHint is False
    _assert_local_write_annotations(tools_by_name["literature.zotero_attachment_health"])
    _assert_local_write_annotations(tools_by_name["literature.behavior_eval_pack"])
    _assert_idempotent_local_write_annotations(tools_by_name["literature.qrels_review_bundle"])
    _assert_open_world_local_write_annotations(tools_by_name["literature.chat_ask_persisting"])
    assert "backend or UX labels" in (tools_by_name["literature.chat_ask_persisting"].description or "")
    _assert_open_world_local_write_annotations(tools_by_name["literature.outline_generate"])
    _assert_local_write_annotations(tools_by_name["literature.agent_request_create"])
    _assert_local_write_annotations(tools_by_name["literature.single_paper_task_create"])
    _assert_local_write_annotations(tools_by_name["literature.agent_progress"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.agent_result"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.agent_fail"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.ocr_material"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.prepare_visual_review"])
    _assert_open_world_destructive_write_annotations(tools_by_name["literature.translate_pack"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.export_docx"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.journal_style_spec_draft"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.journal_style_spec_confirm"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.project_scan_folder"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.figures_generate"])
    _assert_destructive_local_write_annotations(tools_by_name["literature.export_project_pack"])
    _assert_destructive_local_write_annotations(tools_by_name["workflow.write_json_workflow"])
    _assert_open_world_destructive_write_annotations(tools_by_name["workflow.run_json_workflow"])
    _assert_destructive_local_write_annotations(tools_by_name["workflow.run_python_sandbox"])
    _assert_destructive_local_write_annotations(tools_by_name["artifact.write_markdown"])


def test_server_full_profile_hides_experimental_tools_without_opt_in(monkeypatch) -> None:
    """Experimental tools should not consume host context until explicitly enabled."""
    monkeypatch.delenv(EXPERIMENTAL_TOOLS_ENV, raising=False)

    server = create_mcp_server(tool_profile="full")

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert not EXPERIMENTAL_MCP_TOOL_NAMES.intersection(tool_names)
    assert "literature.outline_generate" in tool_names
    assert "workflow.run_json_workflow" in tool_names


def test_server_workflow_cannot_dispatch_hidden_experimental_tools(monkeypatch) -> None:
    """The experimental opt-in must gate indirect JSON workflow dispatch too."""

    monkeypatch.delenv(EXPERIMENTAL_TOOLS_ENV, raising=False)
    runtime = WorkflowProbeRuntime()
    server = create_mcp_server(runtime_tools=runtime, tool_profile="full")

    result = asyncio.run(
        server.call_tool(
            "workflow.run_json_workflow",
            {
                "workflow": {
                    "id": "hidden-ocr-probe",
                    "steps": [
                        {
                            "id": "probe",
                            "tool": "literature.ocr_execution_probe",
                            "args": {
                                "confirm_execution": True,
                                "image_base64": "aW1hZ2U=",
                            },
                        }
                    ],
                }
            },
        )
    )

    assert runtime.ocr_probe_calls == 0
    assert isinstance(result, tuple)
    structured_result = result[1]
    assert structured_result["is_error"] is True
    assert structured_result["error_code"] == "workflow_tool_not_allowed"


def test_server_workflow_dispatches_experimental_tools_after_opt_in(monkeypatch) -> None:
    """The same workflow tool remains available after explicit opt-in."""

    monkeypatch.setenv(EXPERIMENTAL_TOOLS_ENV, "1")
    runtime = WorkflowProbeRuntime()
    server = create_mcp_server(runtime_tools=runtime, tool_profile="full")

    result = asyncio.run(
        server.call_tool(
            "workflow.run_json_workflow",
            {
                "workflow": {
                    "id": "enabled-ocr-probe",
                    "steps": [
                        {
                            "id": "probe",
                            "tool": "literature.ocr_execution_probe",
                            "args": {
                                "confirm_execution": True,
                                "image_base64": "aW1hZ2U=",
                            },
                        }
                    ],
                }
            },
        )
    )

    assert runtime.ocr_probe_calls == 1
    assert isinstance(result, tuple)
    structured_result = result[1]
    assert structured_result["is_error"] is False


def test_server_registers_acquisition_tools_only_in_full_profile(monkeypatch) -> None:
    """Acquisition tools expose explicit action boundaries only in the full profile."""
    monkeypatch.delenv(EXPERIMENTAL_TOOLS_ENV, raising=False)

    full_server = create_mcp_server(tool_profile="full")
    full_tools = {tool.name: tool for tool in full_server._tool_manager.list_tools()}
    minimal_server = create_mcp_server(tool_profile="minimal")
    minimal_tool_names = {tool.name for tool in minimal_server._tool_manager.list_tools()}

    assert ACQUISITION_TOOL_NAMES.issubset(full_tools)
    assert ACQUISITION_TOOL_NAMES.isdisjoint(minimal_tool_names)

    expected_annotations = {
        "literature.acquisition_status": (True, False, True, False),
        "literature.acquisition_search": (False, False, False, True),
        "literature.acquisition_search_run": (True, False, True, False),
        "literature.acquisition_download_queue": (False, False, True, False),
        "literature.acquisition_download_run": (False, False, False, True),
        "literature.acquisition_download_control": (False, True, True, False),
        "literature.acquisition_gate_resolve": (False, False, True, False),
        "literature.acquisition_artifact_import": (False, False, True, False),
        "literature.acquisition_import_receipt": (True, False, True, False),
    }
    for tool_name, expected in expected_annotations.items():
        annotations = full_tools[tool_name].annotations
        assert annotations is not None
        assert (
            annotations.readOnlyHint,
            annotations.destructiveHint,
            annotations.idempotentHint,
            annotations.openWorldHint,
        ) == expected

    search_run_schema = full_tools["literature.acquisition_search_run"].parameters
    assert search_run_schema["required"] == ["run_id"]
    assert search_run_schema["properties"]["candidate_offset"]["default"] == 0
    assert search_run_schema["properties"]["candidate_limit"]["default"] == 10

    control_schema = full_tools["literature.acquisition_download_control"].parameters
    assert control_schema["properties"]["action"]["enum"] == ["pause", "resume", "cancel"]

    gate_schema = full_tools["literature.acquisition_gate_resolve"].parameters
    assert gate_schema["properties"]["confirm_user_completed"]["default"] is False


def test_server_minimal_profile_exposes_only_core_claude_tools(monkeypatch) -> None:
    """Minimal profile keeps the verified evidence and answer write-back chain."""
    monkeypatch.setenv(EXPERIMENTAL_TOOLS_ENV, "1")

    server = create_mcp_server(tool_profile="minimal")

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert tool_names == MINIMAL_MCP_TOOL_NAMES
    assert len(tool_names) == 22
    assert {
        "literature.agent_request_create",
        "literature.agent_result",
        "literature.answer_receipt_read",
        "literature.answer_receipt_list",
    }.issubset(tool_names)
    assert not EXPERIMENTAL_MCP_TOOL_NAMES.intersection(tool_names)
    assert "literature.outline_generate" not in tool_names
    assert "workflow.run_json_workflow" not in tool_names

    resources = asyncio.run(server.list_resources())
    assert SIDEBAR_APP_RESOURCE_URI not in {str(resource.uri) for resource in resources}
    assert NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI not in {str(resource.uri) for resource in resources}


def test_server_reads_minimal_profile_from_environment(monkeypatch) -> None:
    """The stdio process can reduce Claude tool loading by setting one env var."""
    monkeypatch.setenv(MCP_TOOL_PROFILE_ENV, "minimal")

    server = create_mcp_server()

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert tool_names == MINIMAL_MCP_TOOL_NAMES


def test_server_rejects_unknown_tool_profile() -> None:
    """Invalid profiles should fail closed instead of silently exposing surprises."""
    with pytest.raises(ValueError, match=MCP_TOOL_PROFILE_ENV):
        create_mcp_server(tool_profile="tiny")


def test_server_registers_sidebar_app_resource_and_status_tool_metadata() -> None:
    """The MCP Apps sidebar shell is discoverable without a parallel answer chain."""
    server = create_mcp_server(tool_profile="full")

    tools_by_name = {tool.name: tool for tool in server._tool_manager.list_tools()}
    status_tool = tools_by_name[SIDEBAR_APP_STATUS_TOOL_NAME]
    _assert_read_only_annotations(status_tool)
    assert status_tool.meta == {
        "ui": {
            "resourceUri": SIDEBAR_APP_RESOURCE_URI,
            "visibility": ["model", "app"],
        }
    }

    resources = asyncio.run(server.list_resources())
    resources_by_uri = {str(resource.uri): resource for resource in resources}
    sidebar_resource = resources_by_uri[SIDEBAR_APP_RESOURCE_URI]
    assert sidebar_resource.name == "scholar-ai-sidebar"
    assert sidebar_resource.mimeType == SIDEBAR_APP_RESOURCE_MIME_TYPE
    assert sidebar_resource.meta == {
        "ui": {
            "schemaVersion": "scholar-ai-sidebar-app/v1",
            "statusTool": SIDEBAR_APP_STATUS_TOOL_NAME,
            "prefersBorder": False,
            "csp": {
                "connectDomains": [],
                "resourceDomains": [],
            },
        }
    }

    contents = asyncio.run(server.read_resource(SIDEBAR_APP_RESOURCE_URI))
    assert len(contents) == 1
    resource_content = contents[0]
    assert resource_content.mime_type == SIDEBAR_APP_RESOURCE_MIME_TYPE
    assert resource_content.meta == sidebar_resource.meta
    assert 'data-schema-version="scholar-ai-sidebar-app/v1"' in resource_content.content
    assert f'data-status-tool="{SIDEBAR_APP_STATUS_TOOL_NAME}"' in resource_content.content
    assert "literature.answer_receipt" not in resource_content.content


def test_server_registers_native_handoff_widget() -> None:
    """The native handoff widget is discoverable but still host-evidence gated."""
    server = create_mcp_server(tool_profile="full")

    tools_by_name = {tool.name: tool for tool in server._tool_manager.list_tools()}
    handoff_tool = tools_by_name[NATIVE_HANDOFF_WIDGET_TOOL_NAME]
    legacy_probe_tool = tools_by_name[NATIVE_HANDOFF_WIDGET_PROBE_TOOL_NAME]
    _assert_read_only_annotations(handoff_tool)
    _assert_read_only_annotations(legacy_probe_tool)
    assert handoff_tool.meta == {
        "ui": {
            "resourceUri": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
            "visibility": ["model", "app"],
        },
        "ui/resourceUri": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
        "openai/outputTemplate": NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI,
        "openai/widgetAccessible": True,
        "openai/toolInvocation/invoking": "正在打开 Scholar AI 主栏交接...",
        "openai/toolInvocation/invoked": "Scholar AI 主栏交接已准备",
    }
    assert legacy_probe_tool.meta == handoff_tool.meta

    resources = asyncio.run(server.list_resources())
    resources_by_uri = {str(resource.uri): resource for resource in resources}
    probe_resource = resources_by_uri[NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI]
    assert probe_resource.name == "scholar-ai-main-column-handoff"
    assert probe_resource.mimeType == SIDEBAR_APP_RESOURCE_MIME_TYPE
    assert probe_resource.meta == {
        "ui": {
            "schemaVersion": NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
            "prefersBorder": False,
            "csp": {
                "connectDomains": [],
                "resourceDomains": [],
            },
        },
        "openai/widgetDescription": (
            "Scholar AI main-column handoff widget. Sends a bounded sidebar "
            "task handoff to the host conversation only when the user clicks."
        ),
        "openai/widgetPrefersBorder": False,
        "openai/widgetCSP": {
            "connect_domains": [],
            "resource_domains": [],
        },
    }

    contents = asyncio.run(server.read_resource(NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI))
    assert len(contents) == 1
    resource_content = contents[0]
    assert resource_content.mime_type == SIDEBAR_APP_RESOURCE_MIME_TYPE
    assert resource_content.meta == probe_resource.meta
    assert f'data-schema-version="{NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION}"' in resource_content.content
    assert "交接到 Codex 主栏" in resource_content.content
    assert "发送到主栏" in resource_content.content
    assert "发送测试消息" in resource_content.content
    assert "点击后把接手指令发送到当前 Codex 主栏。" in resource_content.content
    assert '<p id="probe-meta" class="sr-only">' in resource_content.content
    assert '<code id="payload" hidden>' in resource_content.content
    assert "调试详情" not in resource_content.content
    assert "Scholar AI 原生交接探针" not in resource_content.content
    assert "请接手 Scholar AI 交接任务" in resource_content.content
    assert "literature.agent_request_read" in resource_content.content
    assert "literature.agent_result" in resource_content.content
    assert "window.openai" in resource_content.content
    assert "hostSupportsMessage" in resource_content.content
    assert "sendFollowUpMessage" in resource_content.content
    assert "sendMessage" in resource_content.content
    assert "ui/initialize" in resource_content.content
    assert "ui/message" in resource_content.content
    assert "directWidgetData" in resource_content.content
    assert "S74_NATIVE_HANDOFF_WIDGET_PROBE_RECEIVED" in resource_content.content


def test_native_handoff_widget_carries_real_request_data() -> None:
    """The host-rendered widget should send the existing sidebar_answer request."""
    server = create_mcp_server(tool_profile="full")

    result = asyncio.run(
        server.call_tool(
            NATIVE_HANDOFF_WIDGET_TOOL_NAME,
            {
                "request_id": "agentreq_sidebar",
                "project_id": "project-a",
                "receipt_id": "session-sidebar-1",
                "ref_count": 3,
            },
        )
    )

    assert result.structuredContent["rendering"] == "native_mcp_handoff_widget"
    assert result.structuredContent["widget_data"] == {
        "schema_version": NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
        "mode": "handoff",
        "request_id": "agentreq_sidebar",
        "project_id": "project-a",
        "receipt_id": "session-sidebar-1",
        "ref_count": 3,
        "note": None,
    }
    assert result.meta["openai/outputTemplate"] == NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI
    assert result.meta["widgetData"]["request_id"] == "agentreq_sidebar"
    assert result.content[0].text == "Scholar AI 主栏交接控件已准备。点击控件按钮发送到 Codex 主栏。"


def test_native_handoff_widget_defaults_to_latest_sidebar_request() -> None:
    """The main-column widget should bind the latest sidebar handoff when omitted."""
    runtime = LatestHandoffRuntime()
    server = create_mcp_server(runtime_tools=runtime, tool_profile="full")

    result = asyncio.run(server.call_tool(NATIVE_HANDOFF_WIDGET_TOOL_NAME, {}))

    assert runtime.latest_calls == [None]
    assert result.structuredContent["rendering"] == "native_mcp_handoff_widget"
    assert result.structuredContent["widget_data"] == {
        "schema_version": NATIVE_HANDOFF_WIDGET_PROBE_SCHEMA_VERSION,
        "mode": "handoff",
        "request_id": "agentreq_latest",
        "project_id": "project-latest",
        "receipt_id": "sidebar_agentreq_latest",
        "ref_count": 2,
        "note": "已绑定最新侧栏接手任务。",
    }
    assert result.meta["widgetData"]["request_id"] == "agentreq_latest"
    assert result.content[0].text == "Scholar AI 主栏交接控件已准备。点击控件按钮发送到 Codex 主栏。"


def test_native_handoff_widget_probe_alias_carries_real_request_data() -> None:
    """The legacy probe name remains a compatibility alias for existing host sessions."""
    server = create_mcp_server(tool_profile="full")

    result = asyncio.run(
        server.call_tool(
            NATIVE_HANDOFF_WIDGET_PROBE_TOOL_NAME,
            {
                "request_id": "agentreq_sidebar",
                "project_id": "project-a",
                "receipt_id": "session-sidebar-1",
                "ref_count": 3,
            },
        )
    )

    assert result.structuredContent["rendering"] == "native_mcp_handoff_widget"
    assert result.structuredContent["widget_data"]["request_id"] == "agentreq_sidebar"
    assert result.meta["openai/outputTemplate"] == NATIVE_HANDOFF_WIDGET_PROBE_RESOURCE_URI


def test_server_instructions_point_to_capability_map_without_stale_count() -> None:
    """Server instructions should advertise the map without duplicating registry counts."""
    server = create_mcp_server(tool_profile="full")

    instructions = getattr(server, "instructions", "")
    assert "agent_mcp_server/CAPABILITY_MAP.md" in instructions
    assert "source.read_file" in instructions
    assert "84 tools" not in instructions


def test_capability_map_covers_registered_tools_and_is_source_readable() -> None:
    """The agent-facing capability map must stay synchronized with registered tools."""
    server = create_mcp_server(tool_profile="full")
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    capability_map = REPO_ROOT / "agent_mcp_server" / "CAPABILITY_MAP.md"
    text = capability_map.read_text(encoding="utf-8")

    assert "## 完整工具名索引" in text
    assert "## KRT actual-loading gate 恢复核对" in text
    assert "literature.agent_workspace_status       # 工作区恢复面" in text
    assert "knowledge_actual_loading_gate.recovery_state" in text
    assert "literature.knowledge_runtime_conformance # KRT 原始一致性面" in text
    assert "不等于 live provider/model actual-loading proof" in text
    assert "## Goal lifecycle completion gate 恢复核对" in text
    assert "requirements_all_proved=true" in text
    assert "literature.agent_workspace_status        # goal_state.lifecycle_rollup / completion_claim" in text
    assert "literature.agent_workspace_requirement   # 单条 requirement-to-evidence drilldown" in text
    assert "goal_state.lifecycle_rollup.can_mark_goal_complete" in text
    assert "completion_blockers[].missing_evidence" in text
    assert "not_complete_pending_authorized_actual_loading_provider_proof" in text
    assert "不能把全绿 requirement 矩阵当成 `update_goal complete` 证据" in text
    assert "## 结果信封与截断边界" in text
    assert "agent_mcp_server/src/lit_assistant_mcp/result.py::safe_result" in text
    assert "is_error` / `error_code` / `message` / `data` / `truncated" in text
    assert "_truncated` / `_omitted_keys` / `omitted_items" in text
    assert "serialization_failed" in text
    assert "## KRT deterministic source-to-context proof" in text
    assert "literature.knowledge_packages            # package/source/hash/runtime consumer 总览" in text
    assert "literature.agent_resource_read           # bounded resource read" in text
    assert "literature.knowledge_context_receipt     # bounded context receipt" in text
    assert "这个链路证明 deterministic source-to-context" in text
    assert "## WikiRegistry -> Source Vault mirror backlog" in text
    assert "literature.wiki_doctor                   # Source Vault mirror backlog / needs_replay" in text
    assert "metrics.source_vault_mirror" in text
    assert "source_vault_mirror_backlog" in text
    assert "actions[].safe_auto_repair" in text
    assert "WikiRegistry.replay_source_vault_mirror()" in text
    assert "不是 MCP 自动修复工具" in text
    missing = sorted(name for name in tool_names if name not in text)
    assert not missing

    source = SourceTools(
        repo_root=REPO_ROOT,
        policy=PathPolicy(
            repo_root=REPO_ROOT,
            allowed_roots=["agent_mcp_server/"],
            denied_patterns=["**/.env*", ".git/**", "workspace_artifacts/runtime_state/**"],
        ),
        audit=AuditLog(REPO_ROOT / "workspace_artifacts/agent_mcp_workflows/.audit"),
    )
    result = source.read_file("agent_mcp_server/CAPABILITY_MAP.md", max_chars=1200)

    assert result["is_error"] is False
    assert "Scholar AI MCP" in result["data"]["content"]

"""Tests for FastMCP server registration."""

from pathlib import Path

from lit_assistant_mcp.audit import AuditLog
from lit_assistant_mcp.policy import PathPolicy
from lit_assistant_mcp.server import create_mcp_server, find_repo_root
from lit_assistant_mcp.tools.source import SourceTools


REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_server_registers_source_and_runtime_tools() -> None:
    """FastMCP server exposes source, runtime, and workflow-spine tool names."""
    server = create_mcp_server()

    tool_names = {tool.name for tool in server._tool_manager.list_tools()}

    assert {
        "source.list_tree",
        "source.search",
        "source.read_file",
        "source.read_symbols",
        "source.inspect_routes",
        "source.find_references",
        "source.explain_entrypoints",
        "literature.launch_desktop",
        "literature.config_status",
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
        "literature.config_status",
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


def test_server_instructions_point_to_capability_map_without_stale_count() -> None:
    """Server instructions should advertise the map without duplicating registry counts."""
    server = create_mcp_server()

    instructions = getattr(server, "instructions", "")
    assert "agent_mcp_server/CAPABILITY_MAP.md" in instructions
    assert "source.read_file" in instructions
    assert "84 tools" not in instructions


def test_capability_map_covers_registered_tools_and_is_source_readable() -> None:
    """The agent-facing capability map must stay synchronized with registered tools."""
    server = create_mcp_server()
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

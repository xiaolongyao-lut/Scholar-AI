"""Tests for FastMCP server registration."""

from lit_assistant_mcp.server import create_mcp_server


def test_server_registers_source_and_runtime_tools() -> None:
    """FastMCP server exposes Slice 2 and Slice 3 tool names."""
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
        "literature.config_status",
        "literature.health_check",
        "literature.zotero_attachment_health",
        "literature.list_projects",
        "literature.list_materials",
        "literature.read_material",
        "literature.get_material_chunks",
        "literature.search_refs",
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
        "literature.agent_request_create",
        "literature.single_paper_task_create",
        "literature.single_paper_completion_check",
        "literature.agent_request_list",
        "literature.agent_request_read",
        "literature.agent_resource_read",
        "literature.agent_progress",
        "literature.agent_result",
        "literature.agent_fail",
        "literature.research_action_lifecycle",
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

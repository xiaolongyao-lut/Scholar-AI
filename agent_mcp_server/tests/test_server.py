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
        "literature.list_projects",
        "literature.list_materials",
        "literature.read_material",
        "literature.get_material_chunks",
        "literature.search_literature",
        "literature.ingest_then_search",
        "literature.export_annotations_markdown",
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

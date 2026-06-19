"""FastMCP stdio server for the Literature Assistant local toolbox."""

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .audit import AuditLog
from .tools import (
    ExperimentalTools,
    RuntimeTools,
    SourceTools,
    WorkflowTools,
    create_default_experimental_tools,
    create_default_runtime_tools,
    create_default_source_tools,
    create_default_workflow_tools,
)


def find_repo_root(start: Path | None = None) -> Path:
    """Find the repository root containing AI_WORKSPACE_GUIDE.md.

    Args:
        start: Optional path to start from. Defaults to this module path.

    Returns:
        Absolute repository root.

    Raises:
        RuntimeError: If the repository root cannot be found.
    """
    env_root = os.environ.get("LITERATURE_ASSISTANT_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if (candidate / "AI_WORKSPACE_GUIDE.md").exists():
            return candidate
        raise RuntimeError("LITERATURE_ASSISTANT_REPO_ROOT does not contain AI_WORKSPACE_GUIDE.md")

    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "AI_WORKSPACE_GUIDE.md").exists():
            return candidate
    raise RuntimeError("Could not find repository root from MCP server path")


def create_mcp_server(
    source_tools: SourceTools | None = None,
    runtime_tools: RuntimeTools | None = None,
    workflow_tools: WorkflowTools | None = None,
    experimental_tools: ExperimentalTools | None = None,
) -> FastMCP:
    """Create and register the Literature Assistant MCP server.

    Args:
        source_tools: Optional injected source tool implementation for tests.
        runtime_tools: Optional injected runtime tool implementation for tests.

    Returns:
        Configured FastMCP server instance.
    """
    repo_root = find_repo_root()
    audit_root = repo_root / "workspace_artifacts/agent_mcp_workflows/.audit"
    source = source_tools or create_default_source_tools(
        repo_root=repo_root,
        audit=AuditLog(audit_root),
    )
    runtime = runtime_tools or create_default_runtime_tools(
        audit_root=audit_root,
        base_url=os.environ.get("LITERATURE_ASSISTANT_BASE_URL") or None,
    )
    experimental = experimental_tools or create_default_experimental_tools(
        repo_root=repo_root,
        runtime=runtime,
        audit_root=audit_root,
    )
    workflow_registry = {
        "source.list_tree": source.list_tree,
        "source.search": source.search,
        "source.read_file": source.read_file,
        "source.read_symbols": source.read_symbols,
        "source.inspect_routes": source.inspect_routes,
        "source.find_references": source.find_references,
        "source.explain_entrypoints": source.explain_entrypoints,
        "literature.config_status": runtime.config_status,
        "literature.list_projects": runtime.list_projects,
        "literature.list_materials": runtime.list_materials,
        "literature.read_material": runtime.read_material,
        "literature.get_material_chunks": runtime.get_material_chunks,
        "literature.search_refs": runtime.search_refs,
        "literature.evidence_pack_build": runtime.evidence_pack_build,
        "literature.project_scan_folder": runtime.project_scan_folder,
        "literature.figures_candidates": runtime.figures_candidates,
        "literature.figures_generate": runtime.figures_generate,
        "literature.citations_sources": runtime.citations_sources,
        "literature.citations_detect_overlap": runtime.citations_detect_overlap,
        "literature.academic_writing_lint": runtime.academic_writing_lint,
        "literature.outline_generate": runtime.outline_generate,
        "literature.export_annotations_markdown": runtime.export_annotations_markdown,
        "literature.export_docx": runtime.export_docx,
        "literature.agent_bridge_status": runtime.agent_bridge_status,
        "literature.agent_request_create": runtime.agent_request_create,
        "literature.agent_request_list": runtime.agent_request_list,
        "literature.agent_request_read": runtime.agent_request_read,
        "literature.agent_resource_read": runtime.agent_resource_read,
        "literature.agent_progress": runtime.agent_progress,
        "literature.agent_result": runtime.agent_result,
        "literature.agent_fail": runtime.agent_fail,
        "literature.ocr_material": experimental.ocr_material,
        "literature.prepare_visual_review": experimental.prepare_visual_review,
        "literature.translate_pack": experimental.translate_pack,
        "literature.export_project_pack": experimental.export_project_pack,
    }
    workflow_impl = workflow_tools or create_default_workflow_tools(
        repo_root=repo_root,
        tool_registry=workflow_registry,
        audit_root=audit_root,
    )
    workflow_registry.update(
        {
            "artifact.write_markdown": workflow_impl.write_markdown,
            "artifact.read_artifact": workflow_impl.read_artifact,
            "artifact.list_artifacts": workflow_impl.list_artifacts,
            "workflow.run_python_sandbox": experimental.run_python_sandbox,
        }
    )
    workflow_impl.tool_registry.update(workflow_registry)
    workflow_impl.interpreter.tool_registry.update(workflow_registry)

    mcp = FastMCP(
        name="literature-assistant",
        instructions="Local Literature Assistant toolbox for Codex and Claude.",
    )

    @mcp.tool(name="source.list_tree", structured_output=True)
    def source_list_tree(
        root: str = ".",
        max_depth: int = 3,
        max_entries: int = 500,
    ) -> dict[str, Any]:
        """List allowed source files and directories."""
        return source.list_tree(root=root, max_depth=max_depth, max_entries=max_entries)

    @mcp.tool(name="source.search", structured_output=True)
    def source_search(
        query: str,
        root: str = ".",
        max_results: int = 50,
        case_sensitive: bool = False,
    ) -> dict[str, Any]:
        """Search allowed source files for literal text."""
        return source.search(
            query=query,
            root=root,
            max_results=max_results,
            case_sensitive=case_sensitive,
        )

    @mcp.tool(name="source.read_file", structured_output=True)
    def source_read_file(path: str, max_chars: int = 80000) -> dict[str, Any]:
        """Read an allowed source text file."""
        return source.read_file(path=path, max_chars=max_chars)

    @mcp.tool(name="source.read_symbols", structured_output=True)
    def source_read_symbols(path: str) -> dict[str, Any]:
        """Read top-level Python symbols from an allowed source file."""
        return source.read_symbols(path=path)

    @mcp.tool(name="source.inspect_routes", structured_output=True)
    def source_inspect_routes(
        root: str = "literature_assistant/core",
        max_routes: int = 200,
    ) -> dict[str, Any]:
        """Inspect FastAPI route decorators without importing modules."""
        return source.inspect_routes(root=root, max_routes=max_routes)

    @mcp.tool(name="source.find_references", structured_output=True)
    def source_find_references(
        symbol: str,
        root: str = ".",
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Find bounded static references to an identifier or literal text."""
        return source.find_references(symbol=symbol, root=root, max_results=max_results)

    @mcp.tool(name="source.explain_entrypoints", structured_output=True)
    def source_explain_entrypoints(
        path: str,
        max_depth: int = 2,
        max_files: int = 30,
    ) -> dict[str, Any]:
        """Sketch imports reachable from a Python entrypoint."""
        return source.explain_entrypoints(path=path, max_depth=max_depth, max_files=max_files)

    @mcp.tool(name="literature.config_status", structured_output=True)
    def literature_config_status() -> dict[str, Any]:
        """Return Literature Assistant backend health."""
        return runtime.config_status()

    @mcp.tool(name="literature.list_projects", structured_output=True)
    def literature_list_projects() -> dict[str, Any]:
        """List Literature Assistant projects."""
        return runtime.list_projects()

    @mcp.tool(name="literature.list_materials", structured_output=True)
    def literature_list_materials(project_id: str) -> dict[str, Any]:
        """List materials for a project."""
        return runtime.list_materials(project_id=project_id)

    @mcp.tool(name="literature.read_material", structured_output=True)
    def literature_read_material(material_id: str) -> dict[str, Any]:
        """Read a material record."""
        return runtime.read_material(material_id=material_id)

    @mcp.tool(name="literature.get_material_chunks", structured_output=True)
    def literature_get_material_chunks(project_id: str, material_id: str) -> dict[str, Any]:
        """Read chunks for a material."""
        return runtime.get_material_chunks(project_id=project_id, material_id=material_id)

    @mcp.tool(name="literature.search_refs", structured_output=True)
    def literature_search_refs(
        project_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search existing project chunks and return refs only."""
        return runtime.search_refs(project_id=project_id, query=query, top_k=top_k)

    @mcp.tool(name="literature.evidence_pack_build", structured_output=True)
    def literature_evidence_pack_build(
        project_id: str,
        query: str,
        section_id: str | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Build a query-scoped evidence pack from project refs."""
        return runtime.evidence_pack_build(
            project_id=project_id,
            query=query,
            section_id=section_id,
            top_k=top_k,
        )

    @mcp.tool(name="literature.project_scan_folder", structured_output=True)
    def literature_project_scan_folder(
        project_id: str,
        scan_mode: str = "fast",
        batch_size: int = 24,
        max_workers: int = 8,
    ) -> dict[str, Any]:
        """Submit project source-folder ingestion as a runtime job."""
        return runtime.project_scan_folder(
            project_id=project_id,
            scan_mode=scan_mode,
            batch_size=batch_size,
            max_workers=max_workers,
        )

    @mcp.tool(name="literature.figures_candidates", structured_output=True)
    def literature_figures_candidates(
        project_id: str,
        limit: int = 20,
        pixel_only: bool = False,
        render_pdf_fallback: bool = True,
    ) -> dict[str, Any]:
        """List backend-derived figure/table candidates."""
        return runtime.figures_candidates(
            project_id=project_id,
            limit=limit,
            pixel_only=pixel_only,
            render_pdf_fallback=render_pdf_fallback,
        )

    @mcp.tool(name="literature.figures_generate", structured_output=True)
    def literature_figures_generate(
        project_id: str,
        candidate_ids: list[str] | None = None,
        max_items: int = 1,
        kind: str | None = None,
        overwrite_existing: bool = False,
    ) -> dict[str, Any]:
        """Materialize existing pixel-backed figure/table candidates."""
        return runtime.figures_generate(
            project_id=project_id,
            candidate_ids=candidate_ids,
            max_items=max_items,
            kind=kind,
            overwrite_existing=overwrite_existing,
        )

    @mcp.tool(name="literature.citations_sources", structured_output=True)
    def literature_citations_sources(project_id: str) -> dict[str, Any]:
        """List backend-managed citation source metadata."""
        return runtime.citations_sources(project_id=project_id)

    @mcp.tool(name="literature.citations_detect_overlap", structured_output=True)
    def literature_citations_detect_overlap(
        project_id: str,
        anchors: list[dict[str, Any]],
        threshold: float = 0.7,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        """Detect citation anchors that reuse the same or similar evidence."""
        return runtime.citations_detect_overlap(
            project_id=project_id,
            anchors=anchors,
            threshold=threshold,
            draft_id=draft_id,
        )

    @mcp.tool(name="literature.academic_writing_lint", structured_output=True)
    def literature_academic_writing_lint(
        text: str | None = None,
        html: str | None = None,
        content_type: str = "manuscript",
        language: str = "auto",
        required_sections: list[str] | None = None,
        require_evidence_refs: bool = True,
        require_figure_table_formula_refs: bool = False,
        style_profile: str | None = None,
        audit_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Check scholarly writing quality before export or submission."""
        return runtime.academic_writing_lint(
            text=text,
            html=html,
            content_type=content_type,
            language=language,
            required_sections=required_sections,
            require_evidence_refs=require_evidence_refs,
            require_figure_table_formula_refs=require_figure_table_formula_refs,
            style_profile=style_profile,
            audit_context=audit_context,
        )

    @mcp.tool(name="literature.outline_generate", structured_output=True)
    def literature_outline_generate(
        project_id: str,
        topic: str,
        content_type: str = "academic",
        target_length: int | None = None,
        focus_areas: list[str] | None = None,
        existing_materials: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate an evidence-grounded writing outline."""
        return runtime.outline_generate(
            project_id=project_id,
            topic=topic,
            content_type=content_type,
            target_length=target_length,
            focus_areas=focus_areas,
            existing_materials=existing_materials,
        )

    @mcp.tool(name="literature.export_annotations_markdown", structured_output=True)
    def literature_export_annotations_markdown(material_id: str) -> dict[str, Any]:
        """Export material annotations as Markdown."""
        return runtime.export_annotations_markdown(material_id=material_id)

    @mcp.tool(name="literature.export_docx", structured_output=True)
    def literature_export_docx(
        html: str,
        title: str,
        style_profile: str = "gb_t_7714_review",
        verify_with_word: bool = False,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Export scholarly HTML as a DOCX workflow artifact."""
        return runtime.export_docx(
            html=html,
            title=title,
            style_profile=style_profile,
            verify_with_word=verify_with_word,
            project_id=project_id,
        )

    @mcp.tool(name="literature.journal_style_spec_draft", structured_output=True)
    def literature_journal_style_spec_draft(
        project_id: str,
        journal_name: str,
        spec_text: str,
    ) -> dict[str, Any]:
        """Create a reviewable project-scoped journal style profile draft."""
        return runtime.journal_style_spec_draft(
            project_id=project_id,
            journal_name=journal_name,
            spec_text=spec_text,
        )

    @mcp.tool(name="literature.journal_style_spec_confirm", structured_output=True)
    def literature_journal_style_spec_confirm(
        project_id: str,
        draft_id: str,
        confirmed_by: str = "mcp",
    ) -> dict[str, Any]:
        """Confirm a project-scoped journal style profile draft."""
        return runtime.journal_style_spec_confirm(
            project_id=project_id,
            draft_id=draft_id,
            confirmed_by=confirmed_by,
        )

    @mcp.tool(name="literature.agent_bridge_status", structured_output=True)
    def literature_agent_bridge_status(limit: int = 20) -> dict[str, Any]:
        """Read the runtime-backed agent bridge status."""
        return runtime.agent_bridge_status(limit=limit)

    @mcp.tool(name="literature.agent_request_create", structured_output=True)
    def literature_agent_request_create(
        intent: str,
        user_text: str = "",
        project_id: str | None = None,
        runtime_session_id: str | None = None,
        chat_session_id: str | None = None,
        route: str | None = None,
        resource_refs: list[dict[str, Any]] | None = None,
        agent_host: str = "mcp",
        source: str = "mcp",
        max_chars: int = 12000,
        max_chunks: int = 12,
        smart_read_conversation: bool = False,
        wiki_candidate: bool = False,
        graph_candidate: bool = False,
        evolution_capture: bool = True,
    ) -> dict[str, Any]:
        """Create a frontend-visible runtime job for external agent work."""
        return runtime.agent_request_create(
            intent=intent,
            user_text=user_text,
            project_id=project_id,
            runtime_session_id=runtime_session_id,
            chat_session_id=chat_session_id,
            route=route,
            resource_refs=resource_refs,
            agent_host=agent_host,
            source=source,
            max_chars=max_chars,
            max_chunks=max_chunks,
            smart_read_conversation=smart_read_conversation,
            wiki_candidate=wiki_candidate,
            graph_candidate=graph_candidate,
            evolution_capture=evolution_capture,
        )

    @mcp.tool(name="literature.agent_request_list", structured_output=True)
    def literature_agent_request_list(
        status: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List runtime-visible agent requests."""
        return runtime.agent_request_list(status=status, project_id=project_id, source=source, limit=limit)

    @mcp.tool(name="literature.agent_request_read", structured_output=True)
    def literature_agent_request_read(request_id: str) -> dict[str, Any]:
        """Read one runtime-visible agent request."""
        return runtime.agent_request_read(request_id=request_id)

    @mcp.tool(name="literature.agent_resource_read", structured_output=True)
    def literature_agent_resource_read(
        ref_id: str,
        project_id: str | None = None,
        max_chars: int = 6000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read a bounded resource ref for an agent request."""
        return runtime.agent_resource_read(
            ref_id=ref_id,
            project_id=project_id,
            max_chars=max_chars,
            cursor=cursor,
        )

    @mcp.tool(name="literature.agent_progress", structured_output=True)
    def literature_agent_progress(
        request_id: str,
        stage: str,
        message: str,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a short progress delta to an agent request job."""
        return runtime.agent_progress(
            request_id=request_id,
            stage=stage,
            message=message,
            progress=progress,
            data=data,
        )

    @mcp.tool(name="literature.agent_result", structured_output=True)
    def literature_agent_result(
        request_id: str,
        text: str = "",
        content: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        wiki_refs: list[dict[str, Any]] | None = None,
        graph_patch_refs: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write final agent output to runtime artifacts."""
        return runtime.agent_result(
            request_id=request_id,
            text=text,
            content=content,
            evidence_refs=evidence_refs,
            wiki_refs=wiki_refs,
            graph_patch_refs=graph_patch_refs,
            metadata=metadata,
        )

    @mcp.tool(name="literature.agent_fail", structured_output=True)
    def literature_agent_fail(request_id: str, error: str) -> dict[str, Any]:
        """Fail a runtime-visible agent request job."""
        return runtime.agent_fail(request_id=request_id, error=error)

    @mcp.tool(name="literature.ocr_material", structured_output=True)
    def literature_ocr_material(
        material_id: str,
        pages: list[int] | None = None,
        ocr_language: str = "eng",
    ) -> dict[str, Any]:
        """Experimental OCR entrypoint; disabled by default."""
        return experimental.ocr_material(
            material_id=material_id,
            pages=pages,
            ocr_language=ocr_language,
        )

    @mcp.tool(name="literature.prepare_visual_review", structured_output=True)
    def literature_prepare_visual_review(
        project_id: str,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Experimental visual review pack preparation; disabled by default."""
        return experimental.prepare_visual_review(project_id=project_id, query=query, top_k=top_k)

    @mcp.tool(name="literature.translate_pack", structured_output=True)
    def literature_translate_pack(
        project_id: str,
        target_language: str,
        query: str | None = None,
        top_k: int = 8,
        use_model: bool = True,
    ) -> dict[str, Any]:
        """Experimental translation pack entrypoint; disabled by default."""
        return experimental.translate_pack(
            project_id=project_id,
            target_language=target_language,
            query=query,
            top_k=top_k,
            use_model=use_model,
        )

    @mcp.tool(name="literature.export_project_pack", structured_output=True)
    def literature_export_project_pack(
        project_id: str,
        include_search_preview: bool = False,
        query: str = "",
    ) -> dict[str, Any]:
        """Experimental project pack export; disabled by default."""
        return experimental.export_project_pack(
            project_id=project_id,
            include_search_preview=include_search_preview,
            query=query,
        )

    @mcp.tool(name="workflow.create_plan", structured_output=True)
    def workflow_create_plan(
        goal: str,
        suggested_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a JSON workflow plan skeleton."""
        return workflow_impl.create_plan(goal=goal, suggested_steps=suggested_steps)

    @mcp.tool(name="workflow.write_json_workflow", structured_output=True)
    def workflow_write_json_workflow(
        path: str,
        workflow: dict[str, Any],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a JSON workflow artifact."""
        return workflow_impl.write_json_workflow(path=path, workflow=workflow, overwrite=overwrite)

    @mcp.tool(name="workflow.run_json_workflow", structured_output=True)
    def workflow_run_json_workflow(
        workflow: dict[str, Any] | None = None,
        path: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an inline or artifact-backed JSON workflow."""
        return workflow_impl.run_json_workflow(workflow=workflow, path=path, input_data=input_data)

    @mcp.tool(name="workflow.run_python_sandbox", structured_output=True)
    def workflow_run_python_sandbox(script: dict[str, Any]) -> dict[str, Any]:
        """Experimental Python sandbox entrypoint; disabled by default."""
        return experimental.run_python_sandbox(script=script)

    @mcp.tool(name="artifact.write_markdown", structured_output=True)
    def artifact_write_markdown(
        path: str,
        content: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a Markdown artifact under the workflow workspace."""
        return workflow_impl.write_markdown(path=path, content=content, overwrite=overwrite)

    @mcp.tool(name="artifact.read_artifact", structured_output=True)
    def artifact_read_artifact(path: str, max_chars: int = 120000) -> dict[str, Any]:
        """Read a text artifact from the workflow workspace."""
        return workflow_impl.read_artifact(path=path, max_chars=max_chars)

    @mcp.tool(name="artifact.list_artifacts", structured_output=True)
    def artifact_list_artifacts(max_entries: int = 200) -> dict[str, Any]:
        """List workflow artifacts."""
        return workflow_impl.list_artifacts(max_entries=max_entries)

    return mcp


def main() -> None:
    """Run the MCP server over stdio."""
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()

"""FastMCP stdio server for the Literature Assistant local toolbox."""

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

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
        "literature.health_check": runtime.health_check,
        "literature.zotero_attachment_health": runtime.zotero_attachment_health,
        "literature.list_projects": runtime.list_projects,
        "literature.list_materials": runtime.list_materials,
        "literature.read_material": runtime.read_material,
        "literature.get_material_chunks": runtime.get_material_chunks,
        "literature.search_refs": runtime.search_refs,
        "literature.knowledge_packages": runtime.knowledge_packages,
        "literature.knowledge_runtime_conformance": runtime.knowledge_runtime_conformance,
        "literature.ocr_status": runtime.ocr_status,
        "literature.ocr_engines": runtime.ocr_engines,
        "literature.ocr_health": runtime.ocr_health,
        "literature.ocr_execution_probe": runtime.ocr_execution_probe,
        "literature.knowledge_context_receipt": runtime.knowledge_context_receipt,
        "literature.wiki_status": runtime.wiki_status,
        "literature.wiki_doctor": runtime.wiki_doctor,
        "literature.wiki_search": runtime.wiki_search,
        "literature.skill_package_status": runtime.skill_package_status,
        "literature.skill_package_search": runtime.skill_package_search,
        "literature.source_vault_status": runtime.source_vault_status,
        "literature.source_vault_search": runtime.source_vault_search,
        "literature.source_vault_read": runtime.source_vault_read,
        "literature.academic_english_status": runtime.academic_english_status,
        "literature.academic_english_search": runtime.academic_english_search,
        "literature.bridge_lexicon_status": runtime.bridge_lexicon_status,
        "literature.bridge_lexicon_read": runtime.bridge_lexicon_read,
        "literature.bridge_lexicon_search": runtime.bridge_lexicon_search,
        "literature.scoring_rules_status": runtime.scoring_rules_status,
        "literature.scoring_rules_read": runtime.scoring_rules_read,
        "literature.scoring_rules_search": runtime.scoring_rules_search,
        "literature.product_docs_status": runtime.product_docs_status,
        "literature.product_docs_read": runtime.product_docs_read,
        "literature.product_docs_search": runtime.product_docs_search,
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
        "literature.agent_workspace_status": runtime.agent_workspace_status,
        "literature.agent_workspace_requirement": runtime.agent_workspace_requirement,
        "literature.agent_request_create": runtime.agent_request_create,
        "literature.wiki_import": runtime.wiki_import,
        "literature.single_paper_task_create": runtime.single_paper_task_create,
        "literature.single_paper_completion_check": runtime.single_paper_completion_check,
        "literature.agent_request_list": runtime.agent_request_list,
        "literature.agent_request_read": runtime.agent_request_read,
        "literature.agent_handoff_card": runtime.agent_handoff_card,
        "literature.behavior_eval_pack": runtime.behavior_eval_pack,
        "literature.workflow_passport": runtime.workflow_passport,
        "literature.evidence_integrity_gate": runtime.evidence_integrity_gate,
        "literature.research_action_lifecycle": runtime.research_action_lifecycle,
        "literature.workflow_refresh_receipt": runtime.workflow_refresh_receipt,
        "literature.workflow_replay_lineage": runtime.workflow_replay_lineage,
        "literature.workflow_replay_index": runtime.workflow_replay_index,
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
        instructions=(
            "Scholar AI (文献助手) local MCP toolbox. "
            "On connect: literature.config_status / literature.health_check, "
            "then literature.list_projects to pick a project_id.\n"
            "Tool groups: source.* = read-only source inspection (tools/source.py); "
            "literature.* = HTTP to backend literature_assistant/core (tools/runtime.py); "
            "workflow.* / artifact.* = JSON workflow + artifacts (tools/workflow.py); "
            "experimental OCR/visual/translate/pack/sandbox gated by "
            "LITASSIST_MCP_ENABLE_EXPERIMENTAL_TOOLS=1 (tools/experimental.py).\n"
            "Typical chains: cite-with-evidence = search_refs -> evidence_pack_build "
            "-> evidence_integrity_gate; write = evidence_pack_build -> outline_generate "
            "-> academic_writing_lint -> figures_generate -> export_docx; "
            "read-code = source.inspect_routes -> source.read_symbols -> source.read_file.\n"
            "Full scenario map + tool->code three-hop locator: "
            "source.read_file path=agent_mcp_server/CAPABILITY_MAP.md.\n"
            "Never read/export .env*, credentials, runtime state, logs, browser "
            "profiles, rollback snapshots, .claude/, .codex/."
        ),
    )

    @mcp.tool(
        name="source.list_tree",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source List Tree",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_list_tree(
        root: str = ".",
        max_depth: int = 3,
        max_entries: int = 500,
    ) -> dict[str, Any]:
        """List allowed source files and directories."""
        return source.list_tree(root=root, max_depth=max_depth, max_entries=max_entries)

    @mcp.tool(
        name="source.search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="source.read_file",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Read File",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_read_file(path: str, max_chars: int = 80000) -> dict[str, Any]:
        """Read an allowed source text file."""
        return source.read_file(path=path, max_chars=max_chars)

    @mcp.tool(
        name="source.read_symbols",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Read Symbols",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_read_symbols(path: str) -> dict[str, Any]:
        """Read top-level Python symbols from an allowed source file."""
        return source.read_symbols(path=path)

    @mcp.tool(
        name="source.inspect_routes",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Inspect Routes",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_inspect_routes(
        root: str = "literature_assistant/core",
        max_routes: int = 200,
    ) -> dict[str, Any]:
        """Inspect FastAPI route decorators without importing modules."""
        return source.inspect_routes(root=root, max_routes=max_routes)

    @mcp.tool(
        name="source.find_references",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Find References",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_find_references(
        symbol: str,
        root: str = ".",
        max_results: int = 100,
    ) -> dict[str, Any]:
        """Find bounded static references to an identifier or literal text."""
        return source.find_references(symbol=symbol, root=root, max_results=max_results)

    @mcp.tool(
        name="source.explain_entrypoints",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Explain Entrypoints",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def source_explain_entrypoints(
        path: str,
        max_depth: int = 2,
        max_files: int = 30,
    ) -> dict[str, Any]:
        """Sketch imports reachable from a Python entrypoint."""
        return source.explain_entrypoints(path=path, max_depth=max_depth, max_files=max_files)

    @mcp.tool(
        name="literature.config_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Config Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_config_status() -> dict[str, Any]:
        """Return Literature Assistant backend health."""
        return runtime.config_status()

    @mcp.tool(
        name="literature.health_check",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Health Check",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_health_check(include_live: bool = False) -> dict[str, Any]:
        """Return passive Scholar AI workflow readiness diagnostics."""
        return runtime.health_check(include_live=include_live)

    @mcp.tool(
        name="literature.zotero_attachment_health",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Zotero Attachment Health",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_zotero_attachment_health(
        zotero_data_dir: str,
        allowed_root: str | None = None,
        min_text_chars: int = 200,
        max_items: int = 500,
        write_reports: bool = True,
    ) -> dict[str, Any]:
        """Return Zotero attachment health diagnostics with optional local reports."""
        return runtime.zotero_attachment_health(
            zotero_data_dir=zotero_data_dir,
            allowed_root=allowed_root,
            min_text_chars=min_text_chars,
            max_items=max_items,
            write_reports=write_reports,
        )

    @mcp.tool(
        name="literature.list_projects",
        structured_output=True,
        annotations=ToolAnnotations(
            title="List Projects",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_list_projects() -> dict[str, Any]:
        """List Literature Assistant projects."""
        return runtime.list_projects()

    @mcp.tool(
        name="literature.list_materials",
        structured_output=True,
        annotations=ToolAnnotations(
            title="List Materials",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_list_materials(project_id: str) -> dict[str, Any]:
        """List materials for a project."""
        return runtime.list_materials(project_id=project_id)

    @mcp.tool(
        name="literature.read_material",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Read Material",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_read_material(material_id: str) -> dict[str, Any]:
        """Read a material record."""
        return runtime.read_material(material_id=material_id)

    @mcp.tool(
        name="literature.get_material_chunks",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Get Material Chunks",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_get_material_chunks(project_id: str, material_id: str) -> dict[str, Any]:
        """Read chunks for a material."""
        return runtime.get_material_chunks(project_id=project_id, material_id=material_id)

    @mcp.tool(
        name="literature.search_refs",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Search Refs",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_search_refs(
        project_id: str,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search existing project chunks and return refs only."""
        return runtime.search_refs(project_id=project_id, query=query, top_k=top_k)

    @mcp.tool(
        name="literature.knowledge_packages",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Knowledge Packages",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_knowledge_packages() -> dict[str, Any]:
        """Return the unified read-only runtime knowledge package registry."""
        return runtime.knowledge_packages()

    @mcp.tool(
        name="literature.knowledge_runtime_conformance",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Knowledge Runtime Conformance",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_knowledge_runtime_conformance() -> dict[str, Any]:
        """Return read-only Knowledge Runtime Pipeline conformance status."""
        return runtime.knowledge_runtime_conformance()

    @mcp.tool(
        name="literature.ocr_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_ocr_status() -> dict[str, Any]:
        """Return the redacted OCR runtime status without running OCR."""
        return runtime.ocr_status()

    @mcp.tool(
        name="literature.ocr_engines",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Engines",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_ocr_engines() -> dict[str, Any]:
        """Return registered OCR engine metadata without running OCR."""
        return runtime.ocr_engines()

    @mcp.tool(
        name="literature.ocr_health",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Health",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_ocr_health(
        engine: str | None = None,
        engine_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a lightweight OCR engine readiness probe without OCR content upload."""
        return runtime.ocr_health(engine=engine, engine_config=engine_config)

    @mcp.tool(
        name="literature.ocr_execution_probe",
        structured_output=True,
        annotations=ToolAnnotations(
            title="OCR Execution Probe",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    def literature_ocr_execution_probe(
        confirm_execution: bool = False,
        image_base64: str | None = None,
        image_path: str | None = None,
        engine: str | None = None,
        engine_config: dict[str, Any] | None = None,
        language: str = "en",
        preview_chars: int = 240,
    ) -> dict[str, Any]:
        """Run one explicit OCR execution probe and return bounded proof."""
        return runtime.ocr_execution_probe(
            confirm_execution=confirm_execution,
            image_base64=image_base64,
            image_path=image_path,
            engine=engine,
            engine_config=engine_config,
            language=language,
            preview_chars=preview_chars,
        )

    @mcp.tool(
        name="literature.knowledge_context_receipt",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Knowledge Context Receipt",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_knowledge_context_receipt(
        ref_ids: list[str],
        project_id: str | None = None,
        prompt_name: str = "knowledge_runtime_context",
        max_chars_per_ref: int = 1200,
    ) -> dict[str, Any]:
        """Prove bounded knowledge refs entered model-context input."""
        return runtime.knowledge_context_receipt(
            ref_ids=ref_ids,
            project_id=project_id,
            prompt_name=prompt_name,
            max_chars_per_ref=max_chars_per_ref,
        )

    @mcp.tool(
        name="literature.wiki_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Wiki Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_wiki_status(user_id: str | None = None) -> dict[str, Any]:
        """Return the wiki package runtime status and manifest drilldown."""
        return runtime.wiki_status(user_id=user_id)

    @mcp.tool(
        name="literature.wiki_doctor",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Wiki Doctor",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_wiki_doctor() -> dict[str, Any]:
        """Return read-only wiki integrity diagnostics for recovery agents."""
        return runtime.wiki_doctor()

    @mcp.tool(
        name="literature.wiki_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Wiki Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_wiki_search(
        query: str,
        top_k: int = 8,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Search wiki knowledge and return bounded refs."""
        return runtime.wiki_search(query=query, top_k=top_k, user_id=user_id)

    @mcp.tool(
        name="literature.skill_package_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Skill Package Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_skill_package_status(
        package_id: str = "academic-english-discourse",
    ) -> dict[str, Any]:
        """Return one supported Skill package provenance status."""
        return runtime.skill_package_status(package_id=package_id)

    @mcp.tool(
        name="literature.skill_package_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Skill Package Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_skill_package_search(
        query: str,
        package_id: str = "academic-english-discourse",
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search one supported Skill package and return bounded refs."""
        return runtime.skill_package_search(query=query, package_id=package_id, top_k=top_k)

    @mcp.tool(
        name="literature.source_vault_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Vault Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_source_vault_status(limit: int = 50) -> dict[str, Any]:
        """Return Source Vault package status and recent source records."""
        return runtime.source_vault_status(limit=limit)

    @mcp.tool(
        name="literature.source_vault_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Vault Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_source_vault_search(
        query: str,
        top_k: int = 8,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Search Source Vault chunks and return bounded refs."""
        return runtime.source_vault_search(query=query, top_k=top_k, project_id=project_id)

    @mcp.tool(
        name="literature.source_vault_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Source Vault Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_source_vault_read(
        ref_id: str,
        project_id: str | None = None,
        max_chars: int = 6000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded Source Vault chunk resource."""
        return runtime.source_vault_read(
            ref_id=ref_id,
            project_id=project_id,
            max_chars=max_chars,
            cursor=cursor,
        )

    @mcp.tool(
        name="literature.academic_english_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Academic English Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_academic_english_status() -> dict[str, Any]:
        """Return academic-English knowledge manifest and artifact status."""
        return runtime.academic_english_status()

    @mcp.tool(
        name="literature.academic_english_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Academic English Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_academic_english_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search academic-English knowledge and return bounded refs."""
        return runtime.academic_english_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.bridge_lexicon_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Bridge Lexicon Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_bridge_lexicon_status() -> dict[str, Any]:
        """Return CJK bridge lexicon provenance and runtime consumer status."""
        return runtime.bridge_lexicon_status()

    @mcp.tool(
        name="literature.bridge_lexicon_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Bridge Lexicon Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_bridge_lexicon_read() -> dict[str, Any]:
        """Read the bounded CJK bridge lexicon runtime artifact."""
        return runtime.bridge_lexicon_read()

    @mcp.tool(
        name="literature.bridge_lexicon_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Bridge Lexicon Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_bridge_lexicon_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search bridge-lexicon entries and return bounded refs."""
        return runtime.bridge_lexicon_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.scoring_rules_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Scoring Rules Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_scoring_rules_status() -> dict[str, Any]:
        """Return scoring-rules JSON config provenance and runtime consumer status."""
        return runtime.scoring_rules_status()

    @mcp.tool(
        name="literature.scoring_rules_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Scoring Rules Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_scoring_rules_read() -> dict[str, Any]:
        """Read the bounded scoring-rules JSON config runtime artifact."""
        return runtime.scoring_rules_read()

    @mcp.tool(
        name="literature.scoring_rules_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Scoring Rules Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_scoring_rules_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search scoring-rules JSON config knowledge and return bounded refs."""
        return runtime.scoring_rules_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.product_docs_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Product Docs Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_product_docs_status() -> dict[str, Any]:
        """Return product-docs Markdown provenance and runtime consumer status."""
        return runtime.product_docs_status()

    @mcp.tool(
        name="literature.product_docs_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Product Docs Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_product_docs_read() -> dict[str, Any]:
        """Read the bounded product-docs runtime artifact."""
        return runtime.product_docs_read()

    @mcp.tool(
        name="literature.product_docs_search",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Product Docs Search",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_product_docs_search(
        query: str,
        top_k: int = 8,
    ) -> dict[str, Any]:
        """Search product-docs Markdown knowledge and return bounded refs."""
        return runtime.product_docs_search(query=query, top_k=top_k)

    @mcp.tool(
        name="literature.evidence_pack_build",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Evidence Pack Build",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.project_scan_folder",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Project Scan Folder",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.citations_sources",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Citation Sources",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_citations_sources(project_id: str) -> dict[str, Any]:
        """List backend-managed citation source metadata."""
        return runtime.citations_sources(project_id=project_id)

    @mcp.tool(
        name="literature.citations_detect_overlap",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Citation Overlap Diagnostic",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.academic_writing_lint",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Academic Writing Lint",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.export_annotations_markdown",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Export Annotations Markdown",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_export_annotations_markdown(material_id: str) -> dict[str, Any]:
        """Export material annotations as Markdown."""
        return runtime.export_annotations_markdown(material_id=material_id)

    @mcp.tool(
        name="literature.export_docx",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Export DOCX",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_export_docx(
        html: str,
        title: str,
        style_profile: str = "gb_t_7714_review",
        verify_with_word: bool = False,
        project_id: str | None = None,
        require_action_preflight: bool = False,
    ) -> dict[str, Any]:
        """Export scholarly HTML as a DOCX workflow artifact."""
        return runtime.export_docx(
            html=html,
            title=title,
            style_profile=style_profile,
            verify_with_word=verify_with_word,
            project_id=project_id,
            require_action_preflight=require_action_preflight,
        )

    @mcp.tool(
        name="literature.journal_style_spec_draft",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Journal Style Draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.journal_style_spec_confirm",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Journal Style Confirm",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.agent_bridge_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Bridge Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_bridge_status(limit: int = 20) -> dict[str, Any]:
        """Read the runtime-backed agent bridge status."""
        return runtime.agent_bridge_status(limit=limit)

    @mcp.tool(
        name="literature.agent_workspace_status",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Workspace Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_workspace_status(
        artifact_limit: int = 200,
        audit_limit: int = 200,
    ) -> dict[str, Any]:
        """Read the Agent Workspace status and workspace recovery state."""
        return runtime.agent_workspace_status(artifact_limit=artifact_limit, audit_limit=audit_limit)

    @mcp.tool(
        name="literature.agent_workspace_requirement",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Workspace Requirement",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_workspace_requirement(
        requirement_id: str,
    ) -> dict[str, Any]:
        """Read one Agent Workspace requirement-to-evidence drilldown."""
        return runtime.agent_workspace_requirement(requirement_id=requirement_id)

    @mcp.tool(
        name="literature.agent_request_create",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Request Create",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.wiki_import",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Import Markdown to Wiki",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_wiki_import(
        source_paths: list[str],
        dry_run: bool = True,
        confirm_write: bool = False,
        overwrite: bool = False,
        kind: str = "synthesis",
        status: str = "draft",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Import local Markdown files into private wiki pages."""
        return runtime.wiki_import(
            source_paths=source_paths,
            dry_run=dry_run,
            confirm_write=confirm_write,
            overwrite=overwrite,
            kind=kind,
            status=status,
            user_id=user_id,
        )

    @mcp.tool(
        name="literature.single_paper_task_create",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Single Paper Task Create",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_single_paper_task_create(
        project_id: str,
        material_id: str,
        task_goal: str = "生成单篇论文深度精读、写作借鉴要点、可导出 Word 的结构化草稿",
        output_language: str = "zh",
        target_document: str = "word_draft",
        create_agent_request: bool = True,
        agent_host: str = "mcp",
        source: str = "mcp",
        max_chars: int = 12000,
        max_chunks: int = 12,
    ) -> dict[str, Any]:
        """Create a dynamic single-paper deep-reading task instance."""
        return runtime.single_paper_task_create(
            project_id=project_id,
            material_id=material_id,
            task_goal=task_goal,
            output_language=output_language,
            target_document=target_document,
            create_agent_request=create_agent_request,
            agent_host=agent_host,
            source=source,
            max_chars=max_chars,
            max_chunks=max_chunks,
        )

    @mcp.tool(
        name="literature.single_paper_completion_check",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Single Paper Completion Check",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_single_paper_completion_check(
        output_text: str,
        task_manifest: dict[str, Any],
        required_output_sections: list[str] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        figure_table_refs: list[dict[str, Any]] | None = None,
        lint_passed: bool = False,
        docx_artifact_path: str | None = None,
        sentinel: str = "待补充",
    ) -> dict[str, Any]:
        """Validate a completed single-paper deep-reading draft."""
        return runtime.single_paper_completion_check(
            output_text=output_text,
            task_manifest=task_manifest,
            required_output_sections=required_output_sections,
            evidence_refs=evidence_refs,
            figure_table_refs=figure_table_refs,
            lint_passed=lint_passed,
            docx_artifact_path=docx_artifact_path,
            sentinel=sentinel,
        )

    @mcp.tool(
        name="literature.agent_request_list",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Request List",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_request_list(
        status: str | None = None,
        project_id: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List runtime-visible agent requests."""
        return runtime.agent_request_list(status=status, project_id=project_id, source=source, limit=limit)

    @mcp.tool(
        name="literature.agent_request_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Request Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_request_read(request_id: str) -> dict[str, Any]:
        """Read one runtime-visible agent request."""
        return runtime.agent_request_read(request_id=request_id)

    @mcp.tool(
        name="literature.agent_handoff_card",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Handoff Card",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_agent_handoff_card(request_id: str) -> dict[str, Any]:
        """Read a resumable handoff card for one runtime-visible agent request."""
        return runtime.agent_handoff_card(request_id=request_id)

    @mcp.tool(
        name="literature.behavior_eval_pack",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Behavior Eval Pack",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def literature_behavior_eval_pack(
        observations: list[dict[str, Any]] | None = None,
        include_cases: bool = True,
        write_record: bool = True,
    ) -> dict[str, Any]:
        """Run deterministic local red-flag evals for MCP and agent outputs."""
        return runtime.behavior_eval_pack(
            observations=observations,
            include_cases=include_cases,
            write_record=write_record,
        )

    @mcp.tool(
        name="literature.workflow_passport",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Passport",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_passport(
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Read the runtime workflow passport projection."""
        return runtime.workflow_passport(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.evidence_integrity_gate",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Evidence Integrity Gate",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_evidence_integrity_gate(
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Read the runtime evidence integrity gate projection."""
        return runtime.evidence_integrity_gate(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.research_action_lifecycle",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Research Action Lifecycle",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_research_action_lifecycle(
        session_id: str | None = None,
        job_id: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Read the runtime research action lifecycle projection."""
        return runtime.research_action_lifecycle(
            session_id=session_id,
            job_id=job_id,
            project_id=project_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.workflow_refresh_receipt",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Refresh Receipt",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_refresh_receipt(
        job_id: str,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Read a persisted workflow refresh/replay receipt for one runtime job."""
        return runtime.workflow_refresh_receipt(job_id=job_id, receipt_id=receipt_id)

    @mcp.tool(
        name="literature.workflow_replay_lineage",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Replay Lineage",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_replay_lineage(
        job_id: str,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Read compact workflow replay lineage for one runtime job."""
        return runtime.workflow_replay_lineage(job_id=job_id, limit=limit)

    @mcp.tool(
        name="literature.workflow_replay_index",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Replay Index",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def literature_workflow_replay_index(
        project_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        action_id: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Read a bounded cross-job workflow replay index for recovery."""
        return runtime.workflow_replay_index(
            project_id=project_id,
            session_id=session_id,
            status=status,
            action_id=action_id,
            limit=limit,
        )

    @mcp.tool(
        name="literature.agent_resource_read",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Resource Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.agent_progress",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Progress",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.agent_result",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Result",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="literature.agent_fail",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Agent Fail",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="workflow.create_plan",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Create Plan",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def workflow_create_plan(
        goal: str,
        suggested_steps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a JSON workflow plan skeleton."""
        return workflow_impl.create_plan(goal=goal, suggested_steps=suggested_steps)

    @mcp.tool(
        name="workflow.write_json_workflow",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Workflow Write JSON",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
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

    @mcp.tool(
        name="artifact.write_markdown",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Artifact Write Markdown",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def artifact_write_markdown(
        path: str,
        content: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Write a Markdown artifact under the workflow workspace."""
        return workflow_impl.write_markdown(path=path, content=content, overwrite=overwrite)

    @mcp.tool(
        name="artifact.read_artifact",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Artifact Read",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def artifact_read_artifact(path: str, max_chars: int = 120000) -> dict[str, Any]:
        """Read a text artifact from the workflow workspace."""
        return workflow_impl.read_artifact(path=path, max_chars=max_chars)

    @mcp.tool(
        name="artifact.list_artifacts",
        structured_output=True,
        annotations=ToolAnnotations(
            title="Artifact List",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def artifact_list_artifacts(max_entries: int = 200) -> dict[str, Any]:
        """List workflow artifacts."""
        return workflow_impl.list_artifacts(max_entries=max_entries)

    return mcp


def main() -> None:
    """Run the MCP server over stdio."""
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()

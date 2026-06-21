# -*- coding: utf-8 -*-
"""Built-in Literature Assistant tool bridge for source-launched chat."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final

from mcp_runtime.provider_tool_adapter import parse_namespaced_tool
from mcp_runtime.tool_dispatcher import DispatchInput
from mcp_runtime.tool_result_formatter import ToolResultRecord, build_tool_result_record
from models.mcp import (
    McpApprovalState,
    McpProvenance,
    McpServerConfig,
    McpStdioConfig,
    McpToolCapability,
    McpToolDescriptor,
    McpTransport,
)


BUILTIN_SERVER_ID: Final[str] = "builtin_literature_assistant"
BUILTIN_SERVER_SLUG: Final[str] = "literature"
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_MCP_SRC_ROOT: Final[Path] = _REPO_ROOT / "agent_mcp_server" / "src"


@dataclass(frozen=True)
class _ToolSpec:
    """Local tool metadata and dispatcher binding."""

    name: str
    description: str
    input_schema: dict[str, Any]
    capability: McpToolCapability
    method_name: str


_TOOL_SPECS: Final[tuple[_ToolSpec, ...]] = (
    _ToolSpec(
        name="literature.list_projects",
        description="List Literature Assistant projects without local source-folder paths.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        capability=McpToolCapability.READ,
        method_name="list_projects",
    ),
    _ToolSpec(
        name="literature.list_materials",
        description="List materials for a project.",
        input_schema={
            "type": "object",
            "properties": {"project_id": {"type": "string", "minLength": 1}},
            "required": ["project_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="list_materials",
    ),
    _ToolSpec(
        name="literature.read_material",
        description="Read one material record.",
        input_schema={
            "type": "object",
            "properties": {"material_id": {"type": "string", "minLength": 1}},
            "required": ["material_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="read_material",
    ),
    _ToolSpec(
        name="literature.get_material_chunks",
        description="Read project-scoped chunks for a material.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "material_id": {"type": "string", "minLength": 1},
            },
            "required": ["project_id", "material_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="get_material_chunks",
    ),
    _ToolSpec(
        name="literature.search_refs",
        description="Search project chunks and return bounded refs, not full source text.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "query": {"type": "string", "minLength": 1},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "required": ["project_id", "query"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="search_refs",
    ),
    _ToolSpec(
        name="literature.evidence_pack_build",
        description="Build a query-scoped evidence pack from backend-managed refs.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "query": {"type": "string", "minLength": 1},
                "section_id": {"type": "string"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
            "required": ["project_id", "query"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="evidence_pack_build",
    ),
    _ToolSpec(
        name="literature.agent_resource_read",
        description="Read a bounded resource ref. Chunk refs must carry project_id.",
        input_schema={
            "type": "object",
            "properties": {
                "ref_id": {"type": "string", "minLength": 1},
                "project_id": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 100, "maximum": 20000, "default": 6000},
                "cursor": {"type": "string"},
            },
            "required": ["ref_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="agent_resource_read",
    ),
    _ToolSpec(
        name="literature.outline_generate",
        description="Generate an evidence-grounded writing outline.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "topic": {"type": "string", "minLength": 1},
                "content_type": {"type": "string", "default": "academic"},
                "target_length": {"type": "integer", "minimum": 100, "maximum": 200000},
                "focus_areas": {"type": "array", "items": {"type": "string"}},
                "existing_materials": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_id", "topic"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="outline_generate",
    ),
    _ToolSpec(
        name="literature.figures_candidates",
        description="List backend-derived figure and table candidates.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "pixel_only": {"type": "boolean", "default": False},
                "render_pdf_fallback": {"type": "boolean", "default": True},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="figures_candidates",
    ),
    _ToolSpec(
        name="literature.citations_sources",
        description="List backend-managed citation metadata for a project.",
        input_schema={
            "type": "object",
            "properties": {"project_id": {"type": "string", "minLength": 1}},
            "required": ["project_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="citations_sources",
    ),
    _ToolSpec(
        name="literature.citations_detect_overlap",
        description="Detect citation anchors that reuse the same or similar evidence.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "anchors": {"type": "array", "items": {"type": "object"}},
                "threshold": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.7},
                "draft_id": {"type": "string"},
            },
            "required": ["project_id", "anchors"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="citations_detect_overlap",
    ),
    _ToolSpec(
        name="literature.academic_writing_lint",
        description="Check scholarly writing structure, evidence, tone, and figure/table/formula references.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "html": {"type": "string"},
                "content_type": {
                    "type": "string",
                    "enum": ["review", "introduction", "manuscript", "section"],
                    "default": "manuscript",
                },
                "language": {"type": "string", "enum": ["zh", "en", "auto"], "default": "auto"},
                "required_sections": {"type": "array", "items": {"type": "string"}},
                "require_evidence_refs": {"type": "boolean", "default": True},
                "require_figure_table_formula_refs": {"type": "boolean", "default": False},
                "style_profile": {"type": "string"},
                "audit_context": {"type": "object"},
            },
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="academic_writing_lint",
    ),
    _ToolSpec(
        name="source.list_tree",
        description="List allowed source files and directories.",
        input_schema={
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "."},
                "max_depth": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 500},
            },
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="source.list_tree",
    ),
    _ToolSpec(
        name="source.search",
        description="Search allowed source files for literal text.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "root": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "case_sensitive": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="source.search",
    ),
    _ToolSpec(
        name="source.read_file",
        description="Read an allowed source text file with secret redaction.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 80000, "default": 80000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="source.read_file",
    ),
    _ToolSpec(
        name="source.inspect_routes",
        description="Inspect FastAPI route decorators without importing modules.",
        input_schema={
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "literature_assistant/core"},
                "max_routes": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
            },
            "additionalProperties": False,
        },
        capability=McpToolCapability.READ,
        method_name="source.inspect_routes",
    ),
    _ToolSpec(
        name="literature.project_scan_folder",
        description="Submit project source-folder ingestion as a runtime job.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "scan_mode": {"type": "string", "enum": ["fast", "legacy"], "default": "fast"},
                "batch_size": {"type": "integer", "minimum": 1, "maximum": 256, "default": 24},
                "max_workers": {"type": "integer", "minimum": 1, "maximum": 64, "default": 8},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.WRITE,
        method_name="project_scan_folder",
    ),
    _ToolSpec(
        name="literature.figures_generate",
        description="Materialize existing pixel-backed figure/table candidates.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "candidate_ids": {"type": "array", "items": {"type": "string"}},
                "max_items": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1},
                "kind": {"type": "string", "enum": ["figure", "table"]},
                "overwrite_existing": {"type": "boolean", "default": False},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.WRITE,
        method_name="figures_generate",
    ),
    _ToolSpec(
        name="literature.export_docx",
        description="Export scholarly HTML as a DOCX workflow artifact.",
        input_schema={
            "type": "object",
            "properties": {
                "html": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "style_profile": {"type": "string", "default": "gb_t_7714_review"},
                "verify_with_word": {"type": "boolean", "default": False},
                "project_id": {"type": "string"},
            },
            "required": ["html", "title"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.WRITE,
        method_name="export_docx",
    ),
    _ToolSpec(
        name="literature.journal_style_spec_draft",
        description="Draft a reviewable project-scoped journal style profile.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "journal_name": {"type": "string", "minLength": 1},
                "spec_text": {"type": "string", "minLength": 20},
            },
            "required": ["project_id", "journal_name", "spec_text"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.WRITE,
        method_name="journal_style_spec_draft",
    ),
    _ToolSpec(
        name="literature.journal_style_spec_confirm",
        description="Confirm a project-scoped journal style profile draft.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "minLength": 1},
                "draft_id": {"type": "string", "minLength": 1},
                "confirmed_by": {"type": "string", "default": "api-chat"},
            },
            "required": ["project_id", "draft_id"],
            "additionalProperties": False,
        },
        capability=McpToolCapability.WRITE,
        method_name="journal_style_spec_confirm",
    ),
    _ToolSpec(
        name="literature.agent_request_create",
        description="Create a frontend-visible runtime job for external agent work.",
        input_schema={
            "type": "object",
            "properties": {
                "intent": {"type": "string", "minLength": 1},
                "user_text": {"type": "string"},
                "project_id": {"type": "string"},
                "resource_refs": {"type": "array", "items": {"type": "object"}},
                "agent_host": {"type": "string", "default": "api-chat"},
                "source": {"type": "string", "default": "api-chat"},
                "max_chars": {"type": "integer", "minimum": 100, "maximum": 40000, "default": 12000},
                "max_chunks": {"type": "integer", "minimum": 1, "maximum": 50, "default": 12},
                "wiki_candidate": {"type": "boolean", "default": False},
                "graph_candidate": {"type": "boolean", "default": False},
                "evolution_capture": {"type": "boolean", "default": True},
            },
            "required": ["intent"],
            "additionalProperties": True,
        },
        capability=McpToolCapability.WRITE,
        method_name="agent_request_create",
    ),
)

_TOOL_BY_NAME: Final[dict[str, _ToolSpec]] = {tool.name: tool for tool in _TOOL_SPECS}


class _InProcessBackendClient:
    """Synchronous loopback backend adapter for in-process chat tool calls."""

    def __init__(self) -> None:
        """Create a TestClient-backed adapter only when a tool first runs."""

        self._client: Any | None = None

    @property
    def client(self) -> Any:
        """Return a lazily-created FastAPI TestClient for the current app."""

        if self._client is None:
            from fastapi.testclient import TestClient
            from python_adapter_server import app

            self._client = TestClient(app)
        return self._client

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform an in-process GET request and return a RuntimeTools envelope."""

        response = self.client.get(path, params=params)
        return self._json_response(response.status_code, response)

    def get_text(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Perform an in-process text GET request."""

        response = self.client.get(path, params=params)
        if response.status_code < 400:
            return {"is_error": False, "error_code": None, "message": None, "data": response.text}
        return {"is_error": True, "error_code": f"backend_http_{response.status_code}", "message": response.text, "data": None}

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an in-process JSON POST request."""

        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        response = self.client.post(path, json=payload, params=params)
        return self._json_response(response.status_code, response)

    def post_binary(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an in-process POST request returning binary content."""

        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        response = self.client.post(path, json=payload, params=params)
        if response.status_code < 400:
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "content": response.content,
                    "headers": dict(response.headers),
                    "status_code": response.status_code,
                },
            }
        return {"is_error": True, "error_code": f"backend_http_{response.status_code}", "message": response.text, "data": None}

    @staticmethod
    def _json_response(status_code: int, response: Any) -> dict[str, Any]:
        """Normalize a TestClient response into the RuntimeTools envelope."""

        if status_code < 400:
            try:
                data = response.json()
            except ValueError:
                data = response.text
            return {"is_error": False, "error_code": None, "message": None, "data": data}
        return {"is_error": True, "error_code": f"backend_http_{status_code}", "message": response.text, "data": None}


class _LocalToolCatalog:
    """Catalog shim used by McpToolUseRunner for built-in tools."""

    async def get_tools(
        self,
        _config: McpServerConfig,
        *,
        refresh: bool = False,
    ) -> list[McpToolDescriptor]:
        """Return the static built-in tool descriptors."""

        return local_literature_tool_descriptors()


class LocalLiteratureToolManager:
    """Execute built-in Literature Assistant tools without a stdio subprocess."""

    def __init__(
        self,
        *,
        runtime_tools: Any | None = None,
        source_tools: Any | None = None,
    ) -> None:
        """Create a local tool manager for chat-side tool-use loops.

        Args:
            runtime_tools: Optional test-injected RuntimeTools-compatible object.
            source_tools: Optional test-injected SourceTools-compatible object.
        """

        self._runtime_tools = runtime_tools
        self._source_tools = source_tools

    async def call_tool(
        self,
        config: McpServerConfig,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call one built-in tool and return MCP content blocks."""

        if config.server_id != BUILTIN_SERVER_ID:
            return self._tool_error(f"server_not_supported: {config.server_id}")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        spec = _TOOL_BY_NAME.get(tool_name)
        if spec is None:
            return self._tool_error(f"unknown_builtin_tool: {tool_name}")
        try:
            if spec.method_name == "academic_writing_lint":
                arguments = self._with_local_academic_audit_context(arguments)
            result = self._call_spec(spec, arguments)
        except Exception as exc:  # noqa: BLE001 - tool errors must stay in-band
            return self._tool_error(f"builtin_tool_failed: {type(exc).__name__}: {exc}")
        text = json.dumps(result, ensure_ascii=False, default=str)
        return {
            "is_error": bool(result.get("is_error")) if isinstance(result, dict) else False,
            "content": [{"type": "text", "text": text}],
        }

    def _call_spec(self, spec: _ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a validated tool spec to RuntimeTools or SourceTools."""

        if spec.method_name.startswith("source."):
            source_method = spec.method_name.split(".", 1)[1]
            method = getattr(self._get_source_tools(), source_method)
        else:
            method = getattr(self._get_runtime_tools(), spec.method_name)
        return method(**arguments)

    def _get_runtime_tools(self) -> Any:
        """Return the RuntimeTools instance used by local chat tools."""

        if self._runtime_tools is None:
            _ensure_agent_mcp_path()
            from lit_assistant_mcp.audit import AuditLog
            from lit_assistant_mcp.tools.runtime import RuntimeTools

            self._runtime_tools = RuntimeTools(
                backend=_InProcessBackendClient(),
                audit=AuditLog(_REPO_ROOT / "workspace_artifacts" / "agent_mcp_workflows" / ".audit"),
            )
        return self._runtime_tools

    def _with_local_academic_audit_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Mark source-launched chat writing checks as local-tool mediated."""

        normalized = dict(arguments)
        raw_context = normalized.get("audit_context")
        context = dict(raw_context) if isinstance(raw_context, dict) else {}
        context["invocation_surface"] = "api_chat_local_tools"
        context.setdefault("agent_host", "source-api-chat")
        context.setdefault("source", "api_chat")
        used_tools = context.get("used_mcp_tools")
        if not isinstance(used_tools, list):
            used_tools = []
        if "literature.academic_writing_lint" not in used_tools:
            used_tools.append("literature.academic_writing_lint")
        context["used_mcp_tools"] = used_tools
        tool_chain = context.get("tool_chain")
        if not isinstance(tool_chain, list):
            tool_chain = []
        if "academic_writing_lint" not in tool_chain:
            tool_chain.append("academic_writing_lint")
        context["tool_chain"] = tool_chain
        normalized["audit_context"] = context
        return normalized

    def _get_source_tools(self) -> Any:
        """Return the SourceTools instance used by local chat tools."""

        if self._source_tools is None:
            _ensure_agent_mcp_path()
            from lit_assistant_mcp.audit import AuditLog
            from lit_assistant_mcp.tools.source import create_default_source_tools

            self._source_tools = create_default_source_tools(
                repo_root=_REPO_ROOT,
                audit=AuditLog(_REPO_ROOT / "workspace_artifacts" / "agent_mcp_workflows" / ".audit"),
            )
        return self._source_tools

    @staticmethod
    def _tool_error(message: str) -> dict[str, Any]:
        """Return an MCP-shaped tool error block."""

        return {"is_error": True, "content": [{"type": "text", "text": message}]}


class LocalLiteratureToolDispatcher:
    """Dispatcher shim for built-in tools with the same risk policy as MCP."""

    def __init__(self, *, allow_high_risk_tools: bool, manager: LocalLiteratureToolManager | None = None) -> None:
        """Create a dispatcher for the local Literature Assistant catalog."""

        self._allow_high_risk_tools = bool(allow_high_risk_tools)
        self._manager = manager or LocalLiteratureToolManager()
        self._slug_to_id = {BUILTIN_SERVER_SLUG: BUILTIN_SERVER_ID}
        self._config = local_literature_server_config()

    async def dispatch_many(self, calls: list[DispatchInput], *, max_parallel: int) -> list[ToolResultRecord]:
        """Dispatch calls in order with the same public method as McpToolDispatcher."""

        if not isinstance(calls, list):
            raise TypeError("calls must be a list")
        return [await self.dispatch_one(call) for call in calls]

    async def dispatch_one(self, call: DispatchInput) -> ToolResultRecord:
        """Dispatch one provider tool call to the built-in tool manager."""

        started = time.perf_counter()
        try:
            ns = parse_namespaced_tool(call.namespaced_name, slug_to_server_id=self._slug_to_id)
        except ValueError as exc:
            return _error_record(call=call, reason=f"unknown_tool: {exc}", elapsed_ms=_elapsed_ms(started))
        if ns.server_id != BUILTIN_SERVER_ID:
            return _error_record(call=call, reason=f"server_not_supported: {ns.server_id}", elapsed_ms=_elapsed_ms(started))
        spec = _TOOL_BY_NAME.get(ns.tool_name)
        if spec is None:
            return _error_record(call=call, reason=f"unknown_tool_on_server: {ns.tool_name}", elapsed_ms=_elapsed_ms(started))
        if spec.capability in {McpToolCapability.WRITE, McpToolCapability.FILESYSTEM, McpToolCapability.DESTRUCTIVE, McpToolCapability.UNKNOWN}:
            if not self._allow_high_risk_tools and not call.allow_high_risk:
                return _error_record(
                    call=call,
                    server_slug=BUILTIN_SERVER_SLUG,
                    server_id=BUILTIN_SERVER_ID,
                    tool_name=ns.tool_name,
                    reason=f"capability_blocked: tool {ns.tool_name} tagged {spec.capability.value}; require allow_high_risk_tools=true",
                    elapsed_ms=_elapsed_ms(started),
                )
        raw = await self._manager.call_tool(self._config, ns.tool_name, _normalize_arguments(call.arguments))
        return build_tool_result_record(
            tool_call_id=call.tool_call_id,
            server_id=BUILTIN_SERVER_ID,
            server_slug=BUILTIN_SERVER_SLUG,
            tool_name=ns.tool_name,
            raw=raw,
            elapsed_ms=_elapsed_ms(started),
        )


class LocalLiteratureToolUseRunner:
    """McpToolUseRunner-compatible runner backed by the local dispatcher."""

    def __init__(
        self,
        *,
        provider_runner: Any,
        allow_high_risk_tools: bool,
        manager: LocalLiteratureToolManager | None = None,
    ) -> None:
        """Patch an existing provider runner with a built-in local dispatcher."""

        self._provider_runner = provider_runner
        self._provider_runner._dispatcher = LocalLiteratureToolDispatcher(
            allow_high_risk_tools=allow_high_risk_tools,
            manager=manager,
        )

    @property
    def offered_tool_count(self) -> int:
        """Return provider-facing local tool count for router diagnostics."""

        count = getattr(self._provider_runner, "offered_tool_count", 0)
        return max(0, int(count))

    async def run(
        self,
        *,
        provider: str,
        initial_messages: list[dict[str, Any]],
        chat_call: Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], Any],
    ) -> Any:
        """Run the provider tool-use loop using the built-in dispatcher."""

        return await self._provider_runner.run(
            provider=provider,
            initial_messages=initial_messages,
            chat_call=chat_call,
        )


def local_literature_server_config() -> McpServerConfig:
    """Return the synthetic built-in Literature Assistant server config."""

    now = "2026-06-18T00:00:00+00:00"
    return McpServerConfig(
        name="Literature Assistant built-in tools",
        server_slug=BUILTIN_SERVER_SLUG,
        transport=McpTransport.STDIO,
        stdio=McpStdioConfig(command="python", args=["-m", "lit_assistant_mcp.server"]),
        provenance=McpProvenance.RUNTIME_USER_CONFIRMED,
        server_id=BUILTIN_SERVER_ID,
        approval_state=McpApprovalState.ENABLED_FOR_SESSION,
        fingerprint="builtin-literature-v1",
        created_at=now,
        updated_at=now,
    )


def local_literature_tool_descriptors() -> list[McpToolDescriptor]:
    """Return MCP descriptors for built-in source and literature tools."""

    return [
        McpToolDescriptor(
            name=spec.name,
            description=spec.description,
            input_schema=dict(spec.input_schema),
            capability=spec.capability,
        )
        for spec in _TOOL_SPECS
    ]


def local_literature_catalog_snapshot() -> list[tuple[McpServerConfig, list[McpToolDescriptor]]]:
    """Return the catalog snapshot consumed by provider tool adapters."""

    return [(local_literature_server_config(), local_literature_tool_descriptors())]


def local_literature_catalog() -> _LocalToolCatalog:
    """Return a catalog shim for the built-in Literature Assistant server."""

    return _LocalToolCatalog()


def _normalize_arguments(arguments: Any) -> dict[str, Any]:
    """Normalize provider arguments into an object for tool dispatch."""

    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"raw_arguments": text}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": arguments}


def _error_record(
    *,
    call: DispatchInput,
    reason: str,
    elapsed_ms: int,
    server_id: str = BUILTIN_SERVER_ID,
    server_slug: str = BUILTIN_SERVER_SLUG,
    tool_name: str | None = None,
) -> ToolResultRecord:
    """Build an in-band tool error record."""

    return build_tool_result_record(
        tool_call_id=call.tool_call_id,
        server_id=server_id,
        server_slug=server_slug,
        tool_name=tool_name or call.namespaced_name,
        raw={"is_error": True, "content": [{"type": "text", "text": reason}]},
        elapsed_ms=elapsed_ms,
    )


def _elapsed_ms(started: float) -> int:
    """Return elapsed milliseconds since ``started``."""

    return int((time.perf_counter() - started) * 1000)


def _ensure_agent_mcp_path() -> None:
    """Expose the local MCP package implementation to source-launched chat."""

    src = str(_MCP_SRC_ROOT)
    if not _MCP_SRC_ROOT.is_dir():
        raise RuntimeError("agent_mcp_server/src is missing")
    if src not in sys.path:
        sys.path.insert(0, src)


__all__ = [
    "BUILTIN_SERVER_ID",
    "BUILTIN_SERVER_SLUG",
    "LocalLiteratureToolManager",
    "LocalLiteratureToolUseRunner",
    "local_literature_catalog",
    "local_literature_catalog_snapshot",
    "local_literature_server_config",
    "local_literature_tool_descriptors",
]

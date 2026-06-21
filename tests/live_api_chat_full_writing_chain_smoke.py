from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "literature_assistant" / "core"
MCP_SRC = ROOT / "agent_mcp_server" / "src"
for import_path in (str(CORE), str(MCP_SRC), str(ROOT)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

os.environ.setdefault("LITASSIST_DISABLE_FILE_LOG", "1")
os.environ.setdefault("LITASSIST_DISABLE_ROUTE_DUMP", "1")
os.environ.setdefault("LITASSIST_API_CAPABILITY_AUTH", "0")
os.environ["LLM_HTTP_TIMEOUT"] = "45"
os.environ["LLM_HTTP_RETRIES"] = "0"
os.environ["MCP_MAX_TOOL_ROUNDS"] = "8"
os.environ["MCP_MAX_TOTAL_TOOL_SECONDS"] = "90"
os.environ["MCP_MAX_PARALLEL_TOOLS"] = "1"
os.environ["MCP_TOOL_CALL_TIMEOUT_SECONDS"] = "20"

_REQUIRED_WRITING_TOOLS = {
    "literature.evidence_pack_build",
    "literature.agent_resource_read",
    "literature.outline_generate",
    "literature.journal_style_spec_draft",
    "literature.journal_style_spec_confirm",
    "literature.export_docx",
    "literature.academic_writing_lint",
}
_EVIDENCE_BACKFLOW_MARKERS = (
    "lack-of-fusion pores",
    "keyhole porosity",
    "near-surface crack initiation",
    "molten-pool flow",
    "critical pore populations",
)


def _mask_key(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}...{text[-4:]}"


def _artifact_path(name: str) -> Path:
    root = ROOT / "workspace_artifacts" / "generated" / "output"
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _configure_isolated_runtime() -> None:
    artifact_root = ROOT / "workspace_artifacts" / "generated" / "output" / "live_api_chat_full_writing_chain_smoke_workspace"
    artifact_root.mkdir(parents=True, exist_ok=True)
    source_root = artifact_root / "source_texts"
    source_root.mkdir(parents=True, exist_ok=True)
    (source_root / "alsi10mg-live-smoke.txt").write_text(
        (
            "AlSi10Mg porosity fatigue laser oscillation review introduction. "
            "Figure 1, Table 1 and Equation (1) are required in the final manuscript."
        ),
        encoding="utf-8",
    )
    os.environ["LITERATURE_ASSISTANT_USER_ROOT"] = str(artifact_root / "user_data")
    os.environ["LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT"] = str(artifact_root / "runtime_state")
    os.environ["LITERATURE_SOURCE_PATHS"] = str(source_root)
    os.environ["WRITING_RESOURCE_DB_PATH"] = str(artifact_root / "writing_resources_state.sqlite3")
    os.environ["WRITING_RESOURCE_STORE_PATH"] = str(artifact_root / "writing_resources_state.json")

    import project_paths  # type: ignore

    project_paths.WORKSPACE_ARTIFACTS_ROOT = Path(os.environ["LITERATURE_ASSISTANT_USER_ROOT"])
    project_paths.WORKSPACE_RUNTIME_STATE_ROOT = Path(os.environ["LITERATURE_ASSISTANT_RUNTIME_STATE_ROOT"])
    project_paths.WORKSPACE_OUTPUT_ROOT = project_paths.WORKSPACE_ARTIFACTS_ROOT / "generated" / "output"
    project_paths.WORKSPACE_GENERATED_ROOT = project_paths.WORKSPACE_ARTIFACTS_ROOT / "generated"

    import writing_resources  # type: ignore

    writing_resources._get_writing_resource_store_singleton.cache_clear()

    import routers.resources_router as resources_router  # type: ignore

    projects_root = project_paths.project_data_path("_anchor").parent
    resources_router._PROJECTS_DATA_ROOT = projects_root
    resources_router.project_data_path = project_paths.project_data_path


def _create_fixture_project(client: Any) -> str:
    import routers.resources_router as resources_router  # type: ignore

    created = client.post(
        "/resources/project",
        json={
            "title": "Live API Chat Full Writing Chain Smoke",
            "description": "Ephemeral real-provider API-chat local tool writing-chain smoke",
        },
    )
    created.raise_for_status()
    project_id = str(created.json()["project_id"])
    materials: list[dict[str, Any]] = [
        {
            "title": "LPBF AlSi10Mg defect control",
            "summary": (
                "LPBF AlSi10Mg fatigue performance is governed by lack-of-fusion pores, "
                "keyhole porosity, and near-surface crack initiation."
            ),
            "content": (
                "LPBF AlSi10Mg fatigue performance is governed by lack-of-fusion pores, "
                "keyhole porosity, and near-surface crack initiation. Figure 1 compares "
                "molten-pool flow, Table 1 summarizes processing windows, and Equation 1 "
                "defines nominal stress from force and area."
            ),
            "chunk_id": "live_full_alsi10mg_defects_chunk_0",
            "page": 4,
            "source_relative_path": "papers/alsi10mg-defects.pdf",
        },
        {
            "title": "Oscillating laser porosity suppression",
            "summary": (
                "Oscillating laser paths reduce AlSi10Mg porosity by changing molten-pool "
                "flow while preserving a controlled heat input window."
            ),
            "content": (
                "Laser oscillation redistributes molten-pool flow in AlSi10Mg and can "
                "suppress porosity when heat input remains controlled; this improves "
                "fatigue reliability by reducing critical pore populations."
            ),
            "chunk_id": "live_full_alsi10mg_oscillation_chunk_0",
            "page": 8,
            "source_relative_path": "papers/alsi10mg-oscillation.pdf",
        },
    ]
    chunk_store: dict[str, list[dict[str, Any]]] = {}
    for item in materials:
        material_response = client.post(
            "/resources/material",
            json={
                "project_id": project_id,
                "title": item["title"],
                "summary": item["summary"],
                "focus_points": ["AlSi10Mg", "porosity", "fatigue", "laser oscillation"],
            },
        )
        material_response.raise_for_status()
        material_id = str(material_response.json()["material_id"])
        chunk_store[material_id] = [
            {
                "chunk_id": item["chunk_id"],
                "material_id": material_id,
                "title": item["title"],
                "content": item["content"],
                "summary": item["summary"],
                "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                "ocr_text": "SHOULD_NOT_LEAK_OCR",
                "private_note": "SHOULD_NOT_LEAK_PRIVATE_NOTE",
                "page": item["page"],
                "chunk_type": "body",
                "source_relative_path": item["source_relative_path"],
                "locator": {
                    "material_id": material_id,
                    "chunk_id": item["chunk_id"],
                    "page": item["page"],
                    "chunk_index": 0,
                },
            }
        ]
    resources_router._save_chunk_store(project_id, chunk_store)
    return project_id


def _markers_in_text(text: str, markers: tuple[str, ...] = _EVIDENCE_BACKFLOW_MARKERS) -> list[str]:
    """Return evidence markers present in text.

    Args:
        text: Provider answer, tool preview, or bounded tool payload text.
        markers: Literal evidence phrases from the fixture chunks.

    Returns:
        Matching markers in fixture order.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(markers, tuple) or not markers:
        raise ValueError("markers must be a non-empty tuple")
    return [marker for marker in markers if marker in text]


def _verdict_for_summary(
    *,
    tool_names: list[str],
    answer_markers: list[str],
) -> str:
    """Classify the smoke without treating partial chains as success.

    Args:
        tool_names: Tool names surfaced by the chat MCP transcript.
        answer_markers: Fixture evidence phrases found in the final answer.

    Returns:
        Machine-readable verdict for process exit and audit artifacts.
    """

    if not isinstance(tool_names, list):
        raise TypeError("tool_names must be a list")
    if not isinstance(answer_markers, list):
        raise TypeError("answer_markers must be a list")
    if not tool_names:
        return "no_tool_calls"
    if not _REQUIRED_WRITING_TOOLS.issubset(set(tool_names)):
        return "partial_tool_chain"
    if not answer_markers:
        return "missing_final_evidence_backflow"
    return "ok"


def _summary_from_response(
    *,
    response: Any,
    project_id: str,
    provider_info: dict[str, str],
    prompt_mode: str,
) -> dict[str, Any]:
    """Build a bounded smoke summary with explicit evidence limits."""

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": str(response.text)[:1000]}

    summary: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "surface": "/api/chat",
        "statusCode": response.status_code,
        "projectId": project_id,
        "promptMode": prompt_mode,
        "claimBoundary": (
            "explicit_tool_sequence proves provider follows named tool instructions; "
            "autonomous_natural_task is the weaker autonomous-routing contrast."
        ),
        **provider_info,
    }
    if response.status_code != 200 or not isinstance(payload, dict):
        summary.update({"verdict": "http_error", "errorPreview": str(payload)[:1000]})
        return summary

    mcp_run = payload.get("mcp_run") if isinstance(payload.get("mcp_run"), dict) else None
    tool_calls = mcp_run.get("tool_calls") if isinstance(mcp_run, dict) else []
    if not isinstance(tool_calls, list):
        tool_calls = []
    tool_names = [str(call.get("tool_name")) for call in tool_calls if isinstance(call, dict)]
    previews = [str(call.get("preview") or "") for call in tool_calls if isinstance(call, dict)]
    preview_text = "\n".join(previews)
    answer = str(payload.get("response") or payload.get("answer") or "")
    answer_markers = _markers_in_text(answer)
    preview_markers = _markers_in_text(preview_text)
    natural_prompt_mode = prompt_mode == "autonomous_natural_task"
    explicit_tool_sequence_prompt = prompt_mode == "explicit_tool_sequence"
    all_required_tools_used = _REQUIRED_WRITING_TOOLS.issubset(set(tool_names))
    provider_selected_tool_calls = bool(tool_names)
    final_answer_evidence_backflow = bool(answer_markers)
    summary.update(
        {
            "verdict": _verdict_for_summary(
                tool_names=tool_names,
                answer_markers=answer_markers,
            ),
            "answerChars": len(answer),
            "rounds": mcp_run.get("rounds") if isinstance(mcp_run, dict) else None,
            "stoppedReason": mcp_run.get("stopped_reason") if isinstance(mcp_run, dict) else None,
            "toolNames": tool_names,
            "missingRequiredTools": sorted(_REQUIRED_WRITING_TOOLS.difference(tool_names)),
            "toolCallCount": len(tool_names),
            "contextChunksUsed": payload.get("context_chunks_used"),
            "leakDetected": "SHOULD_NOT_LEAK" in preview_text,
            "analysisChainPresent": bool(payload.get("analysis_chain")),
            "hasEvidencePack": "evidence_pack:" in preview_text,
            "hasJournalProfile": "style_profile=" in preview_text or "custom_" in preview_text,
            "hasDocxExport": "artifact_path" in preview_text and ".docx" in preview_text,
            "hasWritingAudit": "academic_connector_count" in preview_text or "mcp_tool_calls_used" in preview_text,
            "toolPreviewEvidenceMarkers": preview_markers,
            "answerEvidenceMarkers": answer_markers,
            "evidenceBackflowVerified": final_answer_evidence_backflow,
            "acceptanceCriteria": {
                "naturalPromptMode": natural_prompt_mode,
                "explicitToolSequencePrompt": explicit_tool_sequence_prompt,
                "providerSelectedToolCalls": provider_selected_tool_calls,
                "allRequiredWritingToolsUsed": all_required_tools_used,
                "boundedToolContentReachedProvider": bool(preview_markers),
                "finalAnswerEvidenceBackflow": final_answer_evidence_backflow,
                "noFixtureSecretLeak": "SHOULD_NOT_LEAK" not in preview_text,
            },
        }
    )
    return summary


def _run_tool_capability_preflight(
    *,
    client: Any,
    server_module: Any,
    provider_payload: dict[str, str],
) -> dict[str, Any]:
    """Probe provider tool capability in the same runtime as the smoke.

    Args:
        client: TestClient-like object with a `post` method.
        server_module: Imported `python_adapter_server` module exposing the
            local capability header helper.
        provider_payload: Provider/base/model/key fields resolved through the
            repository config layer.

    Returns:
        Redacted probe summary suitable for embedding in smoke artifacts.
    """

    if not isinstance(provider_payload, dict):
        raise TypeError("provider_payload must be a dictionary")
    required = {"provider", "base_url", "model", "api_key"}
    missing = sorted(required.difference(provider_payload))
    if missing:
        raise ValueError(f"provider_payload missing keys: {', '.join(missing)}")
    header_name = str(getattr(server_module, "LOCAL_API_CAPABILITY_HEADER", "") or "")
    token_factory = getattr(server_module, "get_local_api_capability_token", None)
    headers: dict[str, str] = {}
    if header_name and callable(token_factory):
        headers[header_name] = str(token_factory())
    response = client.post(
        "/api/chat/tool-capability/test",
        json=provider_payload,
        headers=headers,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": str(getattr(response, "text", ""))[:500]}
    if not isinstance(payload, dict):
        payload = {"error": str(payload)[:500]}
    capability = payload.get("capability")
    capability_status = ""
    if isinstance(capability, dict):
        capability_status = str(capability.get("status") or "")
    return {
        "statusCode": int(getattr(response, "status_code", 0) or 0),
        "ok": bool(payload.get("ok")),
        "status": str(payload.get("status") or capability_status or ""),
        "provider": str(payload.get("provider") or ""),
        "base_url_host": str(payload.get("base_url_host") or ""),
        "model": str(payload.get("model") or ""),
        "stage": str(payload.get("stage") or ""),
        "error": str(payload.get("error") or "")[:500],
        "ordinary_chat_ok": bool(payload.get("ordinary_chat_ok")),
        "forced_tool_choice_ok": bool(payload.get("forced_tool_choice_ok")),
        "capability_status": capability_status,
    }


def _write_summary(summary: dict[str, Any]) -> Path:
    """Persist the smoke summary under ignored runtime artifacts."""

    if not isinstance(summary, dict):
        raise TypeError("summary must be a dictionary")
    out = _artifact_path("live_api_chat_full_writing_chain_smoke.summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _explicit_tool_sequence_query(project_id: str) -> str:
    """Return the legacy instruction-following prompt with fixed tool order."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    return (
        "请严格按顺序调用本地文献工具完成一个短链路: "
        f"1) evidence_pack_build(project_id={project_id}, query='AlSi10Mg porosity fatigue laser oscillation', section_id='review-introduction', top_k=2); "
        "2) agent_resource_read 读取第一条 evidence_ref; "
        "3) outline_generate 生成综述和引言提纲; "
        "4) journal_style_spec_draft 使用 Journal of Additive Manufacturing Letters, APA author-year, Times New Roman 12 pt, 2.54 cm margins, figure captions below figures, table captions above tables; "
        "5) journal_style_spec_confirm; "
        "6) export_docx, 内容必须包含综述、引言、图1、表1、式（1）; "
        "7) academic_writing_lint 审计该短稿。最后只用两句中文总结工具链结果，并保留至少一个读取正文里的英文证据短语。"
    )


def _autonomous_natural_task_query(project_id: str) -> str:
    """Return a natural task prompt without enumerated tool names or order."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    return (
        "请基于当前项目里的 AlSi10Mg 本地文献，完成一个可投稿短稿准备流程: "
        "先找到与孔隙、疲劳和激光振荡相关的证据并读取必要正文，再生成综述/引言提纲，"
        "按 Journal of Additive Manufacturing Letters 的 APA author-year、Times New Roman 12 pt、"
        "2.54 cm margins、图题在下和表题在上的要求形成规范，导出包含综述、引言、图1、表1、式（1）的 DOCX，"
        "最后做一次学术写作质检。不要只描述计划，完成后用两句中文总结实际结果，并保留至少一个读取正文里的英文证据短语。"
    )


def _parse_args() -> argparse.Namespace:
    """Parse smoke controls that keep explicit and autonomous evidence separate."""

    parser = argparse.ArgumentParser(description="Run live /api/chat writing-chain smoke.")
    parser.add_argument(
        "--prompt-mode",
        choices=("explicit_tool_sequence", "autonomous_natural_task"),
        default="explicit_tool_sequence",
        help="Use a fixed tool sequence prompt or a natural task prompt.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Return exit code 0 for partial_tool_chain; default treats partial as failure.",
    )
    parser.add_argument(
        "--probe-tool-capability",
        action="store_true",
        help=(
            "Run /api/chat/tool-capability/test inside the same isolated runtime "
            "before the writing-chain request. This consumes the provider probe "
            "budget but proves the product gate path before tool dispatch."
        ),
    )
    return parser.parse_args()


def _exit_code_for_verdict(verdict: str, *, allow_partial: bool) -> int:
    """Return process status for a smoke verdict.

    Args:
        verdict: Summary verdict emitted by `_summary_from_response`.
        allow_partial: Explicit opt-in for treating partial tool chains as
            non-failing exploratory runs.
    """

    if not isinstance(verdict, str) or not verdict.strip():
        raise ValueError("verdict must be a non-empty string")
    if not isinstance(allow_partial, bool):
        raise ValueError("allow_partial must be a boolean")
    if verdict == "ok":
        return 0
    if allow_partial and verdict == "partial_tool_chain":
        return 0
    return 1


def main() -> int:
    args = _parse_args()
    from model_config_store import chat_store

    resolved_provider = str(chat_store.get_resolved_field("provider") or "")
    resolved_base_url = str(chat_store.get_resolved_field("base_url") or "")
    resolved_model = str(chat_store.get_resolved_field("model") or "")
    resolved_api_key = str(chat_store.get_resolved_field("api_key") or "")
    os.environ["CHAT_PROVIDER"] = resolved_provider
    os.environ["CHAT_BASE_URL"] = resolved_base_url
    os.environ["CHAT_MODEL"] = resolved_model
    os.environ["CHAT_API_KEY"] = resolved_api_key

    _configure_isolated_runtime()
    from fastapi.testclient import TestClient
    from literature_assistant.core import python_adapter_server as server

    client = TestClient(server.app)
    provider_info = {
        "provider": resolved_provider,
        "baseHost": resolved_base_url.split("//")[-1].split("/")[0],
        "model": resolved_model,
        "maskedKey": _mask_key(resolved_api_key),
    }
    preflight_probe: dict[str, Any] | None = None
    if args.probe_tool_capability:
        preflight_probe = _run_tool_capability_preflight(
            client=client,
            server_module=server,
            provider_payload={
                "provider": resolved_provider,
                "base_url": resolved_base_url,
                "model": resolved_model,
                "api_key": resolved_api_key,
            },
        )
        if not preflight_probe.get("ok"):
            summary = {
                "generatedAt": datetime.now().isoformat(timespec="seconds"),
                "surface": "/api/chat/tool-capability/test",
                "statusCode": preflight_probe.get("statusCode"),
                "projectId": "",
                "promptMode": str(args.prompt_mode),
                "verdict": "tool_capability_probe_failed",
                "claimBoundary": (
                    "tool capability preflight failed inside the isolated smoke runtime; "
                    "the writing-chain request was not sent."
                ),
                **provider_info,
                "preflightToolCapabilityProbe": preflight_probe,
                "allowPartialExitSuccess": bool(args.allow_partial),
            }
            _write_summary(summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1

    project_id = _create_fixture_project(client)
    query = (
        _explicit_tool_sequence_query(project_id)
        if args.prompt_mode == "explicit_tool_sequence"
        else _autonomous_natural_task_query(project_id)
    )
    response = client.post(
        "/api/chat",
        json={
            "query": query,
            "tier": "fast",
            "project_id": project_id,
            "direct_mode": True,
            "mode": "direct",
            "use_local_literature_tools": True,
            "mcp_allow_high_risk_tools": True,
        },
    )
    summary = _summary_from_response(
        response=response,
        project_id=project_id,
        provider_info=provider_info,
        prompt_mode=str(args.prompt_mode),
    )
    summary["preflightToolCapabilityProbe"] = preflight_probe
    summary["allowPartialExitSuccess"] = bool(args.allow_partial)
    _write_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return _exit_code_for_verdict(str(summary["verdict"]), allow_partial=bool(args.allow_partial))


if __name__ == "__main__":
    raise SystemExit(main())

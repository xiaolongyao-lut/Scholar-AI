# -*- coding: utf-8 -*-
"""API acceptance tests for built-in Literature Assistant tool-use loops."""

from __future__ import annotations

import json
import copy
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import routers.chat_router as chat_router
from routers import intelligent_chat_router
import routers.resources_router as resources_router
from literature_assistant.core.python_adapter_server import app
from routers.local_literature_tool_bridge import LocalLiteratureToolManager
from mcp_runtime.provider_tool_adapter import PROVIDER_TOOL_NAME_RE
from provider_capabilities import (
    CAPABILITY_STATUS_AUTH_REQUIRED,
    CAPABILITY_STATUS_PROBE_FAILED,
    CAPABILITY_STATUS_TOOL_CALL_OK,
    CAPABILITY_STATUS_UNSUPPORTED,
    ProviderCapabilityStore,
)


_TOOL_NAME_SEARCH_REFS = "mcp__literature__literature.search_refs"
_TOOL_NAME_EVIDENCE_PACK = "mcp__literature__literature.evidence_pack_build"
_TOOL_NAME_AGENT_RESOURCE_READ = "mcp__literature__literature.agent_resource_read"
_TOOL_NAME_KNOWLEDGE_CONTEXT_RECEIPT = "mcp__literature__literature.knowledge_context_receipt"
_TOOL_NAME_OUTLINE_GENERATE = "mcp__literature__literature.outline_generate"
_TOOL_NAME_EXPORT_DOCX = "mcp__literature__literature.export_docx"
_TOOL_NAME_ACADEMIC_LINT = "mcp__literature__literature.academic_writing_lint"
_TOOL_NAME_JOURNAL_STYLE_DRAFT = "mcp__literature__literature.journal_style_spec_draft"
_TOOL_NAME_JOURNAL_STYLE_CONFIRM = "mcp__literature__literature.journal_style_spec_confirm"
_FIXTURE_EVIDENCE_MARKERS = (
    "lack-of-fusion pores",
    "keyhole porosity",
    "near-surface crack initiation",
    "molten-pool flow",
)


def _create_project_fixture(client: TestClient) -> tuple[str, list[str]]:
    """Create project-scoped AlSi10Mg chunks for API tool-use assertions.

    Returns:
        Project id and material ids whose stores contain searchable chunks.
    """

    created = client.post(
        "/resources/project",
        json={
            "title": "API Chat Local Literature Tool Loop",
            "description": "Fixture for provider-driven local tool calls",
        },
    )
    assert created.status_code == 200
    project_id = str(created.json()["project_id"])
    material_specs = [
        {
            "title": "LPBF AlSi10Mg defect control",
            "summary": (
                "LPBF AlSi10Mg fatigue performance is governed by lack-of-fusion "
                "pores, keyhole porosity, and near-surface crack initiation."
            ),
            "focus_points": ["LPBF defects", "fatigue crack initiation", "AlSi10Mg"],
            "chunk_id": "alsi10mg_defects_chunk_0",
            "page": 4,
            "source_relative_path": "papers/alsi10mg-defects.pdf",
            "content": (
                "LPBF AlSi10Mg fatigue performance is governed by lack-of-fusion "
                "pores, keyhole porosity, and near-surface crack initiation."
            ),
        },
        {
            "title": "Oscillating laser porosity suppression",
            "summary": (
                "Oscillating laser paths reduce AlSi10Mg porosity by changing "
                "molten-pool flow while preserving a controlled heat input window."
            ),
            "focus_points": ["laser oscillation", "porosity suppression", "molten-pool flow"],
            "chunk_id": "alsi10mg_oscillation_chunk_0",
            "page": 8,
            "source_relative_path": "papers/alsi10mg-oscillation.pdf",
            "content": (
                "Laser oscillation redistributes molten-pool flow in AlSi10Mg and "
                "can suppress porosity when heat input remains controlled."
            ),
        },
    ]
    material_ids: list[str] = []
    chunk_store: dict[str, list[dict[str, Any]]] = {}
    for spec in material_specs:
        material_response = client.post(
            "/resources/material",
            json={
                "project_id": project_id,
                "title": spec["title"],
                "summary": spec["summary"],
                "focus_points": spec["focus_points"],
            },
        )
        assert material_response.status_code == 200
        material_id = str(material_response.json()["material_id"])
        material_ids.append(material_id)
        chunk_store[material_id] = [
            {
                "chunk_id": spec["chunk_id"],
                "material_id": material_id,
                "title": spec["title"],
                "content": spec["content"],
                "summary": spec["summary"],
                "abstract": "SHOULD_NOT_LEAK_ABSTRACT",
                "ocr_text": "SHOULD_NOT_LEAK_OCR",
                "page": spec["page"],
                "chunk_type": "body",
                "source_relative_path": spec["source_relative_path"],
                "locator": {
                    "material_id": material_id,
                    "chunk_id": spec["chunk_id"],
                    "page": spec["page"],
                    "chunk_index": 0,
                },
            }
        ]
    resources_router._save_chunk_store(  # type: ignore[attr-defined]
        project_id,
        chunk_store,
    )
    return project_id, material_ids


def _tool_call_response(
    *,
    call_id: str,
    function_name: str,
    arguments: dict[str, Any],
    model: str = "tool-loop-model",
) -> dict[str, Any]:
    """Return an OpenAI-compatible provider response containing one tool call."""

    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
    }


def _final_response(answer: str, *, model: str = "tool-loop-model") -> dict[str, Any]:
    """Return a final OpenAI-compatible assistant response."""

    return {
        "id": "chatcmpl-final",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": answer},
            }
        ],
        "usage": {"prompt_tokens": 23, "completion_tokens": 17, "total_tokens": 40},
    }


def _tool_names(payload: dict[str, Any]) -> set[str]:
    """Return provider-exposed function names from an OpenAI-compatible payload."""

    raw_tools = payload.get("tools")
    if not isinstance(raw_tools, list):
        return set()
    names: set[str] = set()
    for tool in raw_tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.add(function["name"])
    return names


def _provider_tool_name(payload: dict[str, Any], internal_name: str) -> str:
    """Return the provider alias that corresponds to an internal tool name."""

    expected_prefix = re.sub(r"[^A-Za-z0-9_-]", "_", internal_name).strip("_")
    for name in _tool_names(payload):
        if name == internal_name:
            return name
        if not PROVIDER_TOOL_NAME_RE.match(name):
            continue
        prefix, _, digest = name.rpartition("_")
        if prefix and prefix == expected_prefix[: len(prefix)] and len(digest) == 8:
            return name
    raise AssertionError(f"provider payload missing tool alias for {internal_name}")


def _assert_provider_tool_aliases(payload: dict[str, Any]) -> None:
    """Validate provider-facing tool names before a fake provider uses them."""

    names = _tool_names(payload)
    assert names, "provider payload must expose tools"
    assert all(PROVIDER_TOOL_NAME_RE.match(name) for name in names)
    assert all("." not in name for name in names)


def _tool_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool result messages from a provider payload."""

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        return []
    return [
        message
        for message in raw_messages
        if isinstance(message, dict) and message.get("role") == "tool"
    ]


def _fake_post_chat_with_retry_factory(
    captured_payloads: list[dict[str, Any]],
    responses: list[dict[str, Any] | Any],
) -> Any:
    """Build a deterministic replacement for provider HTTP calls."""

    async def _fake_post_chat_with_retry(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        telemetry_model: str,
        started_at: float,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        captured_payloads.append(copy.deepcopy(payload))
        assert url.startswith("https://chat.example")
        assert headers.get("Authorization") == "Bearer test-key"
        assert telemetry_model
        assert started_at >= 0
        assert responses, "provider response queue exhausted"
        next_response = responses.pop(0)
        if callable(next_response):
            generated = next_response(payload)
            if not isinstance(generated, dict):
                raise TypeError("generated provider response must be a dictionary")
            return generated
        return next_response

    return _fake_post_chat_with_retry


def _latest_tool_json(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse the latest tool result message as a JSON object."""

    tool_messages = _tool_messages(payload)
    if not tool_messages:
        raise AssertionError("provider payload must contain at least one tool message")
    raw_content = tool_messages[-1].get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise AssertionError("tool message content must be non-empty JSON text")
    parsed = json.loads(raw_content)
    if not isinstance(parsed, dict):
        raise AssertionError("tool message content must decode to an object")
    return parsed


def _latest_tool_text(payload: dict[str, Any]) -> str:
    """Return the latest tool result text visible to the provider."""

    tool_messages = _tool_messages(payload)
    if not tool_messages:
        raise AssertionError("provider payload must contain at least one tool message")
    raw_content = tool_messages[-1].get("content")
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise AssertionError("tool message content must be non-empty text")
    return raw_content


def _first_fixture_evidence_marker(text: str) -> str:
    """Return the first fixture evidence phrase present in provider-visible text.

    Args:
        text: Provider-visible tool payload or final answer text.

    Returns:
        The first fixture evidence phrase in stable priority order.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    for marker in _FIXTURE_EVIDENCE_MARKERS:
        if marker in text:
            return marker
    raise AssertionError("provider-visible text must include fixture evidence")


def _assert_initial_prompt_does_not_script_tool_sequence(payload: dict[str, Any]) -> None:
    """Assert the user prompt did not enumerate internal tool names."""

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise AssertionError("provider payload must include messages")
    prompt_text = "\n".join(
        str(message.get("content") or "")
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user"
    )
    for forbidden in (
        "search_refs",
        "evidence_pack_build",
        "agent_resource_read",
        "knowledge_context_receipt",
        "outline_generate",
        "journal_style_spec_draft",
        "journal_style_spec_confirm",
        "export_docx",
        "academic_writing_lint",
    ):
        assert forbidden not in prompt_text


def _fake_writing_chain_post_chat_factory(
    *,
    captured_payloads: list[dict[str, Any]],
    project_id: str,
    material_ids: list[str],
    draft_html: str,
    lint_text: str,
) -> Any:
    """Build a deterministic provider that consumes prior tool results."""

    state: dict[str, str | int] = {"turn_index": 0}

    async def _fake_post_chat_with_retry(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        telemetry_model: str,
        started_at: float,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dictionary")
        captured_payloads.append(copy.deepcopy(payload))
        assert url.startswith("https://chat.example")
        assert headers.get("Authorization") == "Bearer test-key"
        assert telemetry_model
        assert started_at >= 0
        turn_index = int(state["turn_index"]) + 1
        state["turn_index"] = turn_index
        if turn_index == 1:
            _assert_provider_tool_aliases(payload)
            return _tool_call_response(
                call_id="call_evidence_pack",
                function_name=_provider_tool_name(payload, _TOOL_NAME_EVIDENCE_PACK),
                arguments={
                    "project_id": project_id,
                    "query": "AlSi10Mg porosity fatigue laser oscillation",
                    "section_id": "review-introduction",
                    "top_k": 5,
                },
            )
        if turn_index == 2:
            match = re.search(r'"ref_id":\s*"(chunk:[^"]+)"', _latest_tool_text(payload))
            ref_id = match.group(1) if match else ""
            if not ref_id:
                raise AssertionError("first evidence ref must include ref_id")
            state["first_ref_id"] = ref_id
            return _tool_call_response(
                call_id="call_agent_resource_read",
                function_name=_provider_tool_name(payload, _TOOL_NAME_AGENT_RESOURCE_READ),
                arguments={"ref_id": ref_id, "project_id": project_id, "max_chars": 900},
            )
        if turn_index == 3:
            state["evidence_marker"] = _first_fixture_evidence_marker(
                _latest_tool_text(payload)
            )
            return _tool_call_response(
                call_id="call_outline_generate",
                function_name=_provider_tool_name(payload, _TOOL_NAME_OUTLINE_GENERATE),
                arguments={
                    "project_id": project_id,
                    "topic": "AlSi10Mg 增材制造孔隙调控与疲劳性能综述",
                    "content_type": "academic",
                    "target_length": 6000,
                    "focus_areas": ["孔隙形成机制", "振荡激光调控", "疲劳裂纹萌生"],
                    "existing_materials": material_ids,
                },
            )
        if turn_index == 4:
            return _tool_call_response(
                call_id="call_journal_style_draft",
                function_name=_provider_tool_name(payload, _TOOL_NAME_JOURNAL_STYLE_DRAFT),
                arguments={
                    "project_id": project_id,
                    "journal_name": "Journal of Additive Manufacturing Letters",
                    "spec_text": (
                        "Use APA author-year citations, Times New Roman 12 pt body text, "
                        "2.54 cm margins on all sides, figure captions below figures, and table captions above tables."
                    ),
                },
            )
        if turn_index == 5:
            result = _latest_tool_json(payload)
            draft_id = str(result.get("data", {}).get("draft_id") or "")
            if not draft_id:
                raise AssertionError("journal_style_spec_draft must return draft_id")
            return _tool_call_response(
                call_id="call_journal_style_confirm",
                function_name=_provider_tool_name(payload, _TOOL_NAME_JOURNAL_STYLE_CONFIRM),
                arguments={
                    "project_id": project_id,
                    "draft_id": draft_id,
                    "confirmed_by": "api-chat-test",
                },
            )
        if turn_index == 6:
            result = _latest_tool_json(payload)
            profile_id = str(result.get("data", {}).get("profile", {}).get("profile_id") or "")
            if not profile_id:
                raise AssertionError("journal_style_spec_confirm must return profile.profile_id")
            state["profile_id"] = profile_id
            return _tool_call_response(
                call_id="call_export_docx",
                function_name=_provider_tool_name(payload, _TOOL_NAME_EXPORT_DOCX),
                arguments={
                    "html": draft_html,
                    "title": "AlSi10Mg API Chat Review Introduction",
                    "style_profile": profile_id,
                    "project_id": project_id,
                    "verify_with_word": True,
                },
            )
        if turn_index == 7:
            profile_id = str(state.get("profile_id") or "")
            if not profile_id:
                raise AssertionError("confirmed style profile must be available before lint")
            return _tool_call_response(
                call_id="call_academic_lint",
                function_name=_provider_tool_name(payload, _TOOL_NAME_ACADEMIC_LINT),
                arguments={
                    "text": lint_text.replace("chunk:pending", str(state.get("first_ref_id") or "chunk:pending")),
                    "content_type": "manuscript",
                    "language": "zh",
                    "required_sections": ["综述", "引言"],
                    "require_evidence_refs": True,
                    "require_figure_table_formula_refs": True,
                    "style_profile": profile_id,
                    "audit_context": {
                        "project_id": project_id,
                        "tool_chain": [
                            "evidence_pack_build",
                            "agent_resource_read",
                            "outline_generate",
                            "journal_style_spec_draft",
                            "journal_style_spec_confirm",
                            "export_docx",
                            "academic_writing_lint",
                        ],
                        "used_mcp_tools": [
                            "literature.evidence_pack_build",
                            "literature.agent_resource_read",
                            "literature.outline_generate",
                            "literature.journal_style_spec_draft",
                            "literature.journal_style_spec_confirm",
                            "literature.export_docx",
                            "literature.academic_writing_lint",
                        ],
                    },
                },
            )
        marker = str(state.get("evidence_marker") or "")
        if not marker:
            raise AssertionError("final answer requires evidence marker from agent_resource_read payload")
        return _final_response(
            f"已用本地文献工具完成综述/引言链路：证据包、可回读 chunk、提纲、期刊规范、DOCX 导出与写作审计均已完成；最终回答使用正文证据 {marker}。"
        )

    return _fake_post_chat_with_retry


def _configure_test_llm(monkeypatch: Any) -> None:
    """Configure the chat router for an OpenAI-compatible mocked provider."""

    class _EnvOnlyChatStore:
        """Runtime config stub that lets explicit test env/requests win."""

        def get_resolved_field(self, _name: str) -> str | None:
            return None

    monkeypatch.setenv("CHAT_PROVIDER", "OpenAI")
    monkeypatch.setenv("CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("CHAT_MODEL", "tool-loop-model")
    monkeypatch.setenv("OPENAI_API_KEY_CHAT", "test-key")
    monkeypatch.setattr(chat_router, "chat_store", _EnvOnlyChatStore())
    monkeypatch.setattr(intelligent_chat_router, "chat_store", _EnvOnlyChatStore())
    monkeypatch.setattr(intelligent_chat_router, "_ragworkflow_chat_enabled", lambda: False)
    monkeypatch.setattr(intelligent_chat_router, "_hybrid_retrieval_enabled", lambda: False)
    monkeypatch.setattr(chat_router, "_maybe_build_analysis_chain", _disabled_chat_analysis_chain)
    monkeypatch.setattr(intelligent_chat_router, "_maybe_build_chat_analysis_chain", _disabled_chat_analysis_chain)
    store_path = Path(tempfile.mkdtemp(prefix="scholar-ai-provider-capability-test-")) / "provider-capabilities.json"
    store = ProviderCapabilityStore(path=store_path)
    store.upsert_record(
        provider="OpenAI",
        base_url="https://chat.example/v1",
        model="tool-loop-model",
        status=CAPABILITY_STATUS_TOOL_CALL_OK,
        ordinary_chat_ok=True,
        forced_tool_choice_ok=True,
    )
    monkeypatch.setattr(chat_router.provider_capabilities, "provider_capability_store", store)


async def _disabled_chat_analysis_chain(**_kwargs: Any) -> None:
    """Disable optional trace generation so tests measure only tool-loop calls."""

    return None


def _llm_payload() -> dict[str, Any]:
    """Return an explicit LLM payload that bypasses persisted runtime config."""

    return {
        "provider": "OpenAI",
        "api_key": "test-key",
        "model": "tool-loop-model",
        "base_url": "https://chat.example/v1",
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 40,
        "max_tokens": 512,
        "system_prompt": "",
    }


def _assert_tool_result_payload_contains_ref(payload: dict[str, Any], chunk_id: str) -> None:
    """Assert the second provider payload carries a real tool result."""

    messages = payload.get("messages")
    assert isinstance(messages, list)
    tool_messages = [message for message in messages if message.get("role") == "tool"]
    assert tool_messages, "tool result messages must be sent back to the provider"
    content = str(tool_messages[0].get("content") or "")
    assert chunk_id in content
    assert "SHOULD_NOT_LEAK" not in content
    assert "/api/agent-bridge/resource/chunk:" in content


def test_chat_ask_local_literature_tool_loop_executes_search_refs(
    monkeypatch: Any,
) -> None:
    """Provider tool calls should invoke built-in Literature tools in `/chat/ask`."""

    client = TestClient(app)
    project_id, _material_ids = _create_project_fixture(client)
    captured_payloads: list[dict[str, Any]] = []
    responses = [
        lambda payload: _tool_call_response(
            call_id="call_search_refs",
            function_name=_provider_tool_name(payload, _TOOL_NAME_SEARCH_REFS),
            arguments={
                "project_id": project_id,
                "query": "AlSi10Mg porosity fatigue laser oscillation",
                "top_k": 5,
            },
        ),
        _final_response(
            "综述显示，AlSi10Mg 的孔隙控制与疲劳裂纹萌生密切相关；因此，引言应围绕证据锚点展开。"
        ),
    ]
    _configure_test_llm(monkeypatch)
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_post_chat_with_retry_factory(captured_payloads, responses),
    )

    response = client.post(
        "/chat/ask",
        json={
            "query": "写一段 AlSi10Mg 孔隙与疲劳的中文综述引言。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "AlSi10Mg" in payload["answer"]
    assert payload["mcp_run"]["rounds"] == 2
    assert payload["mcp_run"]["diagnostics"]["terminal_state"] == "completed"
    assert payload["mcp_run"]["diagnostics"]["stop_reason"] == "tool_loop_completed"
    assert payload["mcp_run"]["diagnostics"]["legacy_stopped_reason"] == "natural"
    assert payload["mcp_run"]["diagnostics"]["tool_call_count"] == 1
    tool_calls = payload["mcp_run"]["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["server_id"] == "builtin_literature_assistant"
    assert tool_calls[0]["server_slug"] == "literature"
    assert tool_calls[0]["tool_name"] == "literature.search_refs"
    assert tool_calls[0]["is_error"] is False
    assert tool_calls[0]["budget_class"] == "refs"
    assert tool_calls[0]["llm_payload_chars"] > 0
    assert tool_calls[0]["estimated_tokens"] > 0
    assert tool_calls[0]["source_provenance"]["tool_name"] == "literature.search_refs"
    assert "alsi10mg_defects_chunk_0" in tool_calls[0]["preview"]
    assert "SHOULD_NOT_LEAK" not in tool_calls[0]["preview"]
    assert len(captured_payloads) == 2
    first_payload = captured_payloads[0]
    _assert_provider_tool_aliases(first_payload)
    assert _provider_tool_name(first_payload, _TOOL_NAME_SEARCH_REFS) in _tool_names(first_payload)
    _assert_tool_result_payload_contains_ref(captured_payloads[1], "alsi10mg_defects_chunk_0")


def test_chat_ask_local_literature_tool_loop_requires_proven_provider_tools(
    monkeypatch: Any,
) -> None:
    """Ordinary chat success must not be treated as native tool-call support."""

    captured_payloads: list[dict[str, Any]] = []
    _configure_test_llm(monkeypatch)
    empty_path = Path(tempfile.mkdtemp(prefix="scholar-ai-provider-capability-empty-")) / "provider-capabilities.json"
    empty_store = ProviderCapabilityStore(path=empty_path)
    monkeypatch.setattr(chat_router.provider_capabilities, "provider_capability_store", empty_store)
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_post_chat_with_retry_factory(captured_payloads, [_final_response("plain chat")]),
    )

    response = TestClient(app).post(
        "/chat/ask",
        json={
            "query": "写一段 AlSi10Mg 孔隙与疲劳的中文综述引言。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == ""
    assert payload["mcp_run"]["diagnostics"]["terminal_state"] == "failed"
    assert payload["mcp_run"]["diagnostics"]["stop_reason"] == "provider_tool_probe_failed"
    assert payload["mcp_run"]["diagnostics"]["legacy_stopped_reason"] == "provider_tool_probe_failed"
    assert payload["mcp_run"]["tool_calls"] == []
    assert captured_payloads == []


def test_chat_ask_local_literature_tool_loop_blocks_failed_probe_statuses(
    monkeypatch: Any,
) -> None:
    """Persisted non-success probe statuses must fail closed before provider calls."""

    for status in (
        CAPABILITY_STATUS_PROBE_FAILED,
        CAPABILITY_STATUS_AUTH_REQUIRED,
        CAPABILITY_STATUS_UNSUPPORTED,
    ):
        captured_payloads: list[dict[str, Any]] = []
        _configure_test_llm(monkeypatch)
        store_path = (
            Path(tempfile.mkdtemp(prefix=f"scholar-ai-provider-capability-{status}-"))
            / "provider-capabilities.json"
        )
        store = ProviderCapabilityStore(path=store_path)
        store.upsert_record(
            provider="OpenAI",
            base_url="https://chat.example/v1",
            model="tool-loop-model",
            status=status,
            ordinary_chat_ok=status == CAPABILITY_STATUS_PROBE_FAILED,
            forced_tool_choice_ok=False,
            failure_class=status,
            masked_error=f"{status} fixture",
        )
        monkeypatch.setattr(chat_router.provider_capabilities, "provider_capability_store", store)
        monkeypatch.setattr(
            chat_router,
            "_post_chat_with_retry",
            _fake_post_chat_with_retry_factory(captured_payloads, [_final_response("plain chat")]),
        )

        response = TestClient(app).post(
            "/chat/ask",
            json={
                "query": "写一段 AlSi10Mg 孔隙与疲劳的中文综述引言。",
                "context": [],
                "llm": _llm_payload(),
                "use_local_literature_tools": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        diagnostics = payload["mcp_run"]["diagnostics"]
        assert payload["answer"] == ""
        assert diagnostics["terminal_state"] == "failed"
        assert diagnostics["stop_reason"] == "provider_tool_probe_failed"
        assert diagnostics["legacy_stopped_reason"] == "provider_tool_probe_failed"
        assert diagnostics["events"][0]["metadata"]["capability_status"] == status
        assert payload["mcp_run"]["tool_calls"] == []
        assert captured_payloads == []


def test_chat_ask_local_literature_tool_loop_blocks_write_tools_by_default(
    monkeypatch: Any,
) -> None:
    """Write-class built-in tools must not execute unless the request opts in."""

    captured_payloads: list[dict[str, Any]] = []
    responses = [
        lambda payload: _tool_call_response(
            call_id="call_export_docx",
            function_name=_provider_tool_name(payload, _TOOL_NAME_EXPORT_DOCX),
            arguments={
                "html": "<h1>Review</h1><p>Evidence-grounded text.</p>",
                "title": "Blocked Export",
            },
        ),
        _final_response("导出工具未执行；请先由用户确认高风险工具。"),
    ]
    _configure_test_llm(monkeypatch)
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_post_chat_with_retry_factory(captured_payloads, responses),
    )

    response = TestClient(app).post(
        "/chat/ask",
        json={
            "query": "导出这份综述为 DOCX。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
            "mcp_allow_high_risk_tools": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    tool_call = payload["mcp_run"]["tool_calls"][0]
    assert tool_call["tool_name"] == "literature.export_docx"
    assert tool_call["is_error"] is True
    assert "user_rejected" in tool_call["preview"]
    assert "Blocked Export" not in tool_call["preview"]
    assert len(captured_payloads) == 2
    assert "user_rejected" in str(captured_payloads[1]["messages"])


def test_chat_ask_local_literature_tool_loop_executes_academic_lint(
    monkeypatch: Any,
) -> None:
    """Local chat tools should expose deterministic scholarly writing lint."""

    captured_payloads: list[dict[str, Any]] = []
    draft = (
        "# 引言\n"
        "AlSi10Mg 激光增材制造研究表明，孔隙形貌与疲劳裂纹萌生存在关联[chunk:c1]。"
        "因此，引言需要围绕缺陷形成机制与性能退化路径展开。"
    )
    responses = [
        lambda payload: _tool_call_response(
            call_id="call_academic_lint",
            function_name=_provider_tool_name(payload, _TOOL_NAME_ACADEMIC_LINT),
            arguments={
                "text": draft,
                "content_type": "introduction",
                "language": "zh",
                "required_sections": ["引言"],
                "require_evidence_refs": True,
            },
        ),
        _final_response("质检通过：该引言具备证据锚点、章节结构和基本科研论证语体。"),
    ]
    _configure_test_llm(monkeypatch)
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_post_chat_with_retry_factory(captured_payloads, responses),
    )

    response = TestClient(app).post(
        "/chat/ask",
        json={
            "query": "检查这段 AlSi10Mg 引言是否符合科研写作。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    tool_call = payload["mcp_run"]["tool_calls"][0]
    assert tool_call["tool_name"] == "literature.academic_writing_lint"
    assert tool_call["is_error"] is False
    assert '"passed": true' in tool_call["preview"].lower()
    assert '"invocation_surface": "api_chat_local_tools"' in tool_call["preview"]
    assert '"agent_mediated": true' in tool_call["preview"].lower()
    assert '"mcp_tool_calls_used": true' in tool_call["preview"].lower()
    assert '"disclosure_required": true' in tool_call["preview"].lower()
    assert len(captured_payloads) == 2
    _assert_provider_tool_aliases(captured_payloads[0])
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_ACADEMIC_LINT) in _tool_names(captured_payloads[0])
    assert "academic_connector_count" in str(captured_payloads[1]["messages"])


def test_chat_ask_local_literature_tool_result_returns_body_beyond_preview(
    monkeypatch: Any,
) -> None:
    """Provider-visible tool messages should carry bounded body text, not preview."""

    sentinel = "A1_PROVIDER_VISIBLE_RESOURCE_BODY_71c6d9"
    long_content = ("x" * 1800) + sentinel
    captured_payloads: list[dict[str, Any]] = []

    class _SentinelRuntimeTools:
        def agent_resource_read(
            self,
            ref_id: str,
            project_id: str | None = None,
            max_chars: int = 6000,
            cursor: str | None = None,
        ) -> dict[str, Any]:
            assert ref_id == "chunk:sentinel"
            assert project_id == "project-1"
            assert max_chars == 3000
            assert cursor is None
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "ref_id": ref_id,
                    "kind": "chunk",
                    "project_id": project_id,
                    "content": long_content,
                    "truncated": False,
                },
            }

    async def _fake_post_chat_with_retry(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        telemetry_model: str,
        started_at: float,
    ) -> dict[str, Any]:
        captured_payloads.append(copy.deepcopy(payload))
        assert url.startswith("https://chat.example")
        assert headers.get("Authorization") == "Bearer test-key"
        assert telemetry_model
        assert started_at >= 0
        if len(captured_payloads) == 1:
            _assert_provider_tool_aliases(payload)
            return _tool_call_response(
                call_id="call_agent_resource_read",
                function_name=_provider_tool_name(payload, _TOOL_NAME_AGENT_RESOURCE_READ),
                arguments={
                    "ref_id": "chunk:sentinel",
                    "project_id": "project-1",
                    "max_chars": 3000,
                },
            )
        provider_visible = _latest_tool_text(payload)
        assert sentinel in provider_visible
        return _final_response("已读取 sentinel 正文。")

    _configure_test_llm(monkeypatch)
    monkeypatch.setattr(chat_router, "_post_chat_with_retry", _fake_post_chat_with_retry)
    monkeypatch.setattr(
        chat_router.chat_mcp_integration,
        "make_local_literature_runner",
        lambda *, allow_high_risk_tools, caps=None: chat_router.chat_mcp_integration.LocalLiteratureToolUseRunner(
            provider_runner=chat_router.chat_mcp_integration.McpToolUseRunner(
                manager=chat_router.chat_mcp_integration.get_mcp_client_manager(),
                catalog=chat_router.chat_mcp_integration.local_literature_catalog(),
                servers=[chat_router.chat_mcp_integration.local_literature_server_config()],
                catalog_snapshot=chat_router.chat_mcp_integration.local_literature_catalog_snapshot(),
                caps=caps,
                allow_high_risk_tools=allow_high_risk_tools,
            ),
            allow_high_risk_tools=allow_high_risk_tools,
            manager=LocalLiteratureToolManager(
                runtime_tools=_SentinelRuntimeTools(),
            ),
        ),
    )

    response = TestClient(app).post(
        "/chat/ask",
        json={
            "query": "读取 sentinel chunk 正文。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "已读取 sentinel 正文。"
    assert len(captured_payloads) == 2
    tool_call = payload["mcp_run"]["tool_calls"][0]
    assert tool_call["tool_name"] == "literature.agent_resource_read"
    assert tool_call["truncated"] is True
    assert tool_call["budget_class"] == "body"
    assert tool_call["llm_payload_chars"] > 0
    assert tool_call["estimated_tokens"] > 0
    assert tool_call["source_provenance"]["ref_id"] == "chunk:sentinel"
    assert tool_call["source_provenance"]["project_id"] == "project-1"
    assert sentinel not in tool_call["preview"]
    assert sentinel in _latest_tool_text(captured_payloads[1])


def test_chat_ask_local_literature_tools_context_receipt_enters_provider_context(
    monkeypatch: Any,
) -> None:
    """Chat tool loops should return Knowledge Runtime context receipts to the provider."""

    marker = "Context receipt anchor proves bounded knowledge entered the provider-visible prompt."
    captured_payloads: list[dict[str, Any]] = []

    class _ReceiptRuntimeTools:
        def agent_resource_read(
            self,
            ref_id: str,
            project_id: str | None = None,
            max_chars: int = 6000,
            cursor: str | None = None,
        ) -> dict[str, Any]:
            assert ref_id == "product_docs:chunk:readme"
            assert project_id is None
            assert max_chars == 900
            assert cursor is None
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "ref_id": ref_id,
                    "kind": "product_docs",
                    "title": "README",
                    "content": marker,
                    "metadata": {
                        "knowledge_ref_schema_version": "scholar-ai-product-docs-knowledge-ref/v1",
                        "source_path": "README.md",
                        "source_hash": "a" * 64,
                        "package_content_hash": "b" * 64,
                    },
                    "truncated": False,
                    "max_chars": max_chars,
                    "total_chars": len(marker),
                },
            }

        def knowledge_context_receipt(
            self,
            ref_ids: list[str],
            project_id: str | None = None,
            prompt_name: str = "knowledge_runtime_context",
            max_chars_per_ref: int = 1200,
        ) -> dict[str, Any]:
            assert ref_ids == ["product_docs:chunk:readme"]
            assert project_id is None
            assert prompt_name == "api_chat_context_receipt_probe"
            assert max_chars_per_ref == 900
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "schema_version": "scholar-ai-knowledge-context-receipt/v1",
                    "prompt_name": prompt_name,
                    "prompt_hash": "c" * 64,
                    "assembled_context_hash": "d" * 64,
                    "assembled_context_char_count": len(marker),
                    "assembled_context_preview": marker,
                    "resource_read_receipts": [
                        {
                            "ref_id": "product_docs:chunk:readme",
                            "kind": "product_docs",
                            "read_endpoint": "/api/agent-bridge/resource/product_docs:chunk:readme",
                            "content_hash": "e" * 64,
                            "source_hash": "a" * 64,
                            "package_content_hash": "b" * 64,
                            "source_path": "README.md",
                            "returned_chars": len(marker),
                            "total_chars": len(marker),
                            "max_chars": max_chars_per_ref,
                            "truncated": False,
                            "metadata": {
                                "knowledge_ref_schema_version": "scholar-ai-product-docs-knowledge-ref/v1",
                            },
                        }
                    ],
                    "provenance": {
                        "mcp_tool": "literature.knowledge_context_receipt",
                        "resource_reader": "literature_assistant.core.routers.agent_bridge_router",
                        "hash_algorithm": "sha256",
                    },
                },
            }

    async def _fake_post_chat_with_retry(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        telemetry_model: str,
        started_at: float,
    ) -> dict[str, Any]:
        captured_payloads.append(copy.deepcopy(payload))
        assert url.startswith("https://chat.example")
        assert headers.get("Authorization") == "Bearer test-key"
        assert telemetry_model
        assert started_at >= 0
        if len(captured_payloads) == 1:
            _assert_provider_tool_aliases(payload)
            return _tool_call_response(
                call_id="call_agent_resource_read",
                function_name=_provider_tool_name(payload, _TOOL_NAME_AGENT_RESOURCE_READ),
                arguments={
                    "ref_id": "product_docs:chunk:readme",
                    "max_chars": 900,
                },
            )
        if len(captured_payloads) == 2:
            assert marker in _latest_tool_text(payload)
            return _tool_call_response(
                call_id="call_context_receipt",
                function_name=_provider_tool_name(payload, _TOOL_NAME_KNOWLEDGE_CONTEXT_RECEIPT),
                arguments={
                    "ref_ids": ["product_docs:chunk:readme"],
                    "prompt_name": "api_chat_context_receipt_probe",
                    "max_chars_per_ref": 900,
                },
            )
        receipt_text = _latest_tool_text(payload)
        assert "scholar-ai-knowledge-context-receipt/v1" in receipt_text
        assert "assembled_context_hash" in receipt_text
        assert "resource_read_receipts" in receipt_text
        assert marker in receipt_text
        return _final_response("已生成可复验的知识上下文 receipt。")

    _configure_test_llm(monkeypatch)
    monkeypatch.setattr(chat_router, "_post_chat_with_retry", _fake_post_chat_with_retry)
    monkeypatch.setattr(
        chat_router.chat_mcp_integration,
        "make_local_literature_runner",
        lambda *, allow_high_risk_tools, caps=None: chat_router.chat_mcp_integration.LocalLiteratureToolUseRunner(
            provider_runner=chat_router.chat_mcp_integration.McpToolUseRunner(
                manager=chat_router.chat_mcp_integration.get_mcp_client_manager(),
                catalog=chat_router.chat_mcp_integration.local_literature_catalog(),
                servers=[chat_router.chat_mcp_integration.local_literature_server_config()],
                catalog_snapshot=chat_router.chat_mcp_integration.local_literature_catalog_snapshot(),
                caps=caps,
                allow_high_risk_tools=allow_high_risk_tools,
            ),
            allow_high_risk_tools=allow_high_risk_tools,
            manager=LocalLiteratureToolManager(
                runtime_tools=_ReceiptRuntimeTools(),
            ),
        ),
    )

    response = TestClient(app).post(
        "/chat/ask",
        json={
            "query": "读取产品文档知识 ref，并生成可复验的 context receipt。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "已生成可复验的知识上下文 receipt。"
    assert len(captured_payloads) == 3
    first_tool_names = _tool_names(captured_payloads[0])
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_AGENT_RESOURCE_READ) in first_tool_names
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_KNOWLEDGE_CONTEXT_RECEIPT) in first_tool_names
    tool_calls = payload["mcp_run"]["tool_calls"]
    assert [call["tool_name"] for call in tool_calls] == [
        "literature.agent_resource_read",
        "literature.knowledge_context_receipt",
    ]
    assert all(call["is_error"] is False for call in tool_calls)
    assert tool_calls[1]["source_provenance"]["tool_name"] == "literature.knowledge_context_receipt"
    assert "assembled_context_hash" in _latest_tool_text(captured_payloads[2])
    assert "resource_read_receipts" in _latest_tool_text(captured_payloads[2])
    assert marker in _latest_tool_text(captured_payloads[2])


def test_chat_ask_local_literature_tools_execute_full_writing_chain_when_allowed(
    monkeypatch: Any,
) -> None:
    """Local chat tools should run the evidence-to-style-to-export writing chain."""

    client = TestClient(app)
    project_id, material_ids = _create_project_fixture(client)
    captured_payloads: list[dict[str, Any]] = []
    draft_html = (
        "<h1>综述</h1>"
        "<p>证据包 evidence_pack:pending 表明，AlSi10Mg 孔隙、熔池流动与疲劳裂纹萌生存在证据链"
        "[chunk:pending]。</p>"
        "<h1>引言</h1>"
        "<p>如图 1、表 1 和式（1）所示，振荡激光通过改变熔池流动抑制孔隙，并影响疲劳可靠性"
        "[chunk:pending]。</p>"
        "<figcaption>图 1 熔池扰动与孔隙演化示意图</figcaption>"
        "<table><tr><th>参数</th><th>趋势</th></tr><tr><td>扫描速度</td><td>孔隙率变化</td></tr></table>"
        "<figcaption>表 1 AlSi10Mg 工艺参数对比</figcaption>"
        "<p>式（1）：<span data-formula=\"P = F / A\" data-equation-number=\"1\"></span></p>"
    )
    lint_text = (
        "# 综述\n"
        "证据包 evidence_pack:pending 表明，AlSi10Mg 孔隙、熔池流动与疲劳裂纹萌生存在证据链[chunk:pending]。"
        "\n\n# 引言\n"
        "如图 1、表 1 和式（1）所示，振荡激光通过改变熔池流动抑制孔隙，并影响疲劳可靠性[chunk:pending]。"
    )
    _configure_test_llm(monkeypatch)
    monkeypatch.setenv("MCP_MAX_TOOL_ROUNDS", "8")
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_writing_chain_post_chat_factory(
            captured_payloads=captured_payloads,
            project_id=project_id,
            material_ids=material_ids,
            draft_html=draft_html,
            lint_text=lint_text,
        ),
    )

    response = client.post(
        "/chat/ask",
        json={
            "query": "从本地 AlSi10Mg 文献证据生成综述和引言，确认期刊规范，导出 DOCX，并做写作审计。",
            "context": [],
            "llm": _llm_payload(),
            "use_local_literature_tools": True,
            "mcp_allow_high_risk_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "综述/引言" in payload["answer"]
    answer_marker = _first_fixture_evidence_marker(payload["answer"])
    assert payload["mcp_run"]["rounds"] == 8
    assert payload["mcp_run"]["stopped_reason"] == "natural"
    tool_calls = payload["mcp_run"]["tool_calls"]
    expected_tool_names = [
        "literature.evidence_pack_build",
        "literature.agent_resource_read",
        "literature.outline_generate",
        "literature.journal_style_spec_draft",
        "literature.journal_style_spec_confirm",
        "literature.export_docx",
        "literature.academic_writing_lint",
    ]
    assert [call["tool_name"] for call in tool_calls] == expected_tool_names
    assert all(call["server_id"] == "builtin_literature_assistant" for call in tool_calls)
    assert all(call["server_slug"] == "literature" for call in tool_calls)
    assert all(call["is_error"] is False for call in tool_calls)
    previews = "\n".join(str(call["preview"]) for call in tool_calls)
    assert "evidence_pack:" in previews
    assert "/api/agent-bridge/resource/chunk:" in previews
    assert "alsi10mg_defects_chunk_0" in previews
    assert "retrieval_method" in previews
    assert "requires_confirmation" in previews
    assert "style_profile=custom_journal_of_additive_manufacturing_letters_" in previews
    assert "citation_style=author_year" in previews
    assert "word_verify=requested_unavailable" in previews
    assert '"invocation_surface": "api_chat_local_tools"' in previews
    assert '"agent_mediated": true' in previews.lower()
    assert '"mcp_tool_calls_used": true' in previews.lower()
    assert '"disclosure_required": true' in previews.lower()
    assert "SHOULD_NOT_LEAK" not in previews
    assert len(captured_payloads) == 8
    first_tool_names = _tool_names(captured_payloads[0])
    _assert_provider_tool_aliases(captured_payloads[0])
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_EVIDENCE_PACK) in first_tool_names
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_EXPORT_DOCX) in first_tool_names
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_JOURNAL_STYLE_CONFIRM) in first_tool_names
    _assert_initial_prompt_does_not_script_tool_sequence(captured_payloads[0])
    for index, expected_call_id in enumerate(
        [
            "call_evidence_pack",
            "call_agent_resource_read",
            "call_outline_generate",
            "call_journal_style_draft",
            "call_journal_style_confirm",
            "call_export_docx",
            "call_academic_lint",
        ],
        start=1,
    ):
        tool_messages = _tool_messages(captured_payloads[index])
        assert tool_messages, f"provider payload {index} must carry a tool result"
        assert expected_call_id in {str(message.get("tool_call_id") or "") for message in tool_messages}
    export_messages = [
        message
        for message in _tool_messages(captured_payloads[6])
        if message.get("tool_call_id") == "call_export_docx"
    ]
    lint_messages = [
        message
        for message in _tool_messages(captured_payloads[7])
        if message.get("tool_call_id") == "call_academic_lint"
    ]
    assert answer_marker in _latest_tool_text(captured_payloads[2])
    assert export_messages and "artifact_path" in str(export_messages[-1]["content"])
    assert lint_messages and "academic_connector_count" in str(lint_messages[-1]["content"])


def test_api_chat_local_literature_tools_run_through_smart_read(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """SmartRead `/api/chat` should use the same guarded local tool path."""

    client = TestClient(app)
    project_id, _material_ids = _create_project_fixture(client)
    source = tmp_path / "paper.txt"
    source.write_text(
        "请写 AlSi10Mg 孔隙 疲劳 综述 引言。Porosity and fatigue reliability depend on laser oscillation.",
        encoding="utf-8",
    )
    captured_payloads: list[dict[str, Any]] = []
    responses = [
        lambda payload: _tool_call_response(
            call_id="call_smart_read_search_refs",
            function_name=_provider_tool_name(payload, _TOOL_NAME_SEARCH_REFS),
            arguments={
                "project_id": project_id,
                "query": "AlSi10Mg porosity fatigue laser oscillation",
                "top_k": 5,
            },
        ),
        _final_response(
            "基于本地文献工具检索，AlSi10Mg 孔隙调控综述应先说明缺陷类型，再讨论疲劳裂纹萌生。"
        ),
    ]
    _configure_test_llm(monkeypatch)
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_post_chat_with_retry_factory(captured_payloads, responses),
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "请写 AlSi10Mg 孔隙与疲劳的综述引言",
            "tier": "fast",
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "AlSi10Mg" in payload["response"]
    assert payload["context_chunks_used"] >= 1
    assert len(captured_payloads) == 2
    _assert_provider_tool_aliases(captured_payloads[0])
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_SEARCH_REFS) in _tool_names(captured_payloads[0])
    _assert_tool_result_payload_contains_ref(captured_payloads[1], "alsi10mg_defects_chunk_0")


def test_api_chat_local_literature_tools_context_receipt_enters_provider_context(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """SmartRead `/api/chat` should carry context receipt tool output into provider context."""

    client = TestClient(app)
    source = tmp_path / "paper.txt"
    source.write_text(
        "Context receipt anchor proves bounded knowledge entered SmartRead provider context.",
        encoding="utf-8",
    )
    marker = "SmartRead context receipt anchor proves bounded knowledge entered the provider-visible prompt."
    captured_payloads: list[dict[str, Any]] = []

    class _SmartReadReceiptRuntimeTools:
        def agent_resource_read(
            self,
            ref_id: str,
            project_id: str | None = None,
            max_chars: int = 6000,
            cursor: str | None = None,
        ) -> dict[str, Any]:
            assert ref_id == "product_docs:chunk:readme"
            assert project_id is None
            assert max_chars == 850
            assert cursor is None
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "ref_id": ref_id,
                    "kind": "product_docs",
                    "title": "README",
                    "content": marker,
                    "metadata": {
                        "knowledge_ref_schema_version": "scholar-ai-product-docs-knowledge-ref/v1",
                        "source_path": "README.md",
                        "source_hash": "a" * 64,
                        "package_content_hash": "b" * 64,
                    },
                    "truncated": False,
                    "max_chars": max_chars,
                    "total_chars": len(marker),
                },
            }

        def knowledge_context_receipt(
            self,
            ref_ids: list[str],
            project_id: str | None = None,
            prompt_name: str = "knowledge_runtime_context",
            max_chars_per_ref: int = 1200,
        ) -> dict[str, Any]:
            assert ref_ids == ["product_docs:chunk:readme"]
            assert project_id is None
            assert prompt_name == "smart_read_context_receipt_probe"
            assert max_chars_per_ref == 850
            return {
                "is_error": False,
                "error_code": None,
                "message": None,
                "data": {
                    "schema_version": "scholar-ai-knowledge-context-receipt/v1",
                    "prompt_name": prompt_name,
                    "prompt_hash": "c" * 64,
                    "assembled_context_hash": "d" * 64,
                    "assembled_context_char_count": len(marker),
                    "assembled_context_preview": marker,
                    "resource_read_receipts": [
                        {
                            "ref_id": "product_docs:chunk:readme",
                            "kind": "product_docs",
                            "read_endpoint": "/api/agent-bridge/resource/product_docs:chunk:readme",
                            "content_hash": "e" * 64,
                            "source_hash": "a" * 64,
                            "package_content_hash": "b" * 64,
                            "source_path": "README.md",
                            "returned_chars": len(marker),
                            "total_chars": len(marker),
                            "max_chars": max_chars_per_ref,
                            "truncated": False,
                            "metadata": {
                                "knowledge_ref_schema_version": "scholar-ai-product-docs-knowledge-ref/v1",
                            },
                        }
                    ],
                    "provenance": {
                        "mcp_tool": "literature.knowledge_context_receipt",
                        "resource_reader": "literature_assistant.core.routers.agent_bridge_router",
                        "hash_algorithm": "sha256",
                    },
                },
            }

    async def _fake_post_chat_with_retry(
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        telemetry_model: str,
        started_at: float,
    ) -> dict[str, Any]:
        captured_payloads.append(copy.deepcopy(payload))
        assert url.startswith("https://chat.example")
        assert headers.get("Authorization") == "Bearer test-key"
        assert telemetry_model
        assert started_at >= 0
        if len(captured_payloads) == 1:
            _assert_provider_tool_aliases(payload)
            return _tool_call_response(
                call_id="call_agent_resource_read",
                function_name=_provider_tool_name(payload, _TOOL_NAME_AGENT_RESOURCE_READ),
                arguments={
                    "ref_id": "product_docs:chunk:readme",
                    "max_chars": 850,
                },
            )
        if len(captured_payloads) == 2:
            assert marker in _latest_tool_text(payload)
            return _tool_call_response(
                call_id="call_context_receipt",
                function_name=_provider_tool_name(payload, _TOOL_NAME_KNOWLEDGE_CONTEXT_RECEIPT),
                arguments={
                    "ref_ids": ["product_docs:chunk:readme"],
                    "prompt_name": "smart_read_context_receipt_probe",
                    "max_chars_per_ref": 850,
                },
            )
        receipt_text = _latest_tool_text(payload)
        assert "scholar-ai-knowledge-context-receipt/v1" in receipt_text
        assert "assembled_context_hash" in receipt_text
        assert "resource_read_receipts" in receipt_text
        assert marker in receipt_text
        return _final_response("SmartRead 已生成可复验的知识上下文 receipt。")

    _configure_test_llm(monkeypatch)
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setattr(chat_router, "_post_chat_with_retry", _fake_post_chat_with_retry)
    monkeypatch.setattr(
        chat_router.chat_mcp_integration,
        "make_local_literature_runner",
        lambda *, allow_high_risk_tools, caps=None: chat_router.chat_mcp_integration.LocalLiteratureToolUseRunner(
            provider_runner=chat_router.chat_mcp_integration.McpToolUseRunner(
                manager=chat_router.chat_mcp_integration.get_mcp_client_manager(),
                catalog=chat_router.chat_mcp_integration.local_literature_catalog(),
                servers=[chat_router.chat_mcp_integration.local_literature_server_config()],
                catalog_snapshot=chat_router.chat_mcp_integration.local_literature_catalog_snapshot(),
                caps=caps,
                allow_high_risk_tools=allow_high_risk_tools,
            ),
            allow_high_risk_tools=allow_high_risk_tools,
            manager=LocalLiteratureToolManager(
                runtime_tools=_SmartReadReceiptRuntimeTools(),
            ),
        ),
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "读取产品文档知识 ref，并生成 SmartRead context receipt。",
            "tier": "fast",
            "use_local_literature_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response"] == "SmartRead 已生成可复验的知识上下文 receipt。"
    assert payload["context_chunks_used"] >= 1
    assert len(captured_payloads) == 3
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_AGENT_RESOURCE_READ) in _tool_names(captured_payloads[0])
    assert _provider_tool_name(captured_payloads[0], _TOOL_NAME_KNOWLEDGE_CONTEXT_RECEIPT) in _tool_names(captured_payloads[0])
    tool_calls = payload["mcp_run"]["tool_calls"]
    assert [call["tool_name"] for call in tool_calls] == [
        "literature.agent_resource_read",
        "literature.knowledge_context_receipt",
    ]
    assert all(call["is_error"] is False for call in tool_calls)
    assert tool_calls[1]["source_provenance"]["tool_name"] == "literature.knowledge_context_receipt"
    assert "assembled_context_hash" in _latest_tool_text(captured_payloads[2])
    assert "resource_read_receipts" in _latest_tool_text(captured_payloads[2])
    assert marker in _latest_tool_text(captured_payloads[2])


def test_api_chat_local_literature_tools_surface_full_writing_chain_transcript(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """SmartRead `/api/chat` should surface the guarded MCP/local tool transcript."""

    client = TestClient(app)
    project_id, material_ids = _create_project_fixture(client)
    source = tmp_path / "paper.txt"
    source.write_text(
        "AlSi10Mg porosity fatigue reliability laser oscillation review introduction.",
        encoding="utf-8",
    )
    captured_payloads: list[dict[str, Any]] = []
    draft_html = (
        "<h1>综述</h1>"
        "<p>证据包 evidence_pack:pending 表明，AlSi10Mg 孔隙、熔池流动与疲劳裂纹萌生存在证据链"
        "[chunk:pending]。</p>"
        "<h1>引言</h1>"
        "<p>振荡激光通过改变熔池流动抑制孔隙，并影响疲劳可靠性[chunk:pending]。</p>"
    )
    lint_text = (
        "# 综述\n"
        "证据包 evidence_pack:pending 表明，AlSi10Mg 孔隙、熔池流动与疲劳裂纹萌生存在证据链[chunk:pending]。"
        "\n\n# 引言\n"
        "振荡激光通过改变熔池流动抑制孔隙，并影响疲劳可靠性[chunk:pending]。"
    )
    _configure_test_llm(monkeypatch)
    monkeypatch.setenv("LITERATURE_SOURCE_PATHS", str(tmp_path))
    monkeypatch.setenv("MCP_MAX_TOOL_ROUNDS", "8")
    monkeypatch.setattr(
        chat_router,
        "_post_chat_with_retry",
        _fake_writing_chain_post_chat_factory(
            captured_payloads=captured_payloads,
            project_id=project_id,
            material_ids=material_ids,
            draft_html=draft_html,
            lint_text=lint_text,
        ),
    )

    response = client.post(
        "/api/chat",
        json={
            "query": "从本地 AlSi10Mg 文献证据生成综述和引言，确认期刊规范，导出 DOCX，并做写作审计。",
            "tier": "fast",
            "use_local_literature_tools": True,
            "mcp_allow_high_risk_tools": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "综述/引言" in payload["response"]
    answer_marker = _first_fixture_evidence_marker(payload["response"])
    assert payload["mcp_run"]["rounds"] == 8
    assert payload["mcp_run"]["stopped_reason"] == "natural"
    tool_calls = payload["mcp_run"]["tool_calls"]
    assert [call["tool_name"] for call in tool_calls] == [
        "literature.evidence_pack_build",
        "literature.agent_resource_read",
        "literature.outline_generate",
        "literature.journal_style_spec_draft",
        "literature.journal_style_spec_confirm",
        "literature.export_docx",
        "literature.academic_writing_lint",
    ]
    assert all(call["server_id"] == "builtin_literature_assistant" for call in tool_calls)
    assert all(call["server_slug"] == "literature" for call in tool_calls)
    assert all(call["is_error"] is False for call in tool_calls)
    previews = "\n".join(str(call["preview"]) for call in tool_calls)
    assert "evidence_pack:" in previews
    assert "/api/agent-bridge/resource/chunk:" in previews
    assert "alsi10mg_defects_chunk_0" in previews
    assert "style_profile=custom_journal_of_additive_manufacturing_letters_" in previews
    assert "word_verify=requested_unavailable" in previews
    assert '"invocation_surface": "api_chat_local_tools"' in previews
    assert '"agent_mediated": true' in previews.lower()
    assert '"mcp_tool_calls_used": true' in previews.lower()
    assert '"disclosure_required": true' in previews.lower()
    assert "SHOULD_NOT_LEAK" not in previews
    assert len(captured_payloads) == 8
    _assert_initial_prompt_does_not_script_tool_sequence(captured_payloads[0])
    for index, expected_call_id in enumerate(
        [
            "call_evidence_pack",
            "call_agent_resource_read",
            "call_outline_generate",
            "call_journal_style_draft",
            "call_journal_style_confirm",
            "call_export_docx",
            "call_academic_lint",
        ],
        start=1,
    ):
        tool_messages = _tool_messages(captured_payloads[index])
        assert tool_messages, f"provider payload {index} must carry a tool result"
        assert expected_call_id in {str(message.get("tool_call_id") or "") for message in tool_messages}
    assert answer_marker in _latest_tool_text(captured_payloads[2])

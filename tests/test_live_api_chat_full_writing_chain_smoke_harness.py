"""Regression tests for the live API-chat full writing-chain smoke harness."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


_ROOT = Path(__file__).resolve().parents[1]
_HARNESS_PATH = _ROOT / "tests" / "live_api_chat_full_writing_chain_smoke.py"


def _load_harness() -> ModuleType:
    """Load the harness as a module without running its `main` function."""

    spec = importlib.util.spec_from_file_location("live_api_chat_full_writing_chain_smoke", _HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness: {_HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harness_prompt_modes_separate_explicit_and_autonomous_claims() -> None:
    harness = _load_harness()
    explicit = harness._explicit_tool_sequence_query("project-1")  # type: ignore[attr-defined]
    autonomous = harness._autonomous_natural_task_query("project-1")  # type: ignore[attr-defined]

    assert "1) evidence_pack_build" in explicit
    assert "2) agent_resource_read" in explicit
    assert "evidence_pack_build" not in autonomous
    assert "agent_resource_read" not in autonomous
    assert "1)" not in autonomous
    assert "不要只描述计划" in autonomous


def test_harness_partial_tool_chain_is_not_success_by_default() -> None:
    harness = _load_harness()

    assert harness._exit_code_for_verdict("ok", allow_partial=False) == 0  # type: ignore[attr-defined]
    assert harness._exit_code_for_verdict("partial_tool_chain", allow_partial=False) == 1  # type: ignore[attr-defined]
    assert harness._exit_code_for_verdict("partial_tool_chain", allow_partial=True) == 0  # type: ignore[attr-defined]
    assert harness._exit_code_for_verdict("no_tool_calls", allow_partial=True) == 1  # type: ignore[attr-defined]


def test_harness_requires_final_answer_evidence_backflow_for_success() -> None:
    harness = _load_harness()
    tool_names: list[str] = sorted(harness._REQUIRED_WRITING_TOOLS)  # type: ignore[attr-defined]

    assert (
        harness._verdict_for_summary(  # type: ignore[attr-defined]
            tool_names=tool_names,
            answer_markers=[],
        )
        == "missing_final_evidence_backflow"
    )
    assert (
        harness._verdict_for_summary(  # type: ignore[attr-defined]
            tool_names=tool_names,
            answer_markers=["lack-of-fusion pores"],
        )
        == "ok"
    )


def test_harness_natural_prompt_summary_exposes_acceptance_contract() -> None:
    harness = _load_harness()
    tool_calls: list[dict[str, Any]] = [
        {"tool_name": name, "preview": "evidence_pack:abc lack-of-fusion pores"}
        for name in sorted(harness._REQUIRED_WRITING_TOOLS)  # type: ignore[attr-defined]
    ]

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "response": "最终答案使用了 lack-of-fusion pores。",
                "mcp_run": {
                    "rounds": 8,
                    "stopped_reason": "natural",
                    "tool_calls": tool_calls,
                },
            }

    summary = harness._summary_from_response(  # type: ignore[attr-defined]
        response=_Response(),
        project_id="project-1",
        provider_info={"provider": "OpenAI", "baseHost": "chat.example", "model": "m", "maskedKey": "****"},
        prompt_mode="autonomous_natural_task",
    )

    assert summary["acceptanceCriteria"]["naturalPromptMode"] is True
    assert summary["acceptanceCriteria"]["explicitToolSequencePrompt"] is False
    assert summary["acceptanceCriteria"]["providerSelectedToolCalls"] is True
    assert summary["acceptanceCriteria"]["finalAnswerEvidenceBackflow"] is True
    assert summary["acceptanceCriteria"]["allRequiredWritingToolsUsed"] is True


def test_harness_summary_reports_answer_evidence_backflow() -> None:
    harness = _load_harness()
    tool_calls: list[dict[str, Any]] = [
        {"tool_name": name, "preview": "evidence_pack:abc lack-of-fusion pores"}
        for name in sorted(harness._REQUIRED_WRITING_TOOLS)  # type: ignore[attr-defined]
    ]

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "response": "最终答案使用了 lack-of-fusion pores 作为正文证据。",
                "mcp_run": {
                    "rounds": 8,
                    "stopped_reason": "natural",
                    "tool_calls": tool_calls,
                },
            }

    summary = harness._summary_from_response(  # type: ignore[attr-defined]
        response=_Response(),
        project_id="project-1",
        provider_info={"provider": "OpenAI", "baseHost": "chat.example", "model": "m", "maskedKey": "****"},
        prompt_mode="autonomous_natural_task",
    )

    assert summary["verdict"] == "ok"
    assert summary["evidenceBackflowVerified"] is True
    assert "lack-of-fusion pores" in summary["answerEvidenceMarkers"]


def test_harness_tool_capability_preflight_uses_local_capability_header() -> None:
    harness = _load_harness()
    captured: dict[str, Any] = {}

    class _Server:
        LOCAL_API_CAPABILITY_HEADER = "X-Local-Capability"

        @staticmethod
        def get_local_api_capability_token() -> str:
            return "test-token"

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "ok": True,
                "status": "tool_call_ok",
                "provider": "OpenAI",
                "base_url_host": "chat.example",
                "model": "m",
                "stage": "forced_tool_choice",
                "ordinary_chat_ok": True,
                "forced_tool_choice_ok": True,
                "capability": {"status": "tool_call_ok"},
            }

    class _Client:
        def post(
            self,
            path: str,
            *,
            json: dict[str, str],
            headers: dict[str, str],
        ) -> _Response:
            captured["path"] = path
            captured["json"] = json
            captured["headers"] = headers
            return _Response()

    summary = harness._run_tool_capability_preflight(  # type: ignore[attr-defined]
        client=_Client(),
        server_module=_Server(),
        provider_payload={
            "provider": "OpenAI",
            "base_url": "https://chat.example/v1",
            "model": "m",
            "api_key": "secret",
        },
    )

    assert captured["path"] == "/api/chat/tool-capability/test"
    assert captured["headers"] == {"X-Local-Capability": "test-token"}
    assert summary["ok"] is True
    assert summary["status"] == "tool_call_ok"
    assert summary["forced_tool_choice_ok"] is True


def test_evolution_secret_scan_import_survives_direct_script_test_path_shadowing() -> None:
    """Protect live-smoke imports when `tests/` is first on `sys.path`."""

    tests_path = str(_ROOT / "tests")
    original_path = list(sys.path)
    module_names = (
        "wiki",
        "wiki.evaluation",
        "literature_assistant.core.evolution.secret_scan",
    )
    original_modules = {name: sys.modules.get(name) for name in module_names}
    try:
        for name in module_names:
            sys.modules.pop(name, None)
        sys.path[:] = [tests_path, *[path for path in original_path if path != tests_path]]
        spec = importlib.util.find_spec("wiki")
        if spec is None or spec.origin is None:
            raise AssertionError("expected tests/wiki to be importable")
        assert Path(spec.origin).resolve() == (_ROOT / "tests" / "wiki" / "__init__.py").resolve()

        module = importlib.import_module("literature_assistant.core.evolution.secret_scan")

        assert tuple(module.fields_to_scan()) == ("title", "claim", "future_use", "source_summary")
    finally:
        sys.path[:] = original_path
        for name in module_names:
            sys.modules.pop(name, None)
            original = original_modules[name]
            if original is not None:
                sys.modules[name] = original

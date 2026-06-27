"""Regression tests for the live Knowledge Runtime context-receipt smoke."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


_ROOT = Path(__file__).resolve().parents[1]
_HARNESS_PATH = _ROOT / "tests" / "live_api_chat_knowledge_context_receipt_smoke.py"


def _load_harness() -> ModuleType:
    """Load the harness module without running its live `main` function."""

    spec = importlib.util.spec_from_file_location("live_api_chat_knowledge_context_receipt_smoke", _HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness: {_HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _direct_receipt(hash_value: str) -> dict[str, Any]:
    """Return a minimal direct receipt payload for harness assertions."""

    return {
        "schema_version": "scholar-ai-knowledge-context-receipt/v1",
        "prompt_hash": "a" * 64,
        "assembled_context_hash": hash_value,
        "assembled_context_char_count": 321,
        "resource_read_receipts": [{"ref_id": "product_docs:chunk:readme"}],
    }


def test_live_query_requires_exact_context_hash_backflow() -> None:
    harness = _load_harness()
    digest = "b" * 64

    query = harness._live_query(  # type: ignore[attr-defined]
        ref_id="product_docs:chunk:readme",
        prompt_name="smart_read_context_receipt_probe",
        max_chars_per_ref=850,
        expected_hash=digest,
    )

    assert "literature.agent_resource_read" in query
    assert "literature.knowledge_context_receipt" in query
    assert f"CONTEXT_RECEIPT_HASH={digest}" in query
    assert "不要改写、截断或解释这个 hash" in query


def test_main_requires_explicit_live_provider_authorization(monkeypatch: Any) -> None:
    harness = _load_harness()
    summaries: list[dict[str, Any]] = []

    monkeypatch.delenv("LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE", raising=False)
    monkeypatch.setattr(sys, "argv", ["live_api_chat_knowledge_context_receipt_smoke.py"])
    monkeypatch.setattr(
        harness,
        "_provider_info",
        lambda: (_ for _ in ()).throw(AssertionError("credentials must not be read")),
    )
    monkeypatch.setattr(harness, "_write_summary", lambda summary: summaries.append(summary))

    exit_code = harness.main()  # type: ignore[attr-defined]

    assert exit_code == 2
    assert len(summaries) == 1
    assert summaries[0]["verdict"] == "skipped_not_authorized"
    assert summaries[0]["requiredAuthorization"]["environmentVariable"] == (
        "LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE"
    )
    assert summaries[0]["requiredAuthorization"]["cliFlag"] == "--allow-live-provider-call"
    assert "not model-context proof" in summaries[0]["claimBoundary"]


def test_live_provider_authorization_accepts_flag_or_env(monkeypatch: Any) -> None:
    harness = _load_harness()

    monkeypatch.delenv("LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE", raising=False)
    monkeypatch.setattr(sys, "argv", ["live_api_chat_knowledge_context_receipt_smoke.py"])
    args = harness._parse_args()  # type: ignore[attr-defined]
    assert harness._live_smoke_authorized(args) is False  # type: ignore[attr-defined]

    monkeypatch.setattr(
        sys,
        "argv",
        ["live_api_chat_knowledge_context_receipt_smoke.py", "--allow-live-provider-call"],
    )
    flag_args = harness._parse_args()  # type: ignore[attr-defined]
    assert harness._live_smoke_authorized(flag_args) is True  # type: ignore[attr-defined]

    monkeypatch.setattr(sys, "argv", ["live_api_chat_knowledge_context_receipt_smoke.py"])
    monkeypatch.setenv("LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE", "true")
    env_args = harness._parse_args()  # type: ignore[attr-defined]
    assert harness._live_smoke_authorized(env_args) is True  # type: ignore[attr-defined]


def test_summary_requires_tool_preview_and_final_answer_hash() -> None:
    harness = _load_harness()
    digest = "c" * 64

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "response": f"CONTEXT_RECEIPT_HASH={digest}",
                "mcp_run": {
                    "tool_calls": [
                        {
                            "tool_name": "literature.agent_resource_read",
                            "preview": "Product docs bounded content",
                        },
                        {
                            "tool_name": "literature.knowledge_context_receipt",
                            "preview": (
                                "scholar-ai-knowledge-context-receipt/v1 "
                                f"assembled_context_hash={digest} resource_read_receipts=[]"
                            ),
                        },
                    ]
                },
            }

    summary = harness._summary_from_chat_response(  # type: ignore[attr-defined]
        response=_Response(),
        provider_info={"provider": "OpenAI", "baseHost": "chat.example", "model": "m", "maskedKey": "****"},
        ref_info={"refId": "product_docs:chunk:readme", "readEndpoint": "/api/agent-bridge/resource/product_docs:chunk:readme"},
        direct_receipt=_direct_receipt(digest),
        prompt_name="smart_read_context_receipt_probe",
        query_hash=digest,
    )

    assert summary["verdict"] == "ok"
    assert summary["chatEvidence"]["usedRequiredTools"] is True
    assert summary["chatEvidence"]["receiptHashVisibleInToolPreview"] is True
    assert summary["chatEvidence"]["finalAnswerIncludesReceiptHash"] is True


def test_summary_rejects_preview_without_final_answer_hash() -> None:
    harness = _load_harness()
    digest = "d" * 64

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "response": "Receipt completed without repeating the digest.",
                "mcp_run": {
                    "tool_calls": [
                        {"tool_name": "literature.agent_resource_read", "preview": "bounded content"},
                        {
                            "tool_name": "literature.knowledge_context_receipt",
                            "preview": f"scholar-ai-knowledge-context-receipt/v1 assembled_context_hash={digest}",
                        },
                    ]
                },
            }

    summary = harness._summary_from_chat_response(  # type: ignore[attr-defined]
        response=_Response(),
        provider_info={"provider": "OpenAI", "baseHost": "chat.example", "model": "m", "maskedKey": "****"},
        ref_info={"refId": "product_docs:chunk:readme"},
        direct_receipt=_direct_receipt(digest),
        prompt_name="smart_read_context_receipt_probe",
        query_hash=digest,
    )

    assert summary["verdict"] == "missing_final_hash_backflow"
    assert summary["chatEvidence"]["receiptHashVisibleInToolPreview"] is True
    assert summary["chatEvidence"]["finalAnswerIncludesReceiptHash"] is False


def test_mask_key_never_returns_full_secret() -> None:
    harness = _load_harness()

    assert harness._mask_key("") == ""  # type: ignore[attr-defined]
    assert harness._mask_key("short") == "****"  # type: ignore[attr-defined]
    assert harness._mask_key("sk-" + "abcdefghijklmnopqrstuvwxyz") == "sk-a...wxyz"  # type: ignore[attr-defined]

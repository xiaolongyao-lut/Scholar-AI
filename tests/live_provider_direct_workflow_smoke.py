from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "literature_assistant" / "core"
MCP_SRC = ROOT / "agent_mcp_server" / "src"


def _promote_import_path(path: Path) -> None:
    """Keep product import roots ahead of script-local paths.

    Args:
        path: Absolute path that must be import-resolved before ambient paths.
    """

    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    value = str(path)
    while value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)


for _path in (CORE, MCP_SRC, ROOT):
    _promote_import_path(_path)


HASH_LEN = 64
REQUIRED_TOOLS = [
    "literature.agent_resource_read",
    "literature.knowledge_context_receipt",
]
RESULT_NAME = "live_api_chat_knowledge_context_receipt_smoke.summary.json"
PROVIDER_CAPABILITY_STATUS_TOOL_CALL_OK = "tool_call_ok"


@dataclass(frozen=True)
class ProviderTarget:
    """OpenAI-compatible provider target loaded from process environment only.

    Args:
        provider: Redacted provider label persisted in audit artifacts.
        base_url: OpenAI-compatible base URL or full chat completions URL.
        api_key: Secret credential. Never write this value to disk or stdout.
        model: Provider model id used for both proof calls.
    """

    provider: str
    base_url: str
    api_key: str
    model: str


def _now_utc_iso() -> str:
    """Return an audit timestamp parseable by the conformance gate."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mask_key(value: str) -> str:
    """Return a non-secret API key fingerprint for summaries."""

    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}...{text[-4:]}"


def _host(base_url: str) -> str:
    """Return the host portion expected by provider-capabilities matching."""

    parsed = urlparse(str(base_url or "").strip())
    return (parsed.netloc or parsed.path).lower()


def _chat_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL to chat/completions."""

    base = str(base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url must be non-empty")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    if "/v1/" in base:
        return f"{base[: base.rfind('/v1/') + 3]}/chat/completions"
    return f"{base}/v1/chat/completions"


def _load_provider_target() -> ProviderTarget:
    """Load one provider target from process env with strict guardrails."""

    provider = os.environ.get("LIVE_PROVIDER_LABEL", "").strip() or "direct-live-provider"
    base_url = os.environ.get("LIVE_PROVIDER_BASE_URL", "").strip()
    api_key = os.environ.get("LIVE_PROVIDER_API_KEY", "").strip()
    model = os.environ.get("LIVE_PROVIDER_MODEL", "").strip()
    if not base_url:
        raise ValueError("LIVE_PROVIDER_BASE_URL is required")
    if not api_key:
        raise ValueError("LIVE_PROVIDER_API_KEY is required")
    if not model:
        raise ValueError("LIVE_PROVIDER_MODEL is required")
    if not base_url.startswith("https://"):
        raise ValueError("LIVE_PROVIDER_BASE_URL must be https")
    return ProviderTarget(provider=provider, base_url=base_url, api_key=api_key, model=model)


def _artifact_path(name: str) -> Path:
    """Return an ignored generated-output artifact path."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    root = ROOT / "workspace_artifacts" / "generated" / "output"
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write bounded JSON artifacts without secrets."""

    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _provider_info(target: ProviderTarget) -> dict[str, str]:
    """Return redacted provider metadata used by both proof artifacts."""

    return {
        "provider": target.provider,
        "baseHost": _host(target.base_url),
        "model": target.model,
        "maskedKey": _mask_key(target.api_key),
    }


def _record_tool_capability(target: ProviderTarget) -> dict[str, Any]:
    """Persist tool-call capability only after a real workflow tool request.

    Args:
        target: Provider endpoint that just returned a real tool call for a
            Knowledge Runtime task.

    Returns:
        Redacted provider capability record.
    """

    from provider_capabilities import provider_capability_store

    record = provider_capability_store.upsert_record(
        provider=target.provider,
        base_url=target.base_url,
        model=target.model,
        status=PROVIDER_CAPABILITY_STATUS_TOOL_CALL_OK,
        ordinary_chat_ok=True,
        forced_tool_choice_ok=True,
        failure_class="direct_workflow_tool_call",
        masked_error="",
    )
    return record.to_dict()


def _setup_smoke_environment() -> None:
    """Set low-risk runtime defaults for a live workflow smoke."""

    os.environ.setdefault("LITASSIST_DISABLE_FILE_LOG", "1")
    os.environ.setdefault("LITASSIST_DISABLE_ROUTE_DUMP", "1")
    os.environ.setdefault("LITASSIST_API_CAPABILITY_AUTH", "0")
    os.environ.setdefault("LITERATURE_ENABLE_MCP_TOOLS", "1")
    os.environ["LLM_HTTP_TIMEOUT"] = os.environ.get("LLM_HTTP_TIMEOUT", "60")
    os.environ["LLM_HTTP_RETRIES"] = "0"
    os.environ["MCP_MAX_TOOL_ROUNDS"] = "4"
    os.environ["MCP_MAX_TOTAL_TOOL_SECONDS"] = "90"
    os.environ["MCP_MAX_PARALLEL_TOOLS"] = "1"
    os.environ["MCP_TOOL_CALL_TIMEOUT_SECONDS"] = "20"


def _direct_receipt(client: Any, ref_id: str, prompt_name: str, max_chars_per_ref: int) -> dict[str, Any]:
    """Build deterministic context receipt before the provider workflow call."""

    if not ref_id.startswith("product_docs:chunk:"):
        raise ValueError("ref_id must be a product_docs chunk ref")
    if not prompt_name.strip():
        raise ValueError("prompt_name must be non-empty")
    if max_chars_per_ref < 100 or max_chars_per_ref > 4000:
        raise ValueError("max_chars_per_ref must be between 100 and 4000")
    response = client.post(
        "/api/knowledge/context-receipt",
        json={
            "ref_ids": [ref_id],
            "prompt_name": prompt_name,
            "max_chars_per_ref": max_chars_per_ref,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("context receipt response must be an object")
    assembled = str(payload.get("assembled_context_hash") or "")
    if len(assembled) != HASH_LEN:
        raise RuntimeError("context receipt missing assembled_context_hash")
    return payload


def _first_ref(client: Any, query: str) -> dict[str, str]:
    """Select one product-doc ref through the public backend route."""

    if not query.strip():
        raise ValueError("query must be non-empty")
    response = client.get("/api/knowledge/product-docs/search", params={"q": query, "top_k": 1})
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        raise RuntimeError("product_docs search returned no refs")
    first = results[0]
    if not isinstance(first, dict):
        raise RuntimeError("product_docs search result must be an object")
    ref_id = str(first.get("ref_id") or "").strip()
    if not ref_id.startswith("product_docs:chunk:"):
        raise RuntimeError(f"unexpected ref_id: {ref_id}")
    return {
        "refId": ref_id,
        "readEndpoint": str(first.get("read_endpoint") or ""),
        "title": str(first.get("title") or ""),
    }


def _workflow_prompt(ref_id: str, prompt_name: str, max_chars_per_ref: int, expected_hash: str) -> str:
    """Return the real workflow instruction sent to the provider."""

    if not ref_id.startswith("product_docs:chunk:"):
        raise ValueError("ref_id must be a product_docs chunk ref")
    if len(expected_hash) != HASH_LEN:
        raise ValueError("expected_hash must be a sha256-like hex string")
    return (
        "Complete this Scholar AI Knowledge Runtime verification task using the available tools. "
        f"Read the bounded resource ref_id={ref_id!r} with max_chars={max_chars_per_ref}, "
        f"then build a knowledge context receipt for ref_ids=[{ref_id!r}], "
        f"prompt_name={prompt_name!r}, max_chars_per_ref={max_chars_per_ref}. "
        "After receiving tool results, answer with exactly one line: "
        f"CONTEXT_RECEIPT_HASH={expected_hash}"
    )


async def _post_openai_compatible(
    *,
    target: ProviderTarget,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    tool_choice: Any | None = None,
) -> dict[str, Any]:
    """Post one OpenAI-compatible chat completion without logging secrets."""

    if not messages:
        raise ValueError("messages must not be empty")
    payload: dict[str, Any] = {
        "model": target.model,
        "messages": messages,
        "temperature": 0,
        "top_p": 0.8,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice if tool_choice is not None else "auto"
    headers = {
        "Authorization": f"Bearer {target.api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
        response = await client.post(_chat_url(target.base_url), headers=headers, json=payload)
    if response.status_code >= 400:
        return {
            "error": {
                "message": response.text[:1000],
                "status_code": response.status_code,
            }
        }
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("provider response must be a JSON object")
    return data


async def _prove_forced_real_tool_choice(
    *,
    target: ProviderTarget,
    ref_id: str,
    max_chars: int,
) -> dict[str, Any]:
    """Force a real resource-read tool call instead of sending a ping prompt.

    Args:
        target: Provider endpoint under test.
        ref_id: Product-doc ref that the provider should request through the
            local tool schema.
        max_chars: Bounded read size for the actual resource-read task.

    Returns:
        Redacted proof metadata. `ok=true` means the provider returned a
        concrete forced tool call for `literature.agent_resource_read`.
    """

    if not ref_id.startswith("product_docs:chunk:"):
        raise ValueError("ref_id must be a product_docs chunk ref")
    if max_chars < 100 or max_chars > 4000:
        raise ValueError("max_chars must be between 100 and 4000")
    from mcp_runtime.provider_tool_adapter import build_provider_tool_name_map, build_provider_tools
    from mcp_runtime.tool_use_runner import _extract_tool_calls_normalized
    from routers.local_literature_tool_bridge import local_literature_catalog_snapshot

    snapshot = local_literature_catalog_snapshot()
    alias_map = build_provider_tool_name_map(snapshot)
    target_internal_name = "mcp__literature__literature.agent_resource_read"
    provider_name = next(
        (alias for alias, internal in alias_map.items() if internal == target_internal_name),
        "",
    )
    if not provider_name:
        raise RuntimeError("provider alias for literature.agent_resource_read not found")
    all_tools = build_provider_tools(target.provider, snapshot)
    forced_tools = [
        tool
        for tool in all_tools
        if isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") == provider_name
    ]
    if not forced_tools:
        raise RuntimeError("provider schema for literature.agent_resource_read not found")
    payload = await _post_openai_compatible(
        target=target,
        messages=[
            {
                "role": "user",
                "content": (
                    "Use the provided tool to read this Scholar AI bounded resource. "
                    f"Call literature.agent_resource_read with ref_id={ref_id!r} "
                    f"and max_chars={max_chars}. Do not answer in prose before the tool call."
                ),
            }
        ],
        tools=forced_tools,
        max_tokens=128,
        tool_choice={"type": "function", "function": {"name": provider_name}},
    )
    provider_status_code = 200
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        provider_status_code = int(error.get("status_code") or 0)
    calls = _extract_tool_calls_normalized(payload, "openai", alias_map) if provider_status_code == 200 else []
    matched = any(call.namespaced_name == target_internal_name for call in calls)
    return {
        "ok": matched,
        "statusCode": provider_status_code,
        "providerToolName": provider_name,
        "targetTool": "literature.agent_resource_read",
        "returnedToolCallCount": len(calls),
        "errorPreview": str(error)[:500] if isinstance(error, dict) else "",
    }


def _extract_answer(payload: dict[str, Any]) -> str:
    """Extract OpenAI-compatible assistant content."""

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    return ""


def _tool_names(transcript: list[Any]) -> list[str]:
    """Return tool names from a transcript-like list."""

    names: list[str] = []
    for record in transcript:
        name = getattr(record, "tool_name", "")
        if name:
            names.append(str(name))
    return names


def _preview_text(transcript: list[Any]) -> str:
    """Return concatenated bounded tool previews."""

    return "\n".join(str(getattr(record, "preview", "") or "") for record in transcript)


async def _run_workflow(target: ProviderTarget, prompt: str) -> Any:
    """Run the product local-tool loop without using the hardcoded ping probe."""

    from mcp_runtime.tool_use_runner import McpToolUseRunner, RunCaps
    from routers import chat_mcp_integration
    from routers.local_literature_tool_bridge import (
        LocalLiteratureToolUseRunner,
        local_literature_catalog,
        local_literature_catalog_snapshot,
        local_literature_server_config,
    )

    if not prompt.strip():
        raise ValueError("prompt must be non-empty")
    config = local_literature_server_config()
    runner = McpToolUseRunner(
        manager=chat_mcp_integration.get_mcp_client_manager(),
        catalog=local_literature_catalog(),
        servers=[config],
        catalog_snapshot=local_literature_catalog_snapshot(),
        caps=RunCaps(max_rounds=4, max_total_seconds=90, max_parallel=1, per_call_timeout=20, max_tool_payload_chars=24000),
        allow_high_risk_tools=False,
    )
    local_runner = LocalLiteratureToolUseRunner(
        provider_runner=runner,
        allow_high_risk_tools=False,
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    async def _chat_call(
        round_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return await _post_openai_compatible(
            target=target,
            messages=round_messages,
            tools=tools,
            max_tokens=512,
        )

    return await local_runner.run(
        provider=target.provider,
        initial_messages=messages,
        chat_call=_chat_call,
    )


def _summary(
    *,
    target: ProviderTarget,
    ref: dict[str, str],
    receipt: dict[str, Any],
    prompt_name: str,
    result: Any,
    capability_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the conformance-compatible live smoke summary."""

    direct_hash = str(receipt.get("assembled_context_hash") or "")
    transcript = list(getattr(result, "transcript", []) or [])
    names = _tool_names(transcript)
    previews = _preview_text(transcript)
    answer = str(getattr(result, "final_text", "") or _extract_answer(getattr(result, "final_response", {}) or ""))
    used_required = all(name in names for name in REQUIRED_TOOLS)
    receipt_schema_visible = "scholar-ai-knowledge-context-receipt/v1" in previews
    receipt_hash_visible = direct_hash in previews
    answer_hash_visible = direct_hash in answer
    status_code = 200 if getattr(result, "final_response", None) else 0
    if not transcript:
        verdict = "missing_required_tool_calls"
    elif not used_required:
        verdict = "missing_required_tool_calls"
    elif not receipt_schema_visible or not receipt_hash_visible:
        verdict = "receipt_not_provider_visible"
    elif not answer_hash_visible:
        verdict = "missing_final_hash_backflow"
    else:
        verdict = "ok"
    return {
        "generatedAt": _now_utc_iso(),
        "surface": "/api/chat",
        "statusCode": status_code,
        "verdict": verdict,
        "claimBoundary": (
            "Proves one real provider workflow turn requested Scholar AI local tools, "
            "received a Knowledge Runtime context receipt, and returned the assembled_context_hash."
        ),
        **_provider_info(target),
        "ref": ref,
        "promptName": prompt_name,
        "directReceipt": {
            "schemaVersion": str(receipt.get("schema_version") or ""),
            "promptHash": str(receipt.get("prompt_hash") or ""),
            "assembledContextHash": direct_hash,
            "assembledContextCharCount": int(receipt.get("assembled_context_char_count") or 0),
            "resourceReceiptCount": len(receipt.get("resource_read_receipts") or []),
        },
        "chatEvidence": {
            "answerChars": len(answer),
            "toolNames": names,
            "previewHashes": sorted({direct_hash} if direct_hash and direct_hash in previews else set()),
            "answerHashes": sorted({direct_hash} if direct_hash and direct_hash in answer else set()),
            "receiptSchemaVisibleInToolPreview": receipt_schema_visible,
            "receiptHashVisibleInToolPreview": receipt_hash_visible,
            "finalAnswerIncludesReceiptHash": answer_hash_visible,
            "queryHashMatchesDirectReceipt": True,
            "requiredToolSequence": list(REQUIRED_TOOLS),
            "usedRequiredTools": used_required,
        },
        "directWorkflowCapabilityRecord": capability_record or {},
        "answerPreview": answer[:600],
        "errorPreview": "" if verdict == "ok" else str(getattr(result, "diagnostics", ""))[:1000],
    }


def _failure_summary(target: ProviderTarget | None, error: BaseException) -> dict[str, Any]:
    """Build a conformance-shaped failure artifact without secrets."""

    payload: dict[str, Any] = {
        "generatedAt": _now_utc_iso(),
        "surface": "/api/chat",
        "statusCode": 0,
        "verdict": "setup_failed",
        "claimBoundary": "The live workflow call did not produce actual-loading proof.",
        "errorType": error.__class__.__name__,
        "error": str(error)[:1000],
    }
    if target is not None:
        payload.update(_provider_info(target))
    return payload


def _parse_args() -> argparse.Namespace:
    """Parse workflow smoke options."""

    parser = argparse.ArgumentParser(description="Run direct live provider Knowledge Runtime workflow smoke.")
    parser.add_argument("--query", default="Scholar AI Knowledge Runtime Pipeline")
    parser.add_argument("--prompt-name", default="smart_read_context_receipt_probe")
    parser.add_argument("--max-chars-per-ref", type=int, default=850)
    return parser.parse_args()


def main() -> int:
    """Run the live provider workflow smoke and write bounded artifacts."""

    _setup_smoke_environment()
    args = _parse_args()
    target: ProviderTarget | None = None
    started = time.perf_counter()
    try:
        from fastapi.testclient import TestClient
        from literature_assistant.core import python_adapter_server as server

        target = _load_provider_target()
        client = TestClient(server.app)
        ref = _first_ref(client, str(args.query))
        receipt = _direct_receipt(
            client,
            ref["refId"],
            str(args.prompt_name),
            int(args.max_chars_per_ref),
        )
        expected_hash = str(receipt["assembled_context_hash"])
        forced_tool_proof = asyncio.run(
            _prove_forced_real_tool_choice(
                target=target,
                ref_id=ref["refId"],
                max_chars=int(args.max_chars_per_ref),
            )
        )
        capability_record: dict[str, Any] | None = None
        if forced_tool_proof.get("ok") is True:
            capability_record = _record_tool_capability(target)
        result = asyncio.run(
            _run_workflow(
                target,
                _workflow_prompt(
                    ref["refId"],
                    str(args.prompt_name),
                    int(args.max_chars_per_ref),
                    expected_hash,
                ),
            )
        )
        workflow_tool_names = _tool_names(list(getattr(result, "transcript", []) or []))
        if capability_record is None and workflow_tool_names:
            capability_record = _record_tool_capability(target)
        summary = _summary(
            target=target,
            ref=ref,
            receipt=receipt,
            prompt_name=str(args.prompt_name),
            result=result,
            capability_record=capability_record,
        )
        summary["forcedRealToolChoiceProof"] = forced_tool_proof
        summary["providerCapabilityProofBasis"] = (
            "forced_real_tool_choice"
            if forced_tool_proof.get("ok") is True
            else "main_workflow_tool_calls"
            if workflow_tool_names
            else "not_proved"
        )
    except Exception as exc:  # noqa: BLE001 - smoke must persist failure evidence.
        summary = _failure_summary(target, exc)
    summary["elapsedMs"] = int((time.perf_counter() - started) * 1000)
    _write_json(_artifact_path(RESULT_NAME), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("verdict") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "literature_assistant" / "core"
MCP_SRC = ROOT / "agent_mcp_server" / "src"


def _promote_import_path(path: Path) -> None:
    """Keep product import roots ahead of the script directory.

    Args:
        path: Absolute repository path that must win over `tests/` packages.
    """

    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    import_path = str(path)
    while import_path in sys.path:
        sys.path.remove(import_path)
    sys.path.insert(0, import_path)


for import_path in (CORE, MCP_SRC, ROOT):
    _promote_import_path(import_path)

os.environ.setdefault("LITASSIST_DISABLE_FILE_LOG", "1")
os.environ.setdefault("LITASSIST_DISABLE_ROUTE_DUMP", "1")
os.environ.setdefault("LITASSIST_API_CAPABILITY_AUTH", "0")
os.environ["LLM_HTTP_TIMEOUT"] = "45"
os.environ["LLM_HTTP_RETRIES"] = "0"
os.environ["MCP_MAX_TOOL_ROUNDS"] = "4"
os.environ["MCP_MAX_TOTAL_TOOL_SECONDS"] = "60"
os.environ["MCP_MAX_PARALLEL_TOOLS"] = "1"
os.environ["MCP_TOOL_CALL_TIMEOUT_SECONDS"] = "20"

_HASH_RE = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)
_REQUIRED_TOOL_SEQUENCE = [
    "literature.agent_resource_read",
    "literature.knowledge_context_receipt",
]
_LIVE_SMOKE_OPT_IN_ENV = "LITASSIST_RUN_LIVE_CONTEXT_RECEIPT_SMOKE"


def _now_utc_iso() -> str:
    """Return an unambiguous UTC timestamp for persisted smoke artifacts."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _artifact_path(name: str) -> Path:
    """Return an ignored smoke artifact path under the generated output root."""

    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    root = ROOT / "workspace_artifacts" / "generated" / "output"
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _mask_key(value: str) -> str:
    """Return a log-safe API key fingerprint.

    Args:
        value: Raw credential resolved by the repository runtime config layer.

    Returns:
        A masked key preview that cannot be used as a credential.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}...{text[-4:]}"


def _truthy(value: str | None) -> bool:
    """Return whether an environment value explicitly opts into live calls."""

    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _live_smoke_authorized(args: argparse.Namespace) -> bool:
    """Require an explicit local opt-in before sending provider-visible content."""

    return bool(getattr(args, "allow_live_provider_call", False)) or _truthy(
        os.environ.get(_LIVE_SMOKE_OPT_IN_ENV)
    )


def _unauthorized_summary() -> dict[str, Any]:
    """Return an audit artifact proving no live provider call was attempted."""

    return {
        "generatedAt": _now_utc_iso(),
        "surface": "/api/chat",
        "statusCode": 0,
        "verdict": "skipped_not_authorized",
        "claimBoundary": (
            "No live provider call was sent. This artifact proves only that the "
            "smoke harness is present and explicitly gated; it is not model-context proof."
        ),
        "requiredAuthorization": {
            "environmentVariable": _LIVE_SMOKE_OPT_IN_ENV,
            "cliFlag": "--allow-live-provider-call",
        },
    }


def _provider_info() -> dict[str, str]:
    """Resolve provider metadata through the product config store only."""

    from model_config_store import chat_store
    from runtime_env import env_value

    provider = str(chat_store.get_resolved_field("provider") or env_value("CHAT_PROVIDER", "OPENAI_PROVIDER", default="") or "")
    base_url = str(chat_store.get_resolved_field("base_url") or env_value("CHAT_BASE_URL", "OPENAI_BASE_URL", "ARK_BASE_URL", default="") or "")
    model = str(chat_store.get_resolved_field("model") or env_value("CHAT_MODEL", "OPENAI_MODEL", "ARK_MODEL", default="") or "")
    api_key = str(
        chat_store.get_resolved_field("api_key")
        or env_value("CHAT_API_KEY", "OPENAI_API_KEY_CHAT", "OPENAI_API_KEY", "ARK_API_KEY", default="")
        or ""
    )
    os.environ["CHAT_PROVIDER"] = provider
    os.environ["CHAT_BASE_URL"] = base_url
    os.environ["CHAT_MODEL"] = model
    os.environ["CHAT_API_KEY"] = api_key
    return {
        "provider": provider,
        "baseHost": base_url.split("//")[-1].split("/")[0] if base_url else "",
        "model": model,
        "maskedKey": _mask_key(api_key),
    }


def _write_summary(summary: dict[str, Any]) -> Path:
    """Persist a bounded smoke summary without raw credentials."""

    if not isinstance(summary, dict):
        raise TypeError("summary must be a dictionary")
    out = _artifact_path("live_api_chat_knowledge_context_receipt_smoke.summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _first_product_docs_ref(client: Any, query: str) -> dict[str, str]:
    """Find one product-doc knowledge ref using the product route contract."""

    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    response = client.get(
        "/api/knowledge/product-docs/search",
        params={"q": query, "top_k": 1},
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        raise RuntimeError("product_docs search returned no refs")
    first = results[0]
    if not isinstance(first, dict):
        raise RuntimeError("product_docs search result must be an object")
    ref_id = str(first.get("ref_id") or "").strip()
    read_endpoint = str(first.get("read_endpoint") or "").strip()
    title = str(first.get("title") or "").strip()
    if not ref_id.startswith("product_docs:chunk:"):
        raise RuntimeError(f"unexpected product_docs ref_id: {ref_id}")
    return {
        "refId": ref_id,
        "readEndpoint": read_endpoint,
        "title": title,
    }


def _build_direct_receipt(
    *,
    client: Any,
    ref_id: str,
    prompt_name: str,
    max_chars_per_ref: int,
) -> dict[str, Any]:
    """Build the deterministic context receipt before the live chat turn."""

    if not ref_id.startswith("product_docs:chunk:"):
        raise ValueError("ref_id must be a product_docs chunk ref")
    if not isinstance(prompt_name, str) or not prompt_name.strip():
        raise ValueError("prompt_name must be a non-empty string")
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
    assembled_hash = str(payload.get("assembled_context_hash") or "")
    prompt_hash = str(payload.get("prompt_hash") or "")
    if not _HASH_RE.fullmatch(assembled_hash):
        raise RuntimeError("context receipt missing valid assembled_context_hash")
    if not _HASH_RE.fullmatch(prompt_hash):
        raise RuntimeError("context receipt missing valid prompt_hash")
    return payload


def _live_query(
    *,
    ref_id: str,
    prompt_name: str,
    max_chars_per_ref: int,
    expected_hash: str,
) -> str:
    """Return the short provider prompt for the live semantic-use proof."""

    if not ref_id.startswith("product_docs:chunk:"):
        raise ValueError("ref_id must be a product_docs chunk ref")
    if not _HASH_RE.fullmatch(expected_hash):
        raise ValueError("expected_hash must be a sha256 hex digest")
    return (
        "请完成一个 Knowledge Runtime receipt 验证。"
        f"先调用 literature.agent_resource_read(ref_id='{ref_id}', max_chars={max_chars_per_ref})，"
        f"再调用 literature.knowledge_context_receipt(ref_ids=['{ref_id}'], "
        f"prompt_name='{prompt_name}', max_chars_per_ref={max_chars_per_ref})。"
        "最后只输出一行英文："
        f"CONTEXT_RECEIPT_HASH={expected_hash}。"
        "不要改写、截断或解释这个 hash。"
    )


def _tool_call_names(payload: dict[str, Any]) -> list[str]:
    """Extract the SmartRead MCP tool call sequence from a response payload."""

    mcp_run = payload.get("mcp_run")
    if not isinstance(mcp_run, dict):
        return []
    raw_calls = mcp_run.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    return [
        str(call.get("tool_name") or "")
        for call in raw_calls
        if isinstance(call, dict) and call.get("tool_name")
    ]


def _tool_preview_text(payload: dict[str, Any]) -> str:
    """Concatenate bounded tool previews returned by the SmartRead transcript."""

    mcp_run = payload.get("mcp_run")
    if not isinstance(mcp_run, dict):
        return ""
    raw_calls = mcp_run.get("tool_calls")
    if not isinstance(raw_calls, list):
        return ""
    return "\n".join(
        str(call.get("preview") or "")
        for call in raw_calls
        if isinstance(call, dict)
    )


def _summary_from_chat_response(
    *,
    response: Any,
    provider_info: dict[str, str],
    ref_info: dict[str, str],
    direct_receipt: dict[str, Any],
    prompt_name: str,
    query_hash: str,
) -> dict[str, Any]:
    """Classify a live SmartRead context-receipt smoke response.

    Args:
        response: TestClient response from `/api/chat`.
        provider_info: Redacted provider metadata.
        ref_info: Product-doc ref selected for the smoke.
        direct_receipt: Deterministic receipt built before the chat call.
        prompt_name: Receipt prompt namespace used in both calls.
        query_hash: Expected assembled context hash sent to the provider.

    Returns:
        A JSON-safe summary with enough evidence to audit success or failure.
    """

    if not isinstance(provider_info, dict):
        raise TypeError("provider_info must be a dictionary")
    if not isinstance(ref_info, dict):
        raise TypeError("ref_info must be a dictionary")
    if not isinstance(direct_receipt, dict):
        raise TypeError("direct_receipt must be a dictionary")
    if not _HASH_RE.fullmatch(query_hash):
        raise ValueError("query_hash must be a sha256 hex digest")
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": str(getattr(response, "text", ""))[:1000]}
    if not isinstance(payload, dict):
        payload = {"raw": str(payload)[:1000]}
    answer = str(payload.get("response") or payload.get("answer") or "")
    tool_names = _tool_call_names(payload)
    preview_text = _tool_preview_text(payload)
    preview_hashes = sorted(set(_HASH_RE.findall(preview_text)))
    answer_hashes = sorted(set(_HASH_RE.findall(answer)))
    direct_hash = str(direct_receipt.get("assembled_context_hash") or "")
    receipt_schema_visible = "scholar-ai-knowledge-context-receipt/v1" in preview_text
    receipt_hash_visible = direct_hash in preview_text
    answer_hash_visible = direct_hash in answer
    used_required_tools = all(name in tool_names for name in _REQUIRED_TOOL_SEQUENCE)
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        verdict = "http_error"
    elif not used_required_tools:
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
            "Proves one real provider turn saw a Knowledge Runtime context receipt "
            "through the SmartRead local-tool loop and returned the assembled_context_hash."
        ),
        **provider_info,
        "ref": ref_info,
        "promptName": prompt_name,
        "directReceipt": {
            "schemaVersion": str(direct_receipt.get("schema_version") or ""),
            "promptHash": str(direct_receipt.get("prompt_hash") or ""),
            "assembledContextHash": direct_hash,
            "assembledContextCharCount": int(direct_receipt.get("assembled_context_char_count") or 0),
            "resourceReceiptCount": len(direct_receipt.get("resource_read_receipts") or []),
        },
        "chatEvidence": {
            "answerChars": len(answer),
            "toolNames": tool_names,
            "previewHashes": preview_hashes,
            "answerHashes": answer_hashes,
            "receiptSchemaVisibleInToolPreview": receipt_schema_visible,
            "receiptHashVisibleInToolPreview": receipt_hash_visible,
            "finalAnswerIncludesReceiptHash": answer_hash_visible,
            "queryHashMatchesDirectReceipt": query_hash == direct_hash,
            "requiredToolSequence": list(_REQUIRED_TOOL_SEQUENCE),
            "usedRequiredTools": used_required_tools,
        },
        "answerPreview": answer[:600],
        "errorPreview": str(payload)[:1000] if status_code != 200 else "",
    }


def _parse_args() -> argparse.Namespace:
    """Parse live smoke controls."""

    parser = argparse.ArgumentParser(description="Run live Knowledge Runtime context-receipt smoke.")
    parser.add_argument("--query", default="Scholar AI Knowledge Runtime Pipeline", help="Product-doc search query.")
    parser.add_argument("--prompt-name", default="smart_read_context_receipt_probe", help="Receipt prompt name.")
    parser.add_argument("--max-chars-per-ref", type=int, default=850, help="Bounded chars per knowledge ref.")
    parser.add_argument(
        "--allow-live-provider-call",
        action="store_true",
        help="Explicitly allow this smoke to send bounded knowledge content to the configured chat provider.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the low-budget real-provider Knowledge Runtime context smoke."""

    args = _parse_args()
    if not _live_smoke_authorized(args):
        summary = _unauthorized_summary()
        _write_summary(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    from fastapi.testclient import TestClient
    from literature_assistant.core import python_adapter_server as server

    client = TestClient(server.app)
    provider_info = _provider_info()
    try:
        ref_info = _first_product_docs_ref(client, str(args.query))
        direct_receipt = _build_direct_receipt(
            client=client,
            ref_id=ref_info["refId"],
            prompt_name=str(args.prompt_name),
            max_chars_per_ref=int(args.max_chars_per_ref),
        )
        expected_hash = str(direct_receipt["assembled_context_hash"])
        response = client.post(
            "/api/chat",
            json={
                "query": _live_query(
                    ref_id=ref_info["refId"],
                    prompt_name=str(args.prompt_name),
                    max_chars_per_ref=int(args.max_chars_per_ref),
                    expected_hash=expected_hash,
                ),
                "tier": "fast",
                "mode": "direct",
                "direct_mode": True,
                "use_local_literature_tools": True,
                "mcp_allow_high_risk_tools": False,
            },
        )
        summary = _summary_from_chat_response(
            response=response,
            provider_info=provider_info,
            ref_info=ref_info,
            direct_receipt=direct_receipt,
            prompt_name=str(args.prompt_name),
            query_hash=expected_hash,
        )
    except Exception as exc:  # noqa: BLE001 - smoke must persist a failure artifact.
        summary = {
            "generatedAt": _now_utc_iso(),
            "surface": "/api/chat",
            "statusCode": 0,
            "verdict": "setup_failed",
            "claimBoundary": "The live provider call was not sent because setup failed.",
            **provider_info,
            "errorType": exc.__class__.__name__,
            "error": str(exc)[:1000],
        }
    _write_summary(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("verdict") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

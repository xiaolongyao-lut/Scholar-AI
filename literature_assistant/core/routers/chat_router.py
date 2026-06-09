# -*- coding: utf-8 -*-
"""Chat proxy router — forwards user queries to configured LLM with document context.

Supports both synchronous (POST /chat/ask) and streaming (POST /chat/stream) modes.
Streaming uses Server-Sent Events (SSE) following the text/event-stream protocol.
Pattern learned from textgen-4.4 and openhanako WebSocket streaming.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from models.analysis_chain import AnalysisChainPayload
from prompts.project_reasoning_bias import (
    ProjectReasoningBiasContext,
    apply_project_reasoning_bias,
    load_project_reasoning_bias,
    render_project_reasoning_bias_block,
    should_apply_project_reasoning_bias,
)

from ai_cost_profile import normalize_cost_profile, use_cost_profile
from llm_defaults import resolve_llm_params
from llm_cost_logger import log_llm_call
from llm_pricing import usage_from_response
from sampling_storage import load_user_sampling
from model_config_store import chat_store
from runtime_env import env_value
from routers import chat_mcp_integration
from provider_endpoint_policy import TrustSource, validate_endpoint
from provider_catalog import (
    MODEL_CATALOG,
    SUPPORTED_PROVIDERS,
    ModelInfo,
    ProviderInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

_CHAT_ASK_DEPRECATION_HEADERS = {
    "Deprecation": "Tue, 26 May 2026 00:00:00 GMT",
    "Sunset": "Wed, 01 Jul 2026 00:00:00 GMT",
    "Link": '</api/chat>; rel="successor-version", </api/chat/stream>; rel="successor-version"',
}


class LLMConfig(BaseModel):
    provider: str = "DeepSeek"
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    max_tokens: int = 4096
    system_prompt: str = ""


class ChatMessage(BaseModel):
    """A single turn in the conversation history."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")


# Envelope for the assembled prompt that callers pass via ``ChatRequest.query``
# / ``ChatStreamRequest.query``. Discussion + Inspiration paths assemble the
# full per-agent prompt (system suffix + user question + evidence + history)
# and pass it here, so the cap must accommodate the documented **first-turn
# evidence envelope**:
#
#   evidence:        50 snippets × 1200 chars  = 60_000  (DiscussionRunConfig.evidence_top_k ≤ 50,
#                                                          evidence_pack.DEFAULT_MAX_SNIPPET_CHARS = 1200)
#   per-snippet header (~"[E1] source (chunk=… score=…)\n" × 50)  ≈  5_000
#   DiscussionRunConfig.query (hard cap)                          =  4_096
#   CITATION_CONTRACT_SUFFIX + role/identity/turn framing         ≈  2_000
#   safety buffer for system_prompt + short history               ≈  8_900
#   ─────────────────────────────────────────────────────────────────────
#   total                                                         ≈ 80_000
#
# This is **not** a Discussion full-run worst case: ``_format_history`` in
# ``discussion_orchestrator.py`` accumulates prior agent answers across turns
# without a schema-layer hard cap, and ``DiscussionAgentTrace.answer`` itself
# has no ``max_length``. A run with many turns / many agents / verbose
# answers can therefore exceed this envelope. Tracked as FD-14 in
# ``docs/plans/active/2026-05-21-bug-fix-plan.md`` §7.3; the right fix is to
# cap history bytes (or summarize older turns, or migrate evidence/history
# off ``query``), not to keep widening this constant indefinitely.
#
# FD-14 / FD-14.1 / FD-14.2 were implemented 2026-05-21 in
# ``literature_assistant.core.discussion_orchestrator``:
#   * ``MAX_HISTORY_LENGTH = 8_000`` — rolling-newest-turns window in
#     ``_format_history``; callers pass a tighter dynamic max_length when
#     non-history prompt sections consume most of this envelope. Oldest turns
#     are dropped with a single ``[history truncated: N earlier turns omitted]``
#     notice.
#   * ``MAX_AGENT_ANSWER_LENGTH = 4_000`` — write-only cap on
#     ``DiscussionAgentTrace.answer`` applied in ``_result_to_trace``;
#     schema field has no ``max_length`` so legacy artifacts still load
#     (D-HC-5 backward compatibility).
#   * the final assembled Discussion prompt is checked before it is passed to
#     ``ChatRequest``; oversized non-history sections fail fast in the
#     orchestrator instead of surfacing as a generic request validation error.
# Future cap raises should still update the math above.
MAX_CHAT_QUERY_LENGTH = 80_000


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_CHAT_QUERY_LENGTH)
    context: list[str] = Field(default_factory=list, description="Document text chunks as context")
    history: list[ChatMessage] = Field(default_factory=list, description="Previous conversation turns")
    llm: LLMConfig | None = Field(default=None, description="LLM config from client (optional; backend resolves from runtime override + env if absent)")
    sampling: dict[str, float | int] | None = Field(default=None, description="Per-task sampling overrides")
    ai_cost_profile: str | None = Field(default=None, description="balanced | aggressive | quality")
    project_id: str | None = Field(default=None, max_length=128, description="Project id used to resolve project reasoning bias")
    project_reasoning_bias_enabled: bool | None = Field(
        default=None,
        description="Per-request override. False disables project reasoning bias injection.",
    )
    tools: list[dict[str, Any]] | None = Field(default=None, description="Tool/function definitions for skill calling")
    mcp_server_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional MCP service scope for this chat request. When omitted, "
            "the request uses the normal chat path; an empty list records an "
            "explicit no-service run."
        ),
    )
    mcp_allow_high_risk_tools: bool = Field(
        default=False,
        description=(
            "Per-request flag to allow tools tagged write/filesystem/"
            "destructive. Default False — high-risk tools return an "
            "approval-blocked record."
        ),
    )


class ChatResponse(BaseModel):
    answer: str
    model: str
    usage: dict[str, Any] | None = None
    sampling_params: dict[str, Any] | None = Field(default=None, description="Actual sampling params used")
    tool_calls: list[dict[str, Any]] | None = Field(default=None, description="Tool calls from LLM (for skill execution)")
    mcp_run: dict[str, Any] | None = Field(
        default=None,
        description=(
            "MCP tool-use transcript. Populated only when the request uses "
            "MCP services."
        ),
    )
    analysis_chain: AnalysisChainPayload | None = Field(
        default=None,
        description=(
            "Structured 6-field reasoning chain (observation / mechanism / "
            "evidence / boundary / counter_evidence / next_action). "
            "Populated only when feature flag ``analysis_chain_rag`` is on. "
            "ACR-020 ~ ACR-024."
        ),
    )


def _resolve_chat_llm(llm: LLMConfig | None) -> LLMConfig:
    """Resolve the effective LLM config for a chat request.

    Priority: request-provided llm > chat_override.json > env vars > defaults.
    When llm is None or has empty api_key+base_url, fill from runtime override + env.
    """
    if llm is not None and llm.api_key and llm.base_url:
        return llm

    # Build from runtime override + env fallback
    override_provider = chat_store.get_resolved_field("provider") or ""
    override_base_url = chat_store.get_resolved_field("base_url") or ""
    override_api_key = chat_store.get_resolved_field("api_key") or ""
    override_model = chat_store.get_resolved_field("model") or ""

    # Env fallback chain using env_value (reads both os.environ and repo .env)
    env_provider = env_value("CHAT_PROVIDER", "OPENAI_PROVIDER", default="DeepSeek") or "DeepSeek"
    env_base_url = env_value("CHAT_BASE_URL") or env_value("OPENAI_BASE_URL") or env_value("ARK_BASE_URL") or ""
    env_api_key = env_value("CHAT_API_KEY") or env_value("OPENAI_API_KEY_CHAT") or env_value("OPENAI_API_KEY") or env_value("ARK_API_KEY") or ""
    env_model = env_value("CHAT_MODEL") or env_value("OPENAI_MODEL") or env_value("ARK_MODEL") or ""

    resolved_provider = override_provider or (llm.provider if llm else "") or env_provider
    resolved_base_url = override_base_url or (llm.base_url if llm and llm.base_url else "") or env_base_url
    resolved_api_key = override_api_key or (llm.api_key if llm and llm.api_key else "") or env_api_key
    resolved_model = override_model or (llm.model if llm and llm.model else "") or env_model

    # Sampling params: prefer request-provided, then env defaults
    temperature = (llm.temperature if llm else None) or float(env_value("CHAT_TEMPERATURE", default="0.7") or "0.7")
    top_p = (llm.top_p if llm else None) or float(env_value("CHAT_TOP_P", default="0.9") or "0.9")
    top_k = (llm.top_k if llm else None) or int(env_value("CHAT_TOP_K", default="50") or "50")
    max_tokens = (llm.max_tokens if llm else None) or int(env_value("CHAT_MAX_TOKENS", default="4096") or "4096")
    system_prompt = (llm.system_prompt if llm else "") or env_value("CHAT_SYSTEM_PROMPT", default="") or ""

    if not resolved_base_url or not resolved_model:
        raise HTTPException(
            status_code=503,
            detail="未配置 Chat LLM：请在设置页填写 Base URL 和模型，或配置环境变量 CHAT_BASE_URL + CHAT_MODEL",
        )

    return LLMConfig(
        provider=resolved_provider,
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )


def _apply_ai_cost_profile_to_llm(llm: LLMConfig, profile: str | None) -> LLMConfig:
    """Apply cost-profile caps to LLM generation settings for this request only."""
    normalized = normalize_cost_profile(profile)
    if normalized != "aggressive":
        return llm
    return llm.model_copy(
        update={
            "max_tokens": min(llm.max_tokens, 1024),
            "temperature": min(llm.temperature, 0.3),
            "top_p": min(llm.top_p, 0.8),
        }
    )


def _resolve_request_llm_config(
    llm: LLMConfig,
    *,
    task: str,
    sampling: dict[str, float | int] | None,
) -> LLMConfig:
    file_overrides = (load_user_sampling() or {}).get(task, {})
    merged: dict[str, float | int] = {}
    if isinstance(file_overrides, dict):
        merged.update(file_overrides)
    if sampling:
        merged.update(sampling)
    resolved = resolve_llm_params(task, merged or None)
    return llm.model_copy(
        update={
            "temperature": float(resolved["temperature"]),
            "top_p": float(resolved["top_p"]),
            "top_k": int(resolved["top_k"]),
            "max_tokens": int(resolved["max_tokens"]),
        }
    )


def _provider_key(provider: str) -> str:
    """Normalize provider names for routing decisions."""
    return provider.strip().lower()


def _detect_provider_from_url(base_url: str) -> str | None:
    """Infer the likely provider from the base URL so that 'Local LLM' /
    'custom OpenAI-compatible' entries can reuse provider-specific endpoint
    and model-resolution logic automatically.

    Returns a normalised provider key string (same as _provider_key output)
    or None when the URL does not match any known pattern.
    """
    u = base_url.lower()
    # Volcano Engine / ByteDance Doubao
    if "volces.com" in u or "ark.cn-beijing" in u or "ark.volcengineapi" in u:
        return "doubao"
    # DeepSeek
    if "deepseek.com" in u:
        return "deepseek"
    # Anthropic Claude
    if "anthropic.com" in u:
        return "claude"
    # Google Gemini
    if "googleapis.com" in u or "generativelanguage" in u:
        return "gemini"
    # Zhipu GLM
    if "zhipuai.cn" in u or "bigmodel.cn" in u:
        return "zhipu"
    # Moonshot / Kimi
    if "moonshot.cn" in u:
        return "moonshot"
    # Alibaba Qwen / DashScope
    if "dashscope.aliyuncs.com" in u or "aliyuncs.com" in u:
        return "qwen"
    # OpenAI
    if "openai.com" in u:
        return "openai"
    # OpenRouter
    if "openrouter.ai" in u:
        return "openrouter"
    # SiliconFlow
    if "siliconflow.cn" in u:
        return "siliconflow"
    # Groq
    if "groq.com" in u:
        return "groq"
    # Mistral
    if "mistral.ai" in u:
        return "mistral"
    # Perplexity
    if "perplexity.ai" in u:
        return "perplexity"
    # MiniMax
    if "minimax" in u and "api" in u:
        return "minimax"
    return None


def _resolve_api_key(provider: str, provided_key: str | None) -> str:
    """Resolve service credential with server-side env fallback.

    Priority:
    1) Provided key from request payload
    2) Provider-specific env key for server-side defaults
    """
    explicit_key = (provided_key or "").strip()
    if explicit_key:
        return explicit_key

    provider_key = _provider_key(provider)
    env_map: dict[str, tuple[str, ...]] = {
        "doubao": ("ARK_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
        "openai": ("OPENAI_API_KEY",),
        "claude": ("ANTHROPIC_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "qwen": ("DASHSCOPE_API_KEY", "QWEN_API_KEY"),
        "zhipu": ("ZHIPU_API_KEY",),
        "moonshot": ("MOONSHOT_API_KEY",),
        "siliconflow": ("SILICONFLOW_API_KEY",),
        "openrouter": ("OPENROUTER_API_KEY",),
        "groq": ("GROQ_API_KEY",),
        "mistral": ("MISTRAL_API_KEY",),
        "perplexity": ("PERPLEXITY_API_KEY",),
        "minimax": ("MINIMAX_API_KEY",),
    }

    for env_name in env_map.get(provider_key, ()): 
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value

    return ""


def _build_chat_endpoint(base_url: str, provider: str) -> str:
    """Normalize provider base URL to the provider-specific chat endpoint."""
    base = base_url.strip().rstrip("/")
    provider_key = _provider_key(provider)
    detected_provider = _detect_provider_from_url(base)

    if detected_provider and detected_provider != provider_key:
        return _build_chat_endpoint(base, detected_provider)

    if provider_key == "gemini":
        if base.endswith("/chat/completions"):
            return base
        if "generativelanguage.googleapis.com" in base:
            return f"{base}/v1beta/openai/chat/completions"
        return f"{base}/v1/chat/completions"

    if provider_key == "claude":
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        if "/v1/" not in base:
            base = f"{base}/v1"
        return f"{base}/messages"

    if provider_key == "zhipu":
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v4"):
            return f"{base}/chat/completions"
        if "/v4/" not in base:
            base = f"{base}/v4"
        return f"{base}/chat/completions"

    if provider_key == "doubao":
        # B7+ (0.1.8.2 hotfix v4): user reported persistent 502 with
        # "Invalid URL (POST /v1/api/v3/chat/completions)" because their
        # config carried provider=doubao but base_url pointed at a
        # generic OpenAI-compatible proxy (e.g. chybenzun.top/v1). The
        # doubao branch appended /api/v3 to the OpenAI-style URL → 404
        # upstream. Detect this mismatch (URL doesn't look like a real
        # Volcano/Ark endpoint) and fall back to the OpenAI-compatible
        # path so the user's URL is honored verbatim.
        looks_like_real_doubao = any(
            marker in base.lower()
            for marker in ("volces.com", "ark.cn-beijing", "ark.volcengineapi")
        )
        if not looks_like_real_doubao:
            # Treat as OpenAI-compatible — fall through to the generic
            # branch below.
            if base.endswith("/chat/completions"):
                return base
            if not base.endswith("/v1") and "/v1/" not in base:
                base = f"{base}/v1"
            return f"{base}/chat/completions"
        if base.endswith("/chat/completions"):
            return base
        # Normalize to the /v3 anchor so any sub-path variant (/responses,
        # /v3/something, etc.) is reduced to the canonical base before
        # appending /chat/completions.
        if "/v3" in base:
            v3_pos = base.rfind("/v3")
            base = base[: v3_pos + 3]  # keep up to and including "/v3"
        elif "/api" in base:
            api_pos = base.rfind("/api")
            base = base[: api_pos + 4] + "/v3"
        else:
            base = f"{base}/api/v3"
        return f"{base}/chat/completions"

    # For "Local LLM" / "custom OpenAI-compatible" providers, detect the real
    # provider from the base URL and delegate to its specific normalizer so the
    # user doesn't have to manually switch the provider dropdown.
    if provider_key in {"local llm", "ollama"}:
        detected = _detect_provider_from_url(base_url)
        if detected and detected != provider_key:
            return _build_chat_endpoint(base_url, detected)
        # Generic OpenAI-compatible fallthrough below

    if base.endswith("/chat/completions"):
        return base

    if not base.endswith("/v1"):
        if "/v1/" not in base:
            base = f"{base}/v1"
    return f"{base}/chat/completions"


def _build_models_discovery_endpoint(base_url: str) -> str:
    """Build an OpenAI-compatible models endpoint from a path-only base URL."""

    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        raise ValueError("Base URL is empty")
    if "/v1/" in trimmed:
        idx = trimmed.rfind("/v1/")
        return f"{trimmed[: idx + 3]}/models"
    if trimmed.endswith("/v1"):
        return f"{trimmed}/models"
    return f"{trimmed}/v1/models"


def _allows_loopback_http_for_provider(provider: str, base_url: str) -> bool:
    """Return whether this provider is explicitly scoped to a local HTTP server."""

    try:
        parsed = urlsplit(base_url.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() != "http":
        return False
    return _provider_key(provider) in {"ollama", "local llm"}


def _validate_outbound_llm_base_url(base_url: str, provider: str) -> None:
    """Reject unsafe provider endpoints before credentials are sent over HTTP."""

    decision = validate_endpoint(
        base_url,
        trust_source=TrustSource.RUNTIME_USER_CONFIRMED,
        allow_loopback_http=_allows_loopback_http_for_provider(provider, base_url),
    )
    if not decision.allowed:
        raise ValueError(f"provider endpoint rejected: {decision.reason}")


def _build_openai_compatible_url(base_url: str, provider: str) -> str:
    """Backward-compatible alias for provider endpoint normalization."""
    return _build_chat_endpoint(base_url, provider)


def _build_system_text(system_prompt: str, context: list[str]) -> str:
    """Build a single system instruction block from prompt and retrieved context."""
    system_parts: list[str] = []
    if system_prompt:
        system_parts.append(system_prompt)
    if context:
        context_text = "\n\n---\n\n".join(context)
        system_parts.append(
            "以下是用户上传的参考文档内容，请基于这些文档回答用户的问题。"
            "如果文档中没有相关信息，请如实告知。\n\n"
            f"{context_text}"
        )
    return "\n\n".join(part for part in system_parts if part)


def _system_text_with_project_reasoning_bias(
    *,
    system_prompt: str,
    context: list[str],
    project_id: str | None,
    enabled: bool | None,
    surface: str,
) -> str:
    """Build system text and append project bias only when scope rules allow it."""
    base_system_text = _build_system_text(system_prompt, context)
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return base_system_text

    try:
        bias = load_project_reasoning_bias(normalized_project_id)
        if not should_apply_project_reasoning_bias(
            bias,
            ProjectReasoningBiasContext(
                surface=surface,
                request_enabled=True if enabled is None else bool(enabled),
            ),
        ):
            return base_system_text
        assert bias is not None
        rendered = render_project_reasoning_bias_block(bias, locale=bias.language)
        return apply_project_reasoning_bias(base_system_text, rendered)
    except Exception as exc:  # noqa: BLE001 - preference injection must not block chat.
        logger.warning("project_reasoning_bias injection skipped: project=%s err=%s", normalized_project_id, exc)
        return base_system_text


def _resolve_project_reasoning_bias_for_surface(
    *,
    project_id: str | None,
    enabled: bool | None,
    surface: str,
    agent_id: str | None = None,
) -> Any | None:
    """Resolve saved project bias for one AI surface without blocking callers."""
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return None
    try:
        bias = load_project_reasoning_bias(normalized_project_id)
        if should_apply_project_reasoning_bias(
            bias,
            ProjectReasoningBiasContext(
                surface=surface,
                agent_id=agent_id,
                request_enabled=True if enabled is None else bool(enabled),
            ),
        ):
            return bias
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "project_reasoning_bias resolution skipped: project=%s surface=%s err=%s",
            normalized_project_id,
            surface,
            exc,
        )
    return None


def resolve_effective_system_prompt(llm: LLMConfig | None = None) -> str:
    """Mirror the env-fallback logic ``_resolve_chat_llm`` applies to system_prompt.

    Exposed so external callers (e.g. ``discussion_orchestrator``) can compute
    the exact system_prompt the provider will receive when only ``query`` /
    ``context`` are populated and ``llm.system_prompt`` is empty. The discussion
    path never sets ``LLMConfig.system_prompt`` explicitly — it always inherits
    ``CHAT_SYSTEM_PROMPT`` from env via this resolution.

    Keep this function in lockstep with ``_resolve_chat_llm`` line 178:
    ``system_prompt = (llm.system_prompt if llm else "") or env_value("CHAT_SYSTEM_PROMPT", default="") or ""``.
    """
    if llm is not None and llm.system_prompt:
        return llm.system_prompt
    return env_value("CHAT_SYSTEM_PROMPT", default="") or ""


def compose_provider_system_text(
    llm: LLMConfig | None,
    context: list[str],
) -> str:
    """Return the exact system_text the provider will receive given llm + context.

    Combines ``resolve_effective_system_prompt`` (env-fallback) with
    ``_build_system_text`` (prelude + context join). Use this from any
    pre-flight budgeter that needs to know the real system-message size,
    not just the size derived from an unresolved LLMConfig.
    """
    return _build_system_text(resolve_effective_system_prompt(llm), context)


def _resolve_model_name(provider: str, model: str, base_url: str = "") -> str:
    """Resolve model names and guard against invalid placeholder values.

    When *provider* is 'Local LLM' and *model* is 'auto', the function tries
    to infer the right default model from *base_url* via _detect_provider_from_url.
    """
    provider_key = _provider_key(provider)
    normalized = (model or "").strip()

    if normalized and normalized.lower() != "auto":
        return normalized

    hosted_defaults: dict[str, str] = {
        "deepseek": "deepseek-chat",
        "openai": "gpt-4o-mini",
        "claude": "claude-sonnet-4-20250514",
        "gemini": "gemini-2.5-flash",
        "qwen": "qwen-plus",
        "zhipu": "glm-4-plus",
        "doubao": "ep-xxx",
        "moonshot": "moonshot-v1-auto",
        "siliconflow": "deepseek-ai/DeepSeek-V3",
        "openrouter": "deepseek/deepseek-chat-v3-0324",
        "groq": "llama-3.3-70b-versatile",
        "mistral": "mistral-small-latest",
        "perplexity": "sonar",
        "minimax": "abab6.5s-chat",
    }

    if provider_key in hosted_defaults:
        return hosted_defaults[provider_key]

    # For custom / local providers: try to detect from the base URL
    if provider_key in {"ollama", "local llm"} and base_url:
        detected = _detect_provider_from_url(base_url)
        if detected and detected in hosted_defaults:
            # Doubao needs a real endpoint ID — give a clear message
            if detected == "doubao":
                raise ValueError(
                    "识别到火山引擎接口，但模型为 auto。"
                    "请在[生成模型]字段填入接入点 ID（如 ep-xxxxxxxx-xxxx）后重试。"
                )
            return hosted_defaults[detected]

    if provider_key in {"ollama", "local llm"}:
        raise ValueError("当前 Provider 的模型为 auto，请先在系统设置中选择具体模型后再试。")

    raise ValueError(f"未配置可用模型: provider={provider}")


_CHARS_PER_TOKEN = 4  # rough estimate: 1 token ≈ 4 characters (mix of CJK and Latin)


def _compress_history(
    history: list[ChatMessage],
    max_tokens_budget: int,
) -> list[dict[str, str]]:
    """Convert history list to messages dicts, applying a sliding-window compression
    when the cumulative character length would exceed the token budget.

    Strategy:
    1. Walk from newest to oldest, accumulating character cost.
    2. Stop once adding the next message would overflow the budget.
    3. If any messages were dropped, prepend a synthetic system note so the
       model knows context was truncated.

    This is fully deterministic and requires no extra API call.
    """
    if not history:
        return []

    max_chars = max_tokens_budget * _CHARS_PER_TOKEN
    kept: list[dict[str, str]] = []
    used_chars = 0
    truncated = False

    for msg in reversed(history):
        cost = len(msg.content)
        if used_chars + cost > max_chars:
            truncated = True
            break
        kept.insert(0, {"role": msg.role, "content": msg.content})
        used_chars += cost

    if truncated:
        kept.insert(
            0,
            {
                "role": "system",
                "content": (
                    "[系统注意：由于上下文长度限制，早期对话记录已被截断。"
                    "以下仅保留最近的对话历史，请根据现有内容尽力理解用户意图。]"
                ),
            },
        )

    return kept


def _build_chat_request(
    query: str,
    context: list[str],
    llm: LLMConfig,
    *,
    stream: bool = False,
    history: list[ChatMessage] | None = None,
    response_format: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
    project_reasoning_bias_enabled: bool | None = None,
    project_reasoning_bias_surface: str = "chat",
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build provider-specific URL, headers, and payload."""
    provider_key = _provider_key(llm.provider)
    api_key = _resolve_api_key(llm.provider, llm.api_key)
    resolved_model = _resolve_model_name(llm.provider, llm.model, llm.base_url)
    system_text = _system_text_with_project_reasoning_bias(
        system_prompt=llm.system_prompt,
        context=context,
        project_id=project_id,
        enabled=project_reasoning_bias_enabled,
        surface=project_reasoning_bias_surface,
    )
    url = _build_chat_endpoint(llm.base_url, llm.provider)

    # Reserve ~40% of max_tokens for history; the rest for the current exchange.
    history_token_budget = max(0, int(llm.max_tokens * 0.4))
    history_messages = _compress_history(history or [], history_token_budget)

    key_optional_providers = {"ollama", "local llm"}
    if provider_key not in key_optional_providers and not api_key:
        raise ValueError(f"未配置可用的服务访问凭证: provider={llm.provider}")

    if provider_key == "claude":
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        # Claude uses separate `system` field; history goes into messages array
        claude_history = [
            {"role": m["role"], "content": m["content"]}
            for m in history_messages
            if m.get("role") != "system"
        ]
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [*claude_history, {"role": "user", "content": query}],
            "max_tokens": llm.max_tokens,
            "temperature": llm.temperature,
            "top_p": llm.top_p,
        }
        # Merge truncation note into system prompt when history was compressed
        system_parts = [system_text] if system_text else []
        for m in history_messages:
            if m.get("role") == "system":
                system_parts.append(m["content"])
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
        return url, headers, payload

    messages: list[dict[str, str]] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.extend(history_messages)
    messages.append({"role": "user", "content": query})
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": resolved_model,
        "messages": messages,
        "temperature": llm.temperature,
        "top_p": llm.top_p,
        "max_tokens": llm.max_tokens,
    }
    if llm.top_k:
        payload["extra_body"] = {"top_k": llm.top_k}
    if response_format:
        payload["response_format"] = response_format
    if tools:
        payload["tools"] = tools
    if stream:
        payload["stream"] = True
    return url, headers, payload


def _extract_provider_error_message(raw: str) -> str:
    """Parse provider error bodies into a stable user-facing string."""
    friendly = raw
    try:
        err_data = json.loads(raw)
        if isinstance(err_data, dict):
            err_obj = err_data.get("error", err_data)
            if isinstance(err_obj, dict):
                msg = err_obj.get("message", "")
                code = err_obj.get("code", err_obj.get("type", ""))
                if msg:
                    friendly = msg
                    if code:
                        friendly = f"{msg} ({code})"
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return friendly


def _provider_status_error_message(status_code: int, raw: str) -> str:
    """Map upstream HTTP failures to safe, actionable chat error copy."""

    if status_code in {401, 403}:
        return "LLM 访问凭证无效或未授权，请在设置中检查 API Key。"
    if status_code == 404:
        return "LLM 模型或服务地址不可用，请检查供应商、Base URL 和模型名称是否匹配。"
    if status_code == 429:
        return "LLM 上游限流，请稍后重试或切换可用供应商。"
    if status_code in {408, 504, 524}:
        return "上游 LLM 响应超时，请稍后重试或在设置中切换服务地址。"
    if status_code >= 500:
        return f"上游 LLM 服务异常（{status_code}），请稍后重试或切换可用供应商。"

    friendly = _extract_provider_error_message(raw).strip()
    if friendly and len(friendly) <= 160 and "http" not in friendly.lower() and "://" not in friendly:
        return friendly
    return f"上游 LLM 返回非预期状态（{status_code}），请检查当前模型配置。"


def _provider_request_error_message(exc: httpx.RequestError) -> str:
    """Map transport failures to safe chat error copy without leaking URLs."""

    if isinstance(exc, httpx.TimeoutException):
        return "上游 LLM 响应超时，请稍后重试或在设置中切换服务地址。"
    return "无法连接上游 LLM，请检查网络、Base URL 或切换可用供应商。"


def _extract_chat_response(
    data: dict[str, Any],
    provider: str,
    fallback_model: str,
    *,
    tool_calls_present: bool = False,
) -> tuple[str, dict[str, Any] | None, str]:
    """Extract answer text from provider-specific response payloads.

    When ``tool_calls_present=True`` (caller already detected tool calls),
    a missing/null text body returns an empty string instead of raising.
    This supports two legitimate "model chose to call a tool first" shapes:

    - Claude: ``content`` block list contains only ``tool_use`` entries
      and no ``text`` block.
    - OpenAI-compatible: ``choices[0].message.content == None`` with a
      ``tool_calls`` list on the same message.

    When ``tool_calls_present=False`` and text is missing/null, this
    still raises ``KeyError("content")`` — that's a genuinely malformed
    response and must surface as an error rather than a silent ``"None"``
    string in the user-visible answer.
    """
    if _provider_key(provider) == "claude":
        content_blocks = data.get("content", []) if isinstance(data, dict) else []
        text_parts = [
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        usage = data.get("usage") if isinstance(data, dict) else None
        model_used = (
            data.get("model", fallback_model)
            if isinstance(data, dict) else fallback_model
        )
        if not text_parts:
            if tool_calls_present:
                # tool_use-only response is legitimate; surface empty answer.
                return "", usage, model_used
            raise KeyError("content")
        return "".join(text_parts), usage, model_used

    # OpenAI-compatible
    raw = data["choices"][0]["message"]["content"]
    usage = data.get("usage")
    model_used = data.get("model", fallback_model)

    if raw is None:
        if tool_calls_present:
            # content=null + tool_calls is the standard tool-only shape.
            return "", usage, model_used
        # content=null without tool_calls is malformed; never return "None".
        raise KeyError("content")

    if isinstance(raw, list):
        text_parts = [
            part.get("text", "")
            for part in raw
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        ]
        return "".join(text_parts), usage, model_used

    return str(raw), usage, model_used


def _extract_tool_calls(data: dict[str, Any], provider: str) -> list[dict[str, Any]] | None:
    """Extract tool_calls from LLM response (OpenAI-compatible or Claude)."""
    if _provider_key(provider) == "claude":
        content_blocks = data.get("content", []) if isinstance(data, dict) else []
        tool_blocks = [
            {
                "id": block.get("id", ""),
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {})),
                },
                "raw": block,
            }
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        return tool_blocks if tool_blocks else None

    # OpenAI-compatible
    message = data.get("choices", [{}])[0].get("message", {})
    tool_calls = message.get("tool_calls")
    return tool_calls if tool_calls else None


def _log_chat_telemetry(
    *,
    model: str | None,
    task: str,
    started_at: float,
    usage: dict[str, Any] | None = None,
    response: Any = None,
    status: str = "ok",
) -> None:
    try:
        usage_row = usage or usage_from_response(response)
        log_llm_call(
            model=model,
            task=task,
            prompt_tokens=int(usage_row.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_row.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - started_at) * 1000,
            status=status,
            cache_status="miss",
            decision="invoke",
        )
    except Exception:
        pass


async def _post_chat_with_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    telemetry_model: str,
    started_at: float,
) -> dict[str, Any]:
    """POST a fully-built chat payload with bounded exponential backoff.

    Extracted from the chat_ask inline retry loop so the MCP tool-use
    runner can re-issue rounds without duplicating the retry policy.
    """
    timeout_s = float(os.getenv("LLM_HTTP_TIMEOUT", "180"))
    max_retries = max(0, int(os.getenv("LLM_HTTP_RETRIES", "2")))
    backoff_base = float(os.getenv("LLM_HTTP_BACKOFF_BASE", "1.5"))
    retryable_statuses = {408, 409, 425, 429, 500, 502, 503, 504, 529}
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status_code = exc.response.status_code if exc.response else 0
            raw = exc.response.text[:500] if exc.response else str(exc)
            lowered = raw.lower()
            anthropic_transient = (
                "overloaded_error" in lowered or "\"type\":\"api_error\"" in lowered
            )
            if attempt < max_retries and (status_code in retryable_statuses or anthropic_transient):
                sleep_s = backoff_base * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "LLM API %s (attempt %d/%d), retry in %.2fs: %s",
                    status_code, attempt + 1, max_retries + 1, sleep_s, raw[:200],
                )
                await asyncio.sleep(sleep_s)
                continue
            _log_chat_telemetry(model=telemetry_model, task="chat", started_at=started_at, status="error")
            logger.error("LLM API error: %s", raw)
            friendly = _provider_status_error_message(status_code, raw)
            raise HTTPException(status_code=502, detail=friendly) from exc
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < max_retries:
                sleep_s = backoff_base * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "LLM connection error (attempt %d/%d), retry in %.2fs: %s",
                    attempt + 1, max_retries + 1, sleep_s, exc,
                )
                await asyncio.sleep(sleep_s)
                continue
            _log_chat_telemetry(model=telemetry_model, task="chat", started_at=started_at, status="error")
            logger.error("LLM connection error: %s", exc)
            raise HTTPException(status_code=502, detail=_provider_request_error_message(exc)) from exc
    _log_chat_telemetry(model=telemetry_model, task="chat", started_at=started_at, status="error")
    raise HTTPException(status_code=502, detail=f"LLM 调用失败: {last_exc}")


def _apply_chat_ask_deprecation_headers(response: Response) -> None:
    for key, value in _CHAT_ASK_DEPRECATION_HEADERS.items():
        response.headers[key] = value


@router.post("/ask", response_model=ChatResponse, deprecated=True)
async def chat_ask_endpoint(req: ChatRequest, response: Response) -> ChatResponse:
    """Deprecated HTTP compatibility endpoint for legacy chat clients."""
    _apply_chat_ask_deprecation_headers(response)
    return await chat_ask(req)


async def chat_ask(req: ChatRequest) -> ChatResponse:
    """Send user query + context to configured LLM and return the answer."""
    resolved_llm = _resolve_chat_llm(req.llm)
    try:
        llm = _resolve_request_llm_config(resolved_llm, task="chat", sampling=req.sampling)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    llm = _apply_ai_cost_profile_to_llm(llm, req.ai_cost_profile)
    with use_cost_profile(req.ai_cost_profile):
        try:
            _validate_outbound_llm_base_url(llm.base_url, llm.provider)
            url, headers, payload = _build_chat_request(
                req.query,
                req.context,
                llm,
                history=req.history,
                tools=req.tools,
                project_id=req.project_id,
                project_reasoning_bias_enabled=req.project_reasoning_bias_enabled,
                project_reasoning_bias_surface="chat",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        telemetry_model = str(payload.get("model", llm.model))
        started_at = time.perf_counter()

        # ---- Optional MCP tool-use loop ----------------------------------
        mcp_run_dump: dict[str, Any] | None = None
        if req.mcp_server_ids is not None and chat_mcp_integration.is_mcp_tools_enabled():
            try:
                servers, snapshot = await chat_mcp_integration.collect_enabled_servers_with_catalog(
                    req.mcp_server_ids
                )
            except chat_mcp_integration.McpRequestValidationError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            async def _post_fn(p: dict[str, Any]) -> dict[str, Any]:
                return await _post_chat_with_retry(
                    url=url,
                    headers=headers,
                    payload=p,
                    telemetry_model=telemetry_model,
                    started_at=started_at,
                )

            initial_messages = list(payload.get("messages") or [])
            chat_call = chat_mcp_integration.make_chat_call(
                base_payload=payload,
                provider_key=_provider_key(llm.provider),
                post_fn=_post_fn,
            )
            runner = chat_mcp_integration.make_runner(
                servers=servers,
                catalog_snapshot=snapshot,
                allow_high_risk_tools=req.mcp_allow_high_risk_tools,
            )
            run_result = await runner.run(
                provider=llm.provider,
                initial_messages=initial_messages,
                chat_call=chat_call,
            )
            data = run_result.final_response
            mcp_run_dump = chat_mcp_integration.transcript_to_dump(run_result)
        else:
            data = await _post_chat_with_retry(
                url=url,
                headers=headers,
                payload=payload,
                telemetry_model=telemetry_model,
                started_at=started_at,
            )

    try:
        # Extract tool_calls first so the parser can tolerate tool-use-only
        # responses without returning the literal string "None".
        tool_calls = _extract_tool_calls(data, llm.provider)
        answer, usage, model_used = _extract_chat_response(
            data, llm.provider, llm.model,
            tool_calls_present=tool_calls is not None,
        )
    except (KeyError, IndexError) as exc:
        _log_chat_telemetry(model=telemetry_model, task="chat", started_at=started_at, response=data, status="error")
        logger.error("Unexpected LLM response format: %s", data)
        raise HTTPException(status_code=502, detail=f"LLM 返回格式异常: {exc}") from exc

    _log_chat_telemetry(model=model_used or telemetry_model, task="chat", started_at=started_at, usage=usage, status="ok")

    analysis_chain = await _maybe_build_analysis_chain(req=req, answer=answer)

    return ChatResponse(
        answer=answer,
        model=model_used,
        usage=usage,
        sampling_params={
            "temperature": llm.temperature,
            "top_p": llm.top_p,
            "top_k": llm.top_k,
            "max_tokens": llm.max_tokens
        },
        tool_calls=tool_calls,
        mcp_run=mcp_run_dump,
        analysis_chain=analysis_chain,
    )


async def _maybe_build_analysis_chain(
    *, req: "ChatRequest", answer: str
) -> AnalysisChainPayload | None:
    """ACR-020 ~ ACR-024: optionally attach a structured 6-field reasoning chain.

    Returns None when ``analysis_chain_rag`` feature flag is off, so default
    callers see byte-identical behavior. When ``analysis_chain_rag`` is on,
    the deterministic builder is used (no extra LLM call). When BOTH
    ``analysis_chain_rag`` AND ``analysis_chain_rag_llm`` are on (B5,
    0.1.8.2), an async LLM sub-call renders the full 6-field chain via the
    IRAC / FinCoT prompt template; any failure transparently falls back to
    the deterministic chain so the user's chat response is never blocked.
    """
    try:
        from feature_flags import is_enabled
    except ImportError:
        return None
    if not is_enabled("analysis_chain_rag"):
        return None
    try:
        from analysis_chain_rag_builder import build_analysis_chain_async
    except ImportError:
        return None

    evidence_snippets = list(req.context or [])
    use_llm = is_enabled("analysis_chain_rag_llm")

    # B5 LLM path: spin up a minimal sub-chat to render the structured chain.
    # The callable closure deliberately strips MCP tools and history so the
    # sub-call is a pure single-turn render and cannot recursively trigger
    # tool use / further LLM calls. Failures inside build_with_llm_async are
    # caught and silently degrade to the deterministic payload.
    async def _chain_llm_invoke(prompt: str) -> str:
        sub_req = ChatRequest(
            query=prompt,
            context=[],
            history=[],
            llm=req.llm,
            sampling=req.sampling,
            project_id=req.project_id,
            project_reasoning_bias_enabled=False,
        )
        sub_resp = await chat_ask(sub_req)
        return sub_resp.answer

    try:
        return await build_analysis_chain_async(
            query=req.query,
            answer=answer,
            evidence_snippets=evidence_snippets,
            mode="llm" if use_llm else "deterministic",
            llm_invoke=_chain_llm_invoke if use_llm else None,
            frame="irac",
            project_reasoning_bias=_resolve_project_reasoning_bias_for_surface(
                project_id=req.project_id,
                enabled=req.project_reasoning_bias_enabled,
                surface="analysis_chain_rag",
            ),
        )
    except Exception:  # noqa: BLE001 — final safety net
        logger.exception("analysis_chain_rag builder crashed; returning None")
        return None


# ---------------------------------------------------------------------------
# SSE Streaming Chat Endpoint (learned from textgen-4.4 / openhanako)
# ---------------------------------------------------------------------------

class ChatStreamRequest(BaseModel):
    """Request body for streaming chat — same fields as ChatRequest."""

    query: str = Field(..., min_length=1, max_length=MAX_CHAT_QUERY_LENGTH)
    context: list[str] = Field(default_factory=list, description="文档上下文片段")
    history: list[ChatMessage] = Field(default_factory=list, description="历史对话记录")
    llm: LLMConfig | None = Field(default=None, description="LLM config (optional; backend resolves if absent)")
    sampling: dict[str, float | int] | None = Field(default=None, description="Per-task sampling overrides")
    ai_cost_profile: str | None = Field(default=None, description="balanced | aggressive | quality")
    project_id: str | None = Field(default=None, max_length=128, description="Project id used to resolve project reasoning bias")
    project_reasoning_bias_enabled: bool | None = Field(
        default=None,
        description="Per-request override. False disables project reasoning bias injection.",
    )
    stream: bool = Field(True, description="启用流式输出")


@router.post("/stream")
async def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
    """Stream LLM response via Server-Sent Events (SSE).

    Each event is a JSON line:
      data: {"event":"text_delta","delta":"..."}
      data: {"event":"usage","usage":{...},"model":"..."}
      data: {"event":"done"}
      data: {"event":"error","error":"..."}
    """
    resolved_llm = _resolve_chat_llm(req.llm)
    try:
        llm = _resolve_request_llm_config(resolved_llm, task="chat", sampling=req.sampling)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    llm = _apply_ai_cost_profile_to_llm(llm, req.ai_cost_profile)
    with use_cost_profile(req.ai_cost_profile):
        try:
            _validate_outbound_llm_base_url(llm.base_url, llm.provider)
            url, headers, payload = _build_chat_request(
                req.query,
                req.context,
                llm,
                stream=True,
                history=req.history,
                project_id=req.project_id,
                project_reasoning_bias_enabled=req.project_reasoning_bias_enabled,
                project_reasoning_bias_surface="chat",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider_key = _provider_key(llm.provider)
    telemetry_model = str(payload.get("model", llm.model))

    # Third-party Claude proxies frequently buffer the full response and time out at ~120s.
    # Bump default to 180s and allow override via LLM_HTTP_STREAM_TIMEOUT.
    # Mid-stream retry is intentionally NOT done (would replay tokens already sent to the client).
    stream_timeout_s = float(os.getenv("LLM_HTTP_STREAM_TIMEOUT", "180"))

    async def event_generator():
        started_at = time.perf_counter()
        usage: dict[str, Any] | None = None
        model_used = telemetry_model
        status = "ok"
        try:
            async with httpx.AsyncClient(timeout=stream_timeout_s, follow_redirects=False) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        status = "error"
                        body = await resp.aread()
                        body_preview = body.decode("utf-8", errors="replace")[:500]
                        err_msg = _provider_status_error_message(resp.status_code, body_preview)
                        # Annotate Anthropic transient errors so the client can surface a clearer message.
                        if "overloaded_error" in body_preview.lower():
                            err_msg = f"{err_msg} (上游过载，请稍后重试)"
                        yield f"data: {json.dumps({'event': 'error', 'error': err_msg})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("event:"):
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                yield f"data: {json.dumps({'event': 'done'})}\n\n"
                                break
                            try:
                                chunk = json.loads(data_str)
                                if provider_key == "claude":
                                    chunk_type = chunk.get("type")
                                    if chunk_type == "content_block_delta":
                                        delta = chunk.get("delta", {})
                                        content = delta.get("text", "")
                                        if content:
                                            yield f"data: {json.dumps({'event': 'text_delta', 'delta': content})}\n\n"
                                    elif chunk_type == "message_delta":
                                        chunk_usage = chunk.get("usage")
                                        if chunk_usage:
                                            usage = chunk_usage
                                            yield f"data: {json.dumps({'event': 'usage', 'usage': chunk_usage, 'model': model_used})}\n\n"
                                    elif chunk_type == "message_stop":
                                        yield f"data: {json.dumps({'event': 'done'})}\n\n"
                                        break
                                    elif chunk_type == "error":
                                        status = "error"
                                        err_obj = chunk.get('error', {})
                                        err_msg = err_obj.get('message') or json.dumps(chunk, ensure_ascii=False)
                                        yield f"data: {json.dumps({'event': 'error', 'error': err_msg})}\n\n"
                                        return
                                    continue

                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'event': 'text_delta', 'delta': content})}\n\n"

                                # Send usage info if available
                                chunk_usage = chunk.get("usage")
                                if chunk_usage:
                                    usage = chunk_usage
                                    model_used = chunk.get("model", model_used)
                                    yield f"data: {json.dumps({'event': 'usage', 'usage': chunk_usage, 'model': model_used})}\n\n"
                            except json.JSONDecodeError:
                                continue
        except httpx.RequestError as exc:
            status = "error"
            logger.error("SSE stream connection error: %s", exc)
            yield f"data: {json.dumps({'event': 'error', 'error': _provider_request_error_message(exc)})}\n\n"
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            status = "error"
            logger.exception("SSE stream unexpected error")
            yield f"data: {json.dumps({'event': 'error', 'error': str(exc)})}\n\n"
        finally:
            _log_chat_telemetry(
                model=model_used,
                task="chat",
                started_at=started_at,
                usage=usage,
                status=status,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



# Per S6 (`docs/plans/active/2026-05-13-settings-unified-api-config-plan.md`):
# /chat/providers and /chat/models are kept as compatibility endpoints —
# old clients (Settings catalog UI from before the S5 backend-config move,
# or any external integration that grew on top of this surface) keep
# working — but new clients should use `/api/chat/config` +
# Settings-driven backend resolution. The RFC 9745 `Deprecation` header
# signals this. No `Sunset` header (RFC 8594) until a removal date is set.
_PROVIDERS_DEPRECATION_HEADERS = {
    # RFC 9745 §2: value is an HTTP-date marking when the deprecation
    # took effect. 2026-05-15 = the S6 ship date.
    "Deprecation": "Fri, 15 May 2026 00:00:00 GMT",
    # RFC 9745 §3.2: optional Link header to canonical replacement docs.
    "Link": '</api/chat/config>; rel="successor-version"',
}


@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers(response: Response) -> list[ProviderInfo]:
    """List all supported LLM providers with their models.

    **Deprecated** (S6, 2026-05-15) — kept for backward compatibility.
    Prefer `/api/chat/config` + Settings-driven backend resolution for
    new clients. See `docs/plans/active/2026-05-13-settings-unified-api-config-plan.md` §S6.
    """
    for k, v in _PROVIDERS_DEPRECATION_HEADERS.items():
        response.headers[k] = v
    return MODEL_CATALOG


@router.get("/models", response_model=list[ModelInfo])
async def list_supported_models(
    response: Response,
    provider: str | None = None,
) -> list[ModelInfo]:
    """List known LLM model options. Optionally filter by provider.

    **Deprecated** (S6, 2026-05-15) — kept for backward compatibility.
    Prefer `/api/chat/models/discover` for runtime discovery.
    """
    for k, v in _PROVIDERS_DEPRECATION_HEADERS.items():
        response.headers[k] = v
    if provider:
        return [m for p in MODEL_CATALOG for m in p.models if p.provider == provider]
    return SUPPORTED_PROVIDERS


@router.get("/models/discover")
async def discover_models(
    base_url: str = Query(..., description="Base URL of LLM service"),
    api_key: str = Query("", description="Access credential (optional for local services)"),
) -> dict[str, Any]:
    """Auto-discover models from an OpenAI-compatible endpoint.

    Tries GET /v1/models to discover available models.
    Works with Ollama, vLLM, LM Studio, LocalAI, third-party aggregators
    (newapi, OneAPI, OpenRouter, SiliconFlow, etc.).

    URL-derivation rules (matching cc-switch's build_models_url):
      - "https://api.x.com" -> "https://api.x.com/v1/models"
      - "https://api.x.com/v1" -> "https://api.x.com/v1/models"
      - "https://api.x.com/v1/chat/completions" -> "https://api.x.com/v1/models"
      - trailing slash tolerated
    """
    try:
        _validate_outbound_llm_base_url(base_url, "Local LLM")
        url = _build_models_discovery_endpoint(base_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "models": []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Endpoint rejected: {exc}", "models": []}

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models_list = data.get("data", []) if isinstance(data, dict) else []
        discovered = [
            ModelInfo(
                id=m.get("id", ""),
                name=m.get("id", ""),
                provider="discovered",
                context_window=0,
                description=str(m.get("owned_by") or "自动发现的模型"),
            )
            for m in models_list
            if isinstance(m, dict) and m.get("id")
        ]
        discovered.sort(key=lambda m: m.id)
        return {"ok": True, "models": [m.model_dump() for m in discovered], "endpoint": url}
    except httpx.HTTPStatusError as exc:
        # Surface upstream response body so the UI can show *why* the test
        # failed (invalid credential, model not found, quota exhausted, etc.).
        body_snippet = ""
        try:
            body_snippet = exc.response.text[:400] if exc.response is not None else ""
        except Exception:  # noqa: BLE001
            body_snippet = ""
        status_code = exc.response.status_code if exc.response is not None else 0
        return {
            "ok": False,
            "error": f"HTTP {status_code}" + (f" · {body_snippet}" if body_snippet else ""),
            "status_code": status_code,
            "body": body_snippet,
            "models": [],
            "endpoint": url,
        }
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "error": f"连接失败: {exc.__class__.__name__}: {exc}",
            "models": [],
            "endpoint": url,
        }

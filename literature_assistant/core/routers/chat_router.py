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

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai_cost_profile import normalize_cost_profile, use_cost_profile
from llm_defaults import resolve_llm_params
from llm_cost_logger import log_llm_call
from llm_pricing import usage_from_response
from sampling_storage import load_user_sampling

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


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


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    context: list[str] = Field(default_factory=list, description="Document text chunks as context")
    history: list[ChatMessage] = Field(default_factory=list, description="Previous conversation turns")
    llm: LLMConfig
    sampling: dict[str, float | int] | None = Field(default=None, description="Per-task sampling overrides")
    ai_cost_profile: str | None = Field(default=None, description="balanced | aggressive | quality")
    tools: list[dict[str, Any]] | None = Field(default=None, description="Tool/function definitions for skill calling")


class ChatResponse(BaseModel):
    answer: str
    model: str
    usage: dict[str, Any] | None = None
    sampling_params: dict[str, Any] | None = Field(default=None, description="Actual sampling params used")
    tool_calls: list[dict[str, Any]] | None = Field(default=None, description="Tool calls from LLM (for skill execution)")


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
    """Resolve API key with server-side env fallback.

    Priority:
    1) Provider-specific env key (safer for deployment)
    2) Provided key from request payload
    """
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

    return (provided_key or "").strip()


def _build_chat_endpoint(base_url: str, provider: str) -> str:
    """Normalize provider base URL to the provider-specific chat endpoint."""
    base = base_url.strip().rstrip("/")
    provider_key = _provider_key(provider)

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
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build provider-specific URL, headers, and payload."""
    provider_key = _provider_key(llm.provider)
    api_key = _resolve_api_key(llm.provider, llm.api_key)
    resolved_model = _resolve_model_name(llm.provider, llm.model, llm.base_url)
    system_text = _build_system_text(llm.system_prompt, context)
    url = _build_chat_endpoint(llm.base_url, llm.provider)

    # Reserve ~40% of max_tokens for history; the rest for the current exchange.
    history_token_budget = max(0, int(llm.max_tokens * 0.4))
    history_messages = _compress_history(history or [], history_token_budget)

    key_optional_providers = {"ollama", "local llm"}
    if provider_key not in key_optional_providers and not api_key:
        raise ValueError(f"未配置可用的 API Key: provider={llm.provider}")

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
    string in the user-visible answer (Phase P0 hotfix).
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


@router.post("/ask", response_model=ChatResponse)
async def chat_ask(req: ChatRequest) -> ChatResponse:
    """Send user query + context to configured LLM and return the answer."""
    try:
        llm = _resolve_request_llm_config(req.llm, task="chat", sampling=req.sampling)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    llm = _apply_ai_cost_profile_to_llm(llm, req.ai_cost_profile)
    with use_cost_profile(req.ai_cost_profile):
        try:
            url, headers, payload = _build_chat_request(req.query, req.context, llm, history=req.history, tools=req.tools)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        telemetry_model = str(payload.get("model", llm.model))
        started_at = time.perf_counter()
        # Third-party Claude proxies and other LLM gateways frequently return
        # transient 408/429/5xx or drop the connection mid-request. We retry
        # idempotent POSTs with bounded exponential backoff + jitter.
        # Knobs (env): LLM_HTTP_TIMEOUT (s), LLM_HTTP_RETRIES, LLM_HTTP_BACKOFF_BASE (s).
        timeout_s = float(os.getenv("LLM_HTTP_TIMEOUT", "180"))
        max_retries = max(0, int(os.getenv("LLM_HTTP_RETRIES", "2")))
        backoff_base = float(os.getenv("LLM_HTTP_BACKOFF_BASE", "1.5"))
        retryable_statuses = {408, 409, 425, 429, 500, 502, 503, 504, 529}
        last_exc: Exception | None = None
        data = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code if exc.response else 0
                raw = exc.response.text[:500] if exc.response else str(exc)
                lowered = raw.lower()
                # Anthropic-specific transient error names: overloaded_error, api_error.
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
                friendly = _extract_provider_error_message(raw)
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
                raise HTTPException(status_code=502, detail=f"无法连接 LLM 服务: {exc}") from exc
        if data is None:
            # Defensive: should not reach here because the loop either breaks or raises.
            _log_chat_telemetry(model=telemetry_model, task="chat", started_at=started_at, status="error")
            raise HTTPException(status_code=502, detail=f"LLM 调用失败: {last_exc}")

    try:
        # Phase P0 hotfix: extract tool_calls FIRST so the parser can
        # tolerate tool_use-only / content=null+tool_calls responses
        # without raising or returning the literal string "None".
        tool_calls = _extract_tool_calls(data, req.llm.provider)
        answer, usage, model_used = _extract_chat_response(
            data, req.llm.provider, req.llm.model,
            tool_calls_present=tool_calls is not None,
        )
    except (KeyError, IndexError) as exc:
        _log_chat_telemetry(model=telemetry_model, task="chat", started_at=started_at, response=data, status="error")
        logger.error("Unexpected LLM response format: %s", data)
        raise HTTPException(status_code=502, detail=f"LLM 返回格式异常: {exc}") from exc

    _log_chat_telemetry(model=model_used or telemetry_model, task="chat", started_at=started_at, usage=usage, status="ok")
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
    )


# ---------------------------------------------------------------------------
# SSE Streaming Chat Endpoint (learned from textgen-4.4 / openhanako)
# ---------------------------------------------------------------------------

class ChatStreamRequest(BaseModel):
    """Request body for streaming chat — same fields as ChatRequest."""

    query: str = Field(..., min_length=1, max_length=5000)
    context: list[str] = Field(default_factory=list, description="文档上下文片段")
    history: list[ChatMessage] = Field(default_factory=list, description="历史对话记录")
    llm: LLMConfig
    sampling: dict[str, float | int] | None = Field(default=None, description="Per-task sampling overrides")
    ai_cost_profile: str | None = Field(default=None, description="balanced | aggressive | quality")
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
    try:
        llm = _resolve_request_llm_config(req.llm, task="chat", sampling=req.sampling)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    llm = _apply_ai_cost_profile_to_llm(llm, req.ai_cost_profile)
    with use_cost_profile(req.ai_cost_profile):
        try:
            url, headers, payload = _build_chat_request(req.query, req.context, llm, stream=True, history=req.history)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider_key = _provider_key(req.llm.provider)
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
            async with httpx.AsyncClient(timeout=stream_timeout_s) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        status = "error"
                        body = await resp.aread()
                        body_preview = body.decode("utf-8", errors="replace")[:500]
                        err_msg = _extract_provider_error_message(body_preview)
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
            yield f"data: {json.dumps({'event': 'error', 'error': f'无法连接 LLM 服务: {exc}'})}\n\n"
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


# ---------------------------------------------------------------------------
# Chat History & Model Info (learned from openhanako sessions.js / models.js)
# ---------------------------------------------------------------------------

class ModelInfo(BaseModel):
    """LLM model information."""

    id: str
    name: str
    provider: str
    default_base_url: str = ""
    context_window: int = 0
    description: str = ""


class ProviderInfo(BaseModel):
    """Provider with grouped models."""

    provider: str
    display_name: str
    default_base_url: str
    api_type: str = "openai-compatible"
    auth_tip: str = ""
    models: list[ModelInfo]


# Comprehensive model catalog — learned from openhanako known-models + quivr LLMModelConfig
MODEL_CATALOG: list[ProviderInfo] = [
    ProviderInfo(
        provider="DeepSeek",
        display_name="DeepSeek",
        default_base_url="https://api.deepseek.com",
        auth_tip="使用 DeepSeek 开放平台的 API Key (sk-...)",
        models=[
            ModelInfo(id="deepseek-chat", name="DeepSeek-V3", provider="DeepSeek", default_base_url="https://api.deepseek.com", context_window=64000, description="通用对话模型，性价比高"),
            ModelInfo(id="deepseek-reasoner", name="DeepSeek-R1", provider="DeepSeek", default_base_url="https://api.deepseek.com", context_window=64000, description="推理增强模型，适合复杂分析"),
        ],
    ),
    ProviderInfo(
        provider="OpenAI",
        display_name="OpenAI",
        default_base_url="https://api.openai.com",
        auth_tip="使用 OpenAI 平台的 API Key (sk-...)",
        models=[
            ModelInfo(id="gpt-4o", name="GPT-4o", provider="OpenAI", default_base_url="https://api.openai.com", context_window=128000, description="旗舰多模态模型"),
            ModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", provider="OpenAI", default_base_url="https://api.openai.com", context_window=128000, description="轻量快速，适合日常任务"),
            ModelInfo(id="gpt-4.1", name="GPT-4.1", provider="OpenAI", default_base_url="https://api.openai.com", context_window=1047576, description="最新旗舰模型，超长上下文"),
            ModelInfo(id="gpt-4.1-mini", name="GPT-4.1 Mini", provider="OpenAI", default_base_url="https://api.openai.com", context_window=1047576, description="轻量版旗舰，兼顾速度与能力"),
            ModelInfo(id="gpt-4.1-nano", name="GPT-4.1 Nano", provider="OpenAI", default_base_url="https://api.openai.com", context_window=1047576, description="极速低成本选项"),
            ModelInfo(id="o3-mini", name="o3-mini", provider="OpenAI", default_base_url="https://api.openai.com", context_window=200000, description="推理模型，适合数学/代码分析"),
        ],
    ),
    ProviderInfo(
        provider="Claude",
        display_name="Anthropic Claude",
        default_base_url="https://api.anthropic.com",
        api_type="anthropic",
        auth_tip="使用 Anthropic 的 API Key。注意：如使用 OpenAI 兼容代理（如 OpenRouter），请选择'OpenAI 兼容'",
        models=[
            ModelInfo(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", provider="Claude", default_base_url="https://api.anthropic.com", context_window=200000, description="编程与分析能力极强"),
            ModelInfo(id="claude-opus-4-20250514", name="Claude Opus 4", provider="Claude", default_base_url="https://api.anthropic.com", context_window=200000, description="最强模型，适合深度学术研究"),
            ModelInfo(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider="Claude", default_base_url="https://api.anthropic.com", context_window=200000, description="快速轻量，成本最低"),
        ],
    ),
    ProviderInfo(
        provider="Gemini",
        display_name="Google Gemini",
        default_base_url="https://generativelanguage.googleapis.com",
        auth_tip="使用 Google AI Studio 的 API Key",
        models=[
            ModelInfo(id="gemini-2.5-flash", name="Gemini 2.5 Flash", provider="Gemini", default_base_url="https://generativelanguage.googleapis.com", context_window=1048576, description="超长上下文，性价比极高"),
            ModelInfo(id="gemini-2.5-pro", name="Gemini 2.5 Pro", provider="Gemini", default_base_url="https://generativelanguage.googleapis.com", context_window=1048576, description="最强推理能力"),
            ModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", provider="Gemini", default_base_url="https://generativelanguage.googleapis.com", context_window=1048576, description="上一代快速模型"),
        ],
    ),
    ProviderInfo(
        provider="Qwen",
        display_name="通义千问（阿里云）",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode",
        auth_tip="使用阿里云 DashScope 的 API Key (sk-...)",
        models=[
            ModelInfo(id="qwen-plus", name="Qwen Plus", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=131072, description="通用高性能模型"),
            ModelInfo(id="qwen-turbo", name="Qwen Turbo", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=131072, description="快速低成本"),
            ModelInfo(id="qwen-max", name="Qwen Max", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=32768, description="最强旗舰模型"),
            ModelInfo(id="qwen-long", name="Qwen Long", provider="Qwen", default_base_url="https://dashscope.aliyuncs.com/compatible-mode", context_window=10000000, description="千万字超长文档处理"),
        ],
    ),
    ProviderInfo(
        provider="Zhipu",
        display_name="智谱 GLM",
        default_base_url="https://open.bigmodel.cn/api/paas",
        auth_tip="使用智谱 AI 开放平台的 API Key",
        models=[
            ModelInfo(id="glm-4-plus", name="GLM-4 Plus", provider="Zhipu", default_base_url="https://open.bigmodel.cn/api/paas", context_window=128000, description="旗舰对话模型"),
            ModelInfo(id="glm-4-flash", name="GLM-4 Flash", provider="Zhipu", default_base_url="https://open.bigmodel.cn/api/paas", context_window=128000, description="免费快速模型"),
        ],
    ),
    ProviderInfo(
        provider="Doubao",
        display_name="豆包（字节跳动）",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        auth_tip="使用火山引擎 ARK 平台的 API Key。模型 ID 可填接入点 ID (ep-xxx) 或官方模型名称（如 doubao-pro-32k）。Base URL 填写 https://ark.cn-beijing.volces.com/api/v3 即可，无需加 /responses 后缀。",
        models=[
            ModelInfo(id="ep-xxx", name="豆包接入点", provider="Doubao", default_base_url="https://ark.cn-beijing.volces.com/api/v3", context_window=128000, description="填入火山引擎控制台的接入点 ID (ep-xxxxxxxx)"),
            ModelInfo(id="doubao-pro-32k", name="豆包 Pro 32K", provider="Doubao", default_base_url="https://ark.cn-beijing.volces.com/api/v3", context_window=32000, description="豆包 Pro 旗舰对话模型"),
            ModelInfo(id="doubao-lite-32k", name="豆包 Lite 32K", provider="Doubao", default_base_url="https://ark.cn-beijing.volces.com/api/v3", context_window=32000, description="豆包 Lite 轻量对话模型"),
        ],
    ),
    ProviderInfo(
        provider="Moonshot",
        display_name="Kimi（月之暗面）",
        default_base_url="https://api.moonshot.cn",
        auth_tip="使用 Moonshot 平台的 API Key (sk-...)",
        models=[
            ModelInfo(id="moonshot-v1-auto", name="Kimi Auto", provider="Moonshot", default_base_url="https://api.moonshot.cn", context_window=128000, description="自动选择上下文长度"),
            ModelInfo(id="moonshot-v1-128k", name="Kimi 128K", provider="Moonshot", default_base_url="https://api.moonshot.cn", context_window=128000, description="超长上下文"),
        ],
    ),
    ProviderInfo(
        provider="SiliconFlow",
        display_name="SiliconFlow（硅基流动）",
        default_base_url="https://api.siliconflow.cn",
        auth_tip="聚合平台，支持多种开源模型，API Key 来自 SiliconFlow 控制台",
        models=[
            ModelInfo(id="deepseek-ai/DeepSeek-V3", name="DeepSeek-V3 (SiliconFlow)", provider="SiliconFlow", default_base_url="https://api.siliconflow.cn", context_window=64000, description="通过 SiliconFlow 调用 DeepSeek"),
            ModelInfo(id="deepseek-ai/DeepSeek-R1", name="DeepSeek-R1 (SiliconFlow)", provider="SiliconFlow", default_base_url="https://api.siliconflow.cn", context_window=64000, description="通过 SiliconFlow 调用 R1"),
            ModelInfo(id="Qwen/Qwen2.5-72B-Instruct", name="Qwen 2.5 72B (SiliconFlow)", provider="SiliconFlow", default_base_url="https://api.siliconflow.cn", context_window=32768, description="通过 SiliconFlow 调用千问"),
        ],
    ),
    ProviderInfo(
        provider="OpenRouter",
        display_name="OpenRouter（聚合代理）",
        default_base_url="https://openrouter.ai/api",
        auth_tip="一个 Key 访问所有主流模型，从 openrouter.ai 获取 API Key",
        models=[
            ModelInfo(id="deepseek/deepseek-chat-v3-0324", name="DeepSeek V3 (OpenRouter)", provider="OpenRouter", default_base_url="https://openrouter.ai/api", context_window=64000, description="通过 OpenRouter 代理"),
            ModelInfo(id="google/gemini-2.5-flash-preview", name="Gemini 2.5 Flash (OpenRouter)", provider="OpenRouter", default_base_url="https://openrouter.ai/api", context_window=1048576, description="通过 OpenRouter 代理"),
            ModelInfo(id="anthropic/claude-sonnet-4", name="Claude Sonnet 4 (OpenRouter)", provider="OpenRouter", default_base_url="https://openrouter.ai/api", context_window=200000, description="通过 OpenRouter 代理"),
        ],
    ),
    ProviderInfo(
        provider="Groq",
        display_name="Groq（超快推理）",
        default_base_url="https://api.groq.com/openai/v1",
        auth_tip="从 console.groq.com 获取免费 API Key，推理速度比一般云服务快 10-20x",
        models=[
            ModelInfo(id="llama-3.3-70b-versatile", name="Llama 3.3 70B", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=128000, description="Meta 最新旗舰开源模型，速度极快"),
            ModelInfo(id="llama-3.1-8b-instant", name="Llama 3.1 8B Instant", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=128000, description="极速轻量，适合高频对话"),
            ModelInfo(id="mixtral-8x7b-32768", name="Mixtral 8x7B", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=32768, description="Mistral 混合专家架构"),
            ModelInfo(id="gemma2-9b-it", name="Gemma 2 9B", provider="Groq", default_base_url="https://api.groq.com/openai/v1", context_window=8192, description="Google Gemma 2 开源模型"),
        ],
    ),
    ProviderInfo(
        provider="Mistral",
        display_name="Mistral AI（欧洲）",
        default_base_url="https://api.mistral.ai/v1",
        auth_tip="从 console.mistral.ai 获取 API Key，数据存储在欧洲，符合 GDPR",
        models=[
            ModelInfo(id="mistral-small-latest", name="Mistral Small", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=32768, description="轻量高效，性价比高"),
            ModelInfo(id="mistral-medium-latest", name="Mistral Medium", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=131072, description="均衡性能，超长上下文"),
            ModelInfo(id="mistral-large-latest", name="Mistral Large", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=131072, description="旗舰模型，适合复杂推理"),
            ModelInfo(id="codestral-latest", name="Codestral", provider="Mistral", default_base_url="https://api.mistral.ai/v1", context_window=32768, description="专为代码生成优化"),
        ],
    ),
    ProviderInfo(
        provider="Perplexity",
        display_name="Perplexity（联网搜索）",
        default_base_url="https://api.perplexity.ai",
        auth_tip="从 perplexity.ai/settings/api 获取 API Key，sonar 系列模型自带实时联网搜索",
        models=[
            ModelInfo(id="sonar", name="Sonar", provider="Perplexity", default_base_url="https://api.perplexity.ai", context_window=127072, description="联网搜索，回答实时信息"),
            ModelInfo(id="sonar-pro", name="Sonar Pro", provider="Perplexity", default_base_url="https://api.perplexity.ai", context_window=127072, description="高级联网搜索，更深入分析"),
            ModelInfo(id="sonar-reasoning", name="Sonar Reasoning", provider="Perplexity", default_base_url="https://api.perplexity.ai", context_window=127072, description="联网搜索 + 推理增强"),
        ],
    ),
    ProviderInfo(
        provider="MiniMax",
        display_name="MiniMax（海螺 AI）",
        default_base_url="https://api.minimax.chat/v1",
        auth_tip="从 platform.minimaxi.com 获取 API Key。使用新版 ChatCompletion V2（OpenAI 兼容格式）",
        models=[
            ModelInfo(id="abab6.5s-chat", name="ABAB 6.5S", provider="MiniMax", default_base_url="https://api.minimax.chat/v1", context_window=245760, description="MiniMax 旗舰超长上下文模型"),
            ModelInfo(id="abab5.5s-chat", name="ABAB 5.5S", provider="MiniMax", default_base_url="https://api.minimax.chat/v1", context_window=8192, description="轻量快速，适合高频对话"),
        ],
    ),
    ProviderInfo(
        provider="Ollama",
        display_name="Ollama（本地部署）",
        default_base_url="http://localhost:11434",
        api_type="openai-compatible",
        auth_tip="无需 API Key，确保 Ollama 已启动（ollama serve）",
        models=[
            ModelInfo(id="auto", name="自动检测已安装模型", provider="Ollama", default_base_url="http://localhost:11434", context_window=0, description="将自动从本地 Ollama 拉取模型列表"),
        ],
    ),
    ProviderInfo(
        provider="Local LLM",
        display_name="自定义 OpenAI 兼容服务",
        default_base_url="http://localhost:8080",
        api_type="openai-compatible",
        auth_tip="填入任何 OpenAI 兼容 API 的地址和 Key。系统会根据服务器地址自动识别接口格式（如火山引擎、DeepSeek、OpenAI 等），无需手动切换提供商。",
        models=[
            ModelInfo(id="auto", name="自动识别", provider="Local LLM", default_base_url="http://localhost:8080", context_window=0, description="系统将根据服务器地址自动推断接口格式与默认模型。若识别失败，请手动填写模型 ID。"),
        ],
    ),
]

# Flat list for backward compat
SUPPORTED_PROVIDERS = [m for p in MODEL_CATALOG for m in p.models]


@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers() -> list[ProviderInfo]:
    """List all supported LLM providers with their models."""
    return MODEL_CATALOG


@router.get("/models", response_model=list[ModelInfo])
async def list_supported_models(provider: str | None = None) -> list[ModelInfo]:
    """List known LLM model options. Optionally filter by provider."""
    if provider:
        return [m for p in MODEL_CATALOG for m in p.models if p.provider == provider]
    return SUPPORTED_PROVIDERS


@router.get("/models/discover")
async def discover_models(
    base_url: str = Query(..., description="Base URL of LLM service"),
    api_key: str = Query("", description="API key (optional for local)"),
) -> dict[str, Any]:
    """Auto-discover models from an OpenAI-compatible endpoint.
    
    Tries GET /v1/models to discover available models.
    Works with Ollama, vLLM, LM Studio, LocalAI, etc.
    """
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    url = f"{url}/models"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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
                description="自动发现的模型",
            )
            for m in models_list
            if isinstance(m, dict) and m.get("id")
        ]
        return {"ok": True, "models": [m.model_dump() for m in discovered]}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "error": f"HTTP {exc.response.status_code}", "models": []}
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"连接失败: {exc}", "models": []}

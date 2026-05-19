from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from hashlib import sha256
from typing import Any

import httpx

from ai_cost_profile import is_aggressive_cost_save
from model_call_gateway import gated_call
from runtime_env import resolve_llm_config

logger = logging.getLogger(__name__)

DEFAULT_ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
DEFAULT_ARK_MODEL = "ep-20260414011719-8x7s4"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _strip_list_marker(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    return re.sub(r"^\s*(?:[-*•]\s+|\(?\d{1,2}[\).、]\s*)", "", normalized).strip()


def _resolve_api_key(api_key: str | None) -> str | None:
    return resolve_llm_config(
        api_key,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )[0]


def _extract_output_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    # OpenAI Responses-like schema
    output = payload.get("output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        if texts:
            return "\n".join(texts)

    # Fallback schema variants
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    if isinstance(payload.get("text"), str):
        return payload["text"]
    return ""


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _sampling_params_hash(params: dict[str, Any] | None = None) -> str:
    material = json.dumps(params or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


def _call_ark_once(
    prompt: str,
    api_key: str,
    *,
    model: str,
    base_url: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    primary_body = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }
        ],
    }
    fallback_body = {
        "model": model,
        "input": prompt,
    }
    with httpx.Client(timeout=20.0) as client:
        response = client.post(base_url, headers=headers, json=primary_body)
        if response.status_code == 400:
            text = (response.text or "").lower()
            if "unknown type: text" in text or "content.type" in text:
                response = client.post(base_url, headers=headers, json=fallback_body)
    response.raise_for_status()
    return _extract_output_text(response.json())


async def _call_ark_async(
    prompt: str,
    api_key: str,
    *,
    model: str,
    base_url: str,
    semaphore: asyncio.Semaphore | None = None,
    task: str,
) -> str:
    async def _invoke() -> str:
        return await asyncio.to_thread(
            gated_call,
            kind="llm",
            cache_key_parts={
                "model": model,
                "prompt_hash": _prompt_hash(prompt),
                "sampling_params_hash": _sampling_params_hash(),
                "task": task,
            },
            payload={"prompt": prompt},
            invoke=lambda: _call_ark_once(prompt, api_key, model=model, base_url=base_url),
            validate_result=lambda value: isinstance(value, str),
        )

    try:
        if semaphore is not None:
            async with semaphore:
                return await _invoke()
        return await _invoke()
    except httpx.HTTPStatusError as exc:
        response = exc.response
        logger.warning("Query expander API %s: %s", response.status_code, response.text[:240])
        return ""
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Query expander API failed: %s", exc)
        return ""


async def translate_query_async(
    query: str,
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    semaphore: asyncio.Semaphore | None = None,
) -> str:
    source = _normalize_text(query)
    if not source:
        return ""

    resolved_api_key, resolved_base_url, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
    if not resolved_api_key:
        return source

    prompt = (
        "你是科研文献检索翻译专家。将以下中文查询翻译为英文检索查询。\n"
        "要求：\n"
        "1. 保留所有专业术语、材料名称、工艺名称的标准英文表达\n"
        "2. 保留关键量化词（如：高、低、优化、提升）的检索友好译法\n"
        "3. 使用学术文献常见表述，避免口语化\n"
        "4. 仅输出英文翻译，不要解释或添加额外内容\n\n"
        f"查询：{source}"
    )
    translated = _normalize_text(
        await _call_ark_async(
            prompt,
            resolved_api_key,
            model=resolved_model,
            base_url=resolved_base_url,
            semaphore=semaphore,
            task="query_translation",
        )
    )
    return translated or source


async def expand_multi_query_async(
    query: str,
    n: int = 3,
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    semaphore: asyncio.Semaphore | None = None,
) -> list[str]:
    source = _normalize_text(query)
    if not source:
        return []

    # Global cost guard: keep expansion path cheap by default in aggressive mode.
    if is_aggressive_cost_save():
        return [source]

    resolved_api_key, resolved_base_url, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
    if not resolved_api_key:
        return [source]

    safe_n = max(1, min(int(n), 8))
    prompt = (
        f"作为科研问题改写助手，将以下查询改写为 {safe_n} 个语义等价但表达不同的检索查询。\n"
        "要求：\n"
        "1. 包含专业表述、口语表述和带约束条件的变体\n"
        "2. 每行一个，不要编号，不要解释\n"
        f"查询：{source}"
    )
    text = await _call_ark_async(
        prompt,
        resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        semaphore=semaphore,
        task="query_expansion",
    )

    variants = [_strip_list_marker(line) for line in text.splitlines() if _strip_list_marker(line)]
    deduped: list[str] = []
    for item in [source, *variants]:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[: max(1, safe_n)] if deduped else [source]


async def generate_hyde_async(
    query: str,
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    semaphore: asyncio.Semaphore | None = None,
) -> str:
    source = _normalize_text(query)
    if not source:
        return ""

    # Global cost guard: HyDE always consumes one LLM generation; disable in aggressive mode.
    if is_aggressive_cost_save():
        return source

    resolved_api_key, resolved_base_url, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
    if not resolved_api_key:
        return source

    prompt = (
        "你是一名科研检索助手。请针对以下问题生成一段“假设性答案草稿”（约 120-180 字）。\n"
        "要求：\n"
        "1. 包含问题中的关键实体、机制、条件与可能指标\n"
        "2. 使用“可能”、“倾向于”等不确定性表述，不要下最终结论\n"
        "3. 纯文本一段，不要标题或前导语\n\n"
        f"问题：{source}"
    )
    hyde = _normalize_text(
        await _call_ark_async(
            prompt,
            resolved_api_key,
            model=resolved_model,
            base_url=resolved_base_url,
            semaphore=semaphore,
            task="generation",
        )
    )
    return hyde or source


async def decompose_query_async(
    query: str,
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    semaphore: asyncio.Semaphore | None = None,
) -> list[dict[str, Any]]:
    """将复杂科研问题拆解为原子化任务 (借鉴 sa-rag)"""
    source = _normalize_text(query)
    if not source:
        return []

    resolved_api_key, resolved_base_url, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
    if not resolved_api_key:
        return [{"id": 1, "task": source}]

    prompt = (
        "你是一名科研任务拆解专家。请将以下复杂问题拆解为 2-3 个原子化的检索任务。\n"
        "要求：\n"
        "1. 每个任务应专注于一个独立的事实点（如：具体的实验工艺、某项量化指标、对比关系）\n"
        "2. 严禁改变原问题语义\n"
        "3. 输出为严格的 JSON 数组，格式为: [{\"id\": 1, \"task\": \"任务描述\", \"reason\": \"原因\"}]\n\n"
        f"问题：{source}"
    )
    text = await _call_ark_async(
        prompt,
        resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        semaphore=semaphore,
        task="decomposition",
    )

    try:
        # 清理可能的 Markdown 标记
        cleaned_text = re.sub(r"```json\s*|\s*```", "", text).strip()
        data = json.loads(cleaned_text)
        if isinstance(data, list):
            return data
    except Exception:
        logger.warning("Failed to parse decomposed query JSON, falling back to original query")

    return [{"id": 1, "task": source}]


def translate_query(query: str, **kwargs: Any) -> str:
    return asyncio.run(translate_query_async(query, **kwargs))


def expand_multi_query(query: str, **kwargs: Any) -> list[str]:
    return asyncio.run(expand_multi_query_async(query, **kwargs))


def generate_hyde(query: str, **kwargs: Any) -> str:
    return asyncio.run(generate_hyde_async(query, **kwargs))

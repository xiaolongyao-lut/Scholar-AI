from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
DEFAULT_ARK_MODEL = "ep-20260414011719-8x7s4"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _resolve_api_key(api_key: str | None) -> str | None:
    return (
        api_key
        or os.getenv("VOLCANO_API_KEY")
        or os.getenv("ARK_API_KEY")
    )


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


async def _call_ark_async(
    prompt: str,
    api_key: str,
    *,
    model: str,
    base_url: str,
    semaphore: asyncio.Semaphore | None = None,
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

    _ctx = semaphore if semaphore is not None else contextlib.nullcontext()
    async with _ctx:
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(base_url, headers=headers, json=primary_body)
                    if response.status_code == 400:
                        text = (response.text or "").lower()
                        if "unknown type: text" in text or "content.type" in text:
                            response = await client.post(base_url, headers=headers, json=fallback_body)

                if response.status_code == 429 and attempt < 2:
                    await asyncio.sleep(0.8 * (2 ** attempt))
                    continue

                if response.status_code != 200:
                    logger.warning("Query expander API %s: %s", response.status_code, response.text[:240])
                    return ""
                return _extract_output_text(response.json())
            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.TimeoutException, ValueError, TypeError) as exc:
                if attempt < 2:
                    await asyncio.sleep(0.8 * (2 ** attempt))
                    continue
                logger.warning("Query expander API failed: %s", exc)
                return ""
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

    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        return source

    prompt = (
        "将以下中文查询翻译为准确、简洁的英文检索查询。"
        "仅输出英文翻译，不要解释。\n\n"
        f"查询：{source}"
    )
    translated = _normalize_text(
        await _call_ark_async(prompt, resolved_api_key, model=model, base_url=base_url, semaphore=semaphore)
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

    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        return [source]

    safe_n = max(1, min(int(n), 8))
    prompt = (
        f"将以下查询改写为 {safe_n} 个语义等价但表达不同的检索查询。"
        "每行一个，不要编号，不要解释。\n\n"
        f"查询：{source}"
    )
    text = await _call_ark_async(prompt, resolved_api_key, model=model, base_url=base_url, semaphore=semaphore)

    variants = [_normalize_text(line) for line in text.splitlines() if _normalize_text(line)]
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

    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        return source

    prompt = (
        "请作为海洋科学检索助手，针对以下问题生成一段约 120-180 字的专业中文假设答案。"
        "输出纯文本，不要标题。\n\n"
        f"问题：{source}"
    )
    hyde = _normalize_text(
        await _call_ark_async(prompt, resolved_api_key, model=model, base_url=base_url, semaphore=semaphore)
    )
    return hyde or source


def translate_query(query: str, **kwargs: Any) -> str:
    return asyncio.run(translate_query_async(query, **kwargs))


def expand_multi_query(query: str, **kwargs: Any) -> list[str]:
    return asyncio.run(expand_multi_query_async(query, **kwargs))


def generate_hyde(query: str, **kwargs: Any) -> str:
    return asyncio.run(generate_hyde_async(query, **kwargs))

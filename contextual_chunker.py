from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
DEFAULT_ARK_MODEL = "ep-20260414011719-8x7s4"
DEFAULT_SUMMARY_CACHE = Path("output") / "doc_summaries.json"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _resolve_api_key(api_key: str | None) -> str | None:
    return api_key or os.getenv("ARK_API_KEY") or os.getenv("VOLCANO_API_KEY")


def _extract_output_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

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

    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    if isinstance(payload.get("text"), str):
        return payload["text"]
    return ""


def _load_summary_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.exists():
        return {}
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items() if isinstance(v, str)}
    except (OSError, ValueError, TypeError):
        return {}
    return {}


def _save_summary_cache(cache_path: Path, cache: dict[str, str]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to save summary cache: %s", exc)


async def summarize_document_async(
    chunks: list[dict[str, Any]],
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    cache_path: Path = DEFAULT_SUMMARY_CACHE,
) -> str:
    """Generate a short document-level summary for one material group.

    Returns empty string when API key is unavailable or API call fails.
    """
    if not chunks:
        return ""

    material_id = str(chunks[0].get("material_id") or "__unknown__")
    cache = _load_summary_cache(cache_path)
    cached = _normalize_text(cache.get(material_id, ""))
    if cached:
        return cached

    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        return ""

    doc_text = "\n".join(_normalize_text(str(c.get("content") or "")) for c in chunks)
    doc_text = _normalize_text(doc_text)[:6000]
    if not doc_text:
        return ""

    prompt = (
        "请阅读以下文档片段，生成2-3句中文摘要，突出主题与研究对象。"
        "仅输出摘要正文，不要编号。\n\n"
        f"文档片段：{doc_text}"
    )

    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }
    body = {
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

    try:
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(base_url, headers=headers, json=body)

                if response.status_code == 400:
                    text = (response.text or "").lower()
                    if "unknown type: text" in text or "content.type" in text:
                        response = await client.post(base_url, headers=headers, json=fallback_body)

            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(0.8 * (2 ** attempt))
                continue

            if response.status_code != 200:
                logger.warning("Summary API %s: %s", response.status_code, response.text[:240])
                return ""

            summary = _normalize_text(_extract_output_text(response.json()))
            if summary:
                cache[material_id] = summary
                _save_summary_cache(cache_path, cache)
            return summary

        return ""
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Summary API failed: %s", exc)
        return ""


def add_context_prefix(chunk: dict[str, Any], doc_summary: str) -> dict[str, Any]:
    """Prepend document-level summary to chunk content and preserve raw content."""
    out = dict(chunk)
    content = str(out.get("content") or "")
    out["raw_content"] = str(out.get("raw_content") or content)

    summary = _normalize_text(doc_summary)
    if summary:
        out["content"] = f"[{summary}]\n{content}"
    else:
        out["content"] = content
    return out


async def batch_contextualize_async(
    chunks: list[dict[str, Any]],
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
    cache_path: Path = DEFAULT_SUMMARY_CACHE,
) -> list[dict[str, Any]]:
    """Contextualize chunks by adding material-level summary prefixes.

    Without API key, returns shallow copies of original chunks.
    """
    if not chunks:
        return []

    resolved_api_key = _resolve_api_key(api_key)
    if not resolved_api_key:
        return [dict(c) for c in chunks]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        material_id = str(chunk.get("material_id") or "__unknown__")
        grouped.setdefault(material_id, []).append(chunk)

    summaries: dict[str, str] = {}
    for material_id, material_chunks in grouped.items():
        summaries[material_id] = await summarize_document_async(
            material_chunks,
            api_key=resolved_api_key,
            base_url=base_url,
            model=model,
            cache_path=cache_path,
        )

    result: list[dict[str, Any]] = []
    for chunk in chunks:
        material_id = str(chunk.get("material_id") or "__unknown__")
        result.append(add_context_prefix(chunk, summaries.get(material_id, "")))
    return result


def batch_contextualize(chunks: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(batch_contextualize_async(chunks, **kwargs))

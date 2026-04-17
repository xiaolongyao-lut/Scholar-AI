from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_RERANKER_URL = "https://api.siliconflow.cn/v1/rerank"
DEFAULT_RERANKER_MODEL = "Qwen/Qwen3-Reranker-8B"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _extract_document(item: dict[str, Any]) -> str:
    # raw_content 优先：Phase 6 会在 content 里注入上下文摘要前缀，
    # rerank 应看无前缀原文，避免 Qwen3-Reranker 输入被稀释。
    return _normalize_text(
        str(
            item.get("raw_content")
            or item.get("content")
            or item.get("claim")
            or item.get("text")
            or item.get("source_text")
            or ""
        )
    )


def _fallback_score(item: dict[str, Any]) -> float:
    for key in ("rerank_score", "rrf_score", "hybrid_score", "dense_score"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _apply_fallback(candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    preserved: list[dict[str, Any]] = []
    for item in candidates[:top_k]:
        updated = dict(item)
        updated["rerank_score"] = _fallback_score(item)
        preserved.append(updated)
    return preserved


async def rerank_async(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 10,
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    semaphore: asyncio.Semaphore | None = None,
    timings: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Rerank retrieval candidates via SiliconFlow, with graceful fallback.

    timings (optional) — caller-supplied dict; on return contains:
      - queue_wait_ms: time spent waiting for `semaphore`
      - api_ms: pure HTTP round-trip for the successful attempt
      - attempts: number of attempts made (1-3)
    """
    if not candidates or top_k <= 0:
        return []

    resolved_api_key = api_key or os.getenv("SILICONFLOW_RERANK_API_KEY") or os.getenv("SILICONFLOW_API_KEY")
    resolved_base_url = base_url or os.getenv("SILICONFLOW_RERANK_BASE_URL", DEFAULT_RERANKER_URL)
    resolved_model = model or os.getenv("SILICONFLOW_RERANK_MODEL", DEFAULT_RERANKER_MODEL)

    documents = [_extract_document(item) for item in candidates]
    valid_pairs = [(idx, doc) for idx, doc in enumerate(documents) if doc]
    if not valid_pairs:
        return _apply_fallback(candidates, top_k)

    if not resolved_api_key:
        return _apply_fallback(candidates, top_k)

    payload = {
        "model": resolved_model,
        "query": query,
        "documents": [doc for _, doc in valid_pairs],
        "top_n": min(top_k, len(valid_pairs)),
        "return_documents": False,
    }
    headers = {
        "Authorization": f"Bearer {resolved_api_key}",
        "Content-Type": "application/json",
    }

    _ctx = semaphore if semaphore is not None else contextlib.nullcontext()
    t_call = time.perf_counter()
    async with _ctx:
        t_acquired = time.perf_counter()
        if timings is not None:
            timings["queue_wait_ms"] = (t_acquired - t_call) * 1000.0
        for attempt in range(3):
            try:
                t_api = time.perf_counter()
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(resolved_base_url, headers=headers, json=payload)
                api_ms = (time.perf_counter() - t_api) * 1000.0
                if timings is not None:
                    timings["api_ms"] = api_ms
                    timings["attempts"] = attempt + 1
                if response.status_code != 200:
                    logger.warning("Reranker API %s: %s", response.status_code, response.text[:240])
                    return _apply_fallback(candidates, top_k)

                body = response.json() if hasattr(response, "json") else {}
                result_items = body.get("results", []) if isinstance(body, dict) else []
                if not isinstance(result_items, list) or not result_items:
                    return _apply_fallback(candidates, top_k)

                score_by_original_index: dict[int, float] = {}
                original_indices = [idx for idx, _ in valid_pairs]
                for raw in result_items:
                    if not isinstance(raw, dict):
                        continue
                    rerank_index = raw.get("index")
                    score = raw.get("relevance_score")
                    if not isinstance(rerank_index, int) or not isinstance(score, (int, float)):
                        continue
                    if 0 <= rerank_index < len(original_indices):
                        score_by_original_index[original_indices[rerank_index]] = float(score)

                reranked: list[dict[str, Any]] = []
                for idx, item in enumerate(candidates):
                    updated = dict(item)
                    updated["rerank_score"] = score_by_original_index.get(idx, _fallback_score(item))
                    reranked.append(updated)

                reranked.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
                return reranked[:top_k]

            except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2 ** attempt))  # 0.5s, 1.0s
                    continue
                logger.warning("Reranker API failed after 3 attempts: %s", exc)
                return _apply_fallback(candidates, top_k)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as exc:  # pragma: no cover - unexpected parse errors
                logger.warning("Reranker API failed: %s", exc)
                return _apply_fallback(candidates, top_k)
    return _apply_fallback(candidates, top_k)


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 10,
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    return asyncio.run(
        rerank_async(
            query,
            candidates,
            top_k=top_k,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    )

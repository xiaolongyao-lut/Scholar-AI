from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from model_call_gateway import gated_call
from project_paths import output_path
from runtime_env import resolve_llm_config

logger = logging.getLogger(__name__)

DEFAULT_ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
DEFAULT_ARK_MODEL = "ep-20260414011719-8x7s4"
DEFAULT_SUMMARY_CACHE = output_path("doc_summaries.json")
DEFAULT_CONTEXTUAL_SUMMARIES_DIR = output_path("contextual_summaries")
DEFAULT_CONTEXTUAL_MISS_LOG = output_path("contextual_miss.jsonl")
CONTEXTUAL_SUMMARY_FIELDS = (
    "topic",
    "objective",
    "material_system",
    "process_method",
    "key_metrics",
    "main_conclusion",
    "keywords",
)
CONTEXTUAL_SUMMARY_PROMPT_V1 = """你是一个严格的文档信息抽取器。请仅基于给定文档片段生成“文档级摘要对象”。
【硬性约束】
1) 仅使用提供的内容；若信息不存在，填“文中未提及”。
2) 输出必须是单个 JSON 对象，且只能包含以下字段：
topic, objective, material_system, process_method, key_metrics, main_conclusion, keywords
3) 不得输出 Markdown、解释、前后缀文本。
4) 字段值要求简洁、可检索、无空话（禁止“本文主要讨论了”等）。
5) keywords 为数组，3-8 个短语，去重。
6) 若出现冲突信息，优先保留更具体、可验证、带数字/条件的表述。
7) 总体尽量压缩：除 keywords 外，每个字段建议 ≤ 28 个中文字符；main_conclusion 建议 ≤ 40 个中文字符。
【输出 JSON Schema（语义约束）】
- topic: 主题对象（研究/任务/问题域）
- objective: 目标（要解决什么）
- material_system: 材料/对象/系统边界（研究对象是谁）
- process_method: 方法/流程（怎么做）
- key_metrics: 关键指标/条件/量化结果（数字优先）
- main_conclusion: 主要结论（一句话）
- keywords: 关键词数组（检索友好）
【文档片段】
{context}"""


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _resolve_api_key(api_key: str | None) -> str | None:
    return resolve_llm_config(
        api_key,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )[0]


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


def _prompt_hash(prompt: str) -> str:
    return sha256(prompt.encode("utf-8")).hexdigest()


def _sampling_params_hash(params: dict[str, Any] | None = None) -> str:
    material = json.dumps(params or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


def _contextual_summary_path(
    material_id: str,
    *,
    project_id: str | None = None,
    summaries_root: Path = DEFAULT_CONTEXTUAL_SUMMARIES_DIR,
) -> Path | None:
    if project_id:
        candidate = Path(summaries_root) / str(project_id) / f"{material_id}.json"
        if candidate.exists():
            return candidate
    root = Path(summaries_root)
    if not root.exists():
        return None
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{material_id}.json"
        if candidate.exists():
            return candidate
    return None


def _coerce_contextual_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    summary: dict[str, Any] = {}
    for field in CONTEXTUAL_SUMMARY_FIELDS[:-1]:
        raw = value.get(field, "文中未提及")
        if isinstance(raw, (dict, list, tuple, set)):
            raw = "文中未提及"
        text = _normalize_text(str(raw))
        summary[field] = text or "文中未提及"

    keywords: list[str] = []
    raw_keywords = value.get("keywords")
    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            keyword = _normalize_text(str(item))
            if keyword and keyword not in keywords:
                keywords.append(keyword)
    summary["keywords"] = keywords or ["文中未提及"]
    return summary


def _extract_json_object_text(text: str) -> str | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if 0 <= start < end:
        return cleaned[start : end + 1].strip()
    return cleaned or None


def _parse_contextual_summary(raw_summary: Any) -> dict[str, Any] | None:
    if isinstance(raw_summary, dict):
        return _coerce_contextual_summary(raw_summary)
    json_text = _extract_json_object_text(str(raw_summary or ""))
    if not json_text:
        return None
    return _coerce_contextual_summary(json.loads(json_text))


def _load_contextual_summary(
    material_id: str,
    *,
    project_id: str | None = None,
    summaries_root: Path = DEFAULT_CONTEXTUAL_SUMMARIES_DIR,
) -> dict[str, Any] | None:
    path = _contextual_summary_path(material_id, project_id=project_id, summaries_root=summaries_root)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return _coerce_contextual_summary(payload)


def _render_contextual_summary(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return ""
    parts: list[str] = []
    for field in CONTEXTUAL_SUMMARY_FIELDS[:-1]:
        value = _normalize_text(str(summary.get(field) or ""))
        if value and value != "文中未提及":
            parts.append(value)
    keywords = summary.get("keywords")
    if isinstance(keywords, list):
        compact_keywords = [_normalize_text(str(item)) for item in keywords]
        compact_keywords = [item for item in compact_keywords if item and item != "文中未提及"]
        if compact_keywords:
            parts.append("关键词:" + "、".join(compact_keywords))
    return "；".join(parts)


def _append_contextual_miss(
    material_id: str,
    *,
    project_id: str | None = None,
    miss_log_path: Path = DEFAULT_CONTEXTUAL_MISS_LOG,
) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "project_id": str(project_id or ""),
        "material_id": str(material_id or ""),
    }
    try:
        miss_log_path = Path(miss_log_path)
        miss_log_path.parent.mkdir(parents=True, exist_ok=True)
        with miss_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        return


def _call_summary_once(
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
    with httpx.Client(timeout=20.0) as client:
        response = client.post(base_url, headers=headers, json=body)
        if response.status_code == 400:
            text = (response.text or "").lower()
            if "unknown type: text" in text or "content.type" in text:
                response = client.post(base_url, headers=headers, json=fallback_body)
    response.raise_for_status()
    return _extract_output_text(response.json())


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


async def summarize_document_json_async(
    chunks: list[dict[str, Any]],
    api_key: str | None = None,
    *,
    base_url: str = DEFAULT_ARK_URL,
    model: str = DEFAULT_ARK_MODEL,
) -> dict[str, Any] | None:
    if not chunks:
        return None

    resolved_api_key, resolved_base_url, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
    if not resolved_api_key:
        return None

    doc_text = "\n".join(_normalize_text(str(c.get("content") or "")) for c in chunks)
    doc_text = _normalize_text(doc_text)[:6000]
    if not doc_text:
        return None

    prompt = CONTEXTUAL_SUMMARY_PROMPT_V1.format(context=doc_text)

    try:
        raw_summary = await asyncio.to_thread(
            gated_call,
            kind="llm",
            cache_key_parts={
                "model": resolved_model,
                "prompt_hash": _prompt_hash(prompt),
                "sampling_params_hash": _sampling_params_hash(),
                "task": "contextual_summary",
            },
            payload={"prompt": prompt},
            invoke=lambda: _call_summary_once(
                prompt,
                resolved_api_key,
                model=resolved_model,
                base_url=resolved_base_url,
            ),
            validate_result=lambda value: isinstance(value, str),
        )
        parsed = _parse_contextual_summary(raw_summary)
        if parsed is None:
            logger.warning("Summary API returned empty or non-JSON output: %r", str(raw_summary)[:160])
            return None
        return parsed
    except httpx.HTTPStatusError as exc:
        response = exc.response
        logger.warning("Summary API %s: %s", response.status_code, response.text[:240])
        return None
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Summary API failed: %s", exc)
        return None


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

    resolved_api_key, resolved_base_url, resolved_model = resolve_llm_config(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=DEFAULT_ARK_URL,
        default_model=DEFAULT_ARK_MODEL,
    )
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

    try:
        summary = _normalize_text(
            await asyncio.to_thread(
                gated_call,
                kind="llm",
                cache_key_parts={
                    "model": resolved_model,
                    "prompt_hash": _prompt_hash(prompt),
                    "sampling_params_hash": _sampling_params_hash(),
                    "task": "contextual_summary",
                },
                payload={"prompt": prompt},
                invoke=lambda: _call_summary_once(
                    prompt,
                    resolved_api_key,
                    model=resolved_model,
                    base_url=resolved_base_url,
                ),
                validate_result=lambda value: isinstance(value, str),
            )
        )
        if summary:
            cache[material_id] = summary
            _save_summary_cache(cache_path, cache)
        return summary
    except httpx.HTTPStatusError as exc:
        response = exc.response
        logger.warning("Summary API %s: %s", response.status_code, response.text[:240])
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
    project_id: str | None = None,
    summaries_root: Path = DEFAULT_CONTEXTUAL_SUMMARIES_DIR,
    miss_log_path: Path = DEFAULT_CONTEXTUAL_MISS_LOG,
) -> list[dict[str, Any]]:
    """Contextualize chunks by adding material-level summary prefixes.

    Query-time contextualization is artifact-only. Missing summaries are logged
    for offline backfill and never generated online.
    """
    if not chunks:
        return []

    import os
    cost_profile = os.environ.get("LITERATURE_AI_COST_PROFILE", "").strip().lower()
    if cost_profile == "aggressive":
        return chunks

    if api_key is None:
        return chunks

    del api_key, base_url, model, cache_path

    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        material_id = str(chunk.get("material_id") or "__unknown__")
        grouped.setdefault(material_id, []).append(chunk)

    summaries: dict[str, str] = {}
    for material_id, material_chunks in grouped.items():
        resolved_project_id = project_id or str(material_chunks[0].get("project_id") or "").strip() or None
        artifact = _load_contextual_summary(
            material_id,
            project_id=resolved_project_id,
            summaries_root=summaries_root,
        )
        if artifact is None:
            _append_contextual_miss(
                material_id,
                project_id=resolved_project_id,
                miss_log_path=miss_log_path,
            )
            summaries[material_id] = ""
            continue
        summaries[material_id] = _render_contextual_summary(artifact)

    result: list[dict[str, Any]] = []
    for chunk in chunks:
        material_id = str(chunk.get("material_id") or "__unknown__")
        summary = summaries.get(material_id, "")
        if summary:
            result.append(add_context_prefix(chunk, summary))
        else:
            result.append(dict(chunk))
    return result


def batch_contextualize(chunks: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    return asyncio.run(batch_contextualize_async(chunks, **kwargs))

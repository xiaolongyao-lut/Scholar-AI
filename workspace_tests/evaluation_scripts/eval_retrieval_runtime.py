from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

try:
    from runtime_env import _dotenv_disabled
except (ImportError, ModuleNotFoundError):  # pragma: no cover - defensive fallback
    def _dotenv_disabled() -> bool:
        return str(os.getenv("RUNTIME_ENV_DISABLE_DOTENV", "")).strip().lower() in {"1", "true", "yes"}

# 加载 .env（SILICONFLOW_API_KEY / RERANK_API_KEY / ARK_API_KEY 等）
if not _dotenv_disabled():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        _env_path = Path(__file__).parent / ".env"
        if _env_path.exists():
            for line in _env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

try:
    from layers.r_layer_hybrid_retriever import hybrid_search as hybrid_search_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    hybrid_search_async = None

try:
    from graph_keyword_retriever import build_keyword_graph, graph_keyword_search
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    build_keyword_graph = None
    graph_keyword_search = None

try:
    from chunk_vector_store import ChunkVectorStore
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    ChunkVectorStore = None

try:
    from reranker_client import rerank_async, resolve_rerank_config, warm_rerank_live_candidate
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    rerank_async = None
    resolve_rerank_config = None
    warm_rerank_live_candidate = None

try:
    from query_expander import translate_query_async
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    translate_query_async = None

try:
    from contextual_chunker import batch_contextualize
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    batch_contextualize = None

try:
    from ai_cost_profile import get_cost_profile
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    def get_cost_profile() -> str:
        return "balanced"

from chunk_size_guard import filter_embedding_safe_chunks, summarize_oversize_chunks
from retrieval_provenance import attach_source_labels, merge_source_labels

logger = logging.getLogger(__name__)


# 默认参数采用“建议值”，不是硬编码策略。
# 后续只需改这里即可全局生效（run_eval 默认值与 CLI 默认值共用）。
DEFAULT_TOP_K = 10
DEFAULT_RECALL_TOP_N = 100
DEFAULT_RERANK_TOP_N = 40
DEFAULT_USE_RERANK = True
# 实测：query expansion 在 v2.0 (414 条中文语料) 上反向收益 -12%
# （0.3043 → 0.2657）。翻译后英文 query 喂 dense 路引入噪声，RRF 稀释
# BM25/Graph 的精准命中。保留代码路径但默认关闭，需 --expansion 显式开。
DEFAULT_USE_EXPANSION = False
DEFAULT_USE_PREFILTER = False
DEFAULT_PREFILTER_THRESHOLD = 0.3
DEFAULT_USE_DYNAMIC_TOPK = False
DEFAULT_DYNAMIC_LOW_RERANK_TOP_N = 20
DEFAULT_DYNAMIC_HIGH_RERANK_TOP_N = 60
DEFAULT_DYNAMIC_SCORE_GAP_THRESHOLD = 0.15
DEFAULT_RERANK_PRE_TOPN = 30
DEFAULT_RERANK_PRE_TOPN_HARD_CAP = 60
DEFAULT_QUERIES_PATH = "eval_queries_v2.0.jsonl"
DEFAULT_QUERY_CONCURRENCY = 8
DEFAULT_RERANK_CONCURRENCY = 3
DEFAULT_STRICT_CACHE_GUARD = True


def _resolve_rerank_model_identity(use_rerank: bool) -> str | None:
    if not use_rerank:
        return None
    if resolve_rerank_config is not None:
        try:
            _, _, model = resolve_rerank_config()
            return str(model or "").strip() or None
        except Exception:  # pragma: no cover - defensive fallback
            pass
    fallback = (
        os.getenv("DASHSCOPE_RERANK_MODEL")
        or os.getenv("SILICONFLOW_RERANK_MODEL")
    )
    return str(fallback or "").strip() or None


def _resume_guard_path(output_path: str) -> Path:
    return Path(f"{output_path}.resume_config.json")


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    return str(Path(path).resolve())


def _file_sha256(path: str | None) -> str | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_nonempty_lines(path: str | None) -> int | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None
    with file_path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _has_resume_data(path: str | None) -> bool:
    if not path:
        return False
    file_path = Path(path)
    return file_path.exists() and file_path.is_file() and file_path.stat().st_size > 0


def _get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _configured_rerank_pre_top_n_hard_cap() -> int:
    return max(1, _get_env_int("RERANK_PRE_TOPN_HARD_CAP", DEFAULT_RERANK_PRE_TOPN_HARD_CAP))


def _configured_rerank_pre_top_n() -> int:
    return min(
        max(1, _get_env_int("RERANK_PRE_TOPN", DEFAULT_RERANK_PRE_TOPN)),
        _configured_rerank_pre_top_n_hard_cap(),
    )


def _build_resume_guard_config(
    *,
    queries_path: str,
    output_path: str,
    top_k: int,
    recall_top_n: int,
    use_rerank: bool,
    rerank_top_n: int,
    use_prefilter: bool,
    prefilter_threshold: float,
    use_dynamic_topk: bool,
    dynamic_low_rerank_top_n: int,
    dynamic_high_rerank_top_n: int,
    dynamic_score_gap_threshold: float,
    use_expansion: bool,
    use_contextual: bool,
    query_concurrency: int,
    strict_cache_guard: bool,
    chunk_store_dir: str | None,
    embedding_cache_path: str | None,
    template_flags_path: str | None,
    offset: int,
    limit: int | None,
    progress_path: str | None,
    progress_every: int,
    per_query_output: str | None,
    rerank_trace_output: str | None = None,
) -> dict[str, Any]:
    return {
        "queries_path": _normalize_path(queries_path),
        "output_path": _normalize_path(output_path),
        "query_slice": {
            "offset": int(offset),
            "limit": int(limit) if limit is not None else None,
        },
        "retrieval_config": {
            "top_k": int(top_k),
            "recall_top_n": int(recall_top_n),
            "use_rerank": bool(use_rerank),
            "rerank_model": _resolve_rerank_model_identity(use_rerank),
            "rerank_top_n": int(rerank_top_n),
            "rerank_pre_top_n": _configured_rerank_pre_top_n(),
            "rerank_pre_top_n_hard_cap": _configured_rerank_pre_top_n_hard_cap(),
            "cost_profile": get_cost_profile(),
            "use_prefilter": bool(use_prefilter),
            "prefilter_threshold": float(prefilter_threshold),
            "use_dynamic_topk": bool(use_dynamic_topk),
            "dynamic_low_rerank_top_n": int(dynamic_low_rerank_top_n),
            "dynamic_high_rerank_top_n": int(dynamic_high_rerank_top_n),
            "dynamic_score_gap_threshold": float(dynamic_score_gap_threshold),
            "use_expansion": bool(use_expansion),
            "use_contextual": bool(use_contextual),
            "query_concurrency": int(query_concurrency),
            "strict_cache_guard": bool(strict_cache_guard),
            "chunk_store_dir": _normalize_path(chunk_store_dir),
            "embedding_cache_path": _normalize_path(embedding_cache_path),
            "template_flags_path": _normalize_path(template_flags_path),
        },
        "append_targets": {
            "progress_path": _normalize_path(progress_path),
            "progress_every": int(progress_every),
            "per_query_output": _normalize_path(per_query_output),
            "rerank_trace_output": _normalize_path(rerank_trace_output),
        },
    }


def _enforce_resume_parity_guard(
    *,
    queries_path: str,
    output_path: str,
    top_k: int,
    recall_top_n: int,
    use_rerank: bool,
    rerank_top_n: int,
    use_prefilter: bool,
    prefilter_threshold: float,
    use_dynamic_topk: bool,
    dynamic_low_rerank_top_n: int,
    dynamic_high_rerank_top_n: int,
    dynamic_score_gap_threshold: float,
    use_expansion: bool,
    use_contextual: bool,
    query_concurrency: int,
    strict_cache_guard: bool,
    chunk_store_dir: str | None,
    embedding_cache_path: str | None,
    template_flags_path: str | None,
    offset: int,
    limit: int | None,
    progress_path: str | None,
    progress_every: int,
    per_query_output: str | None,
    rerank_trace_output: str | None = None,
) -> None:
    guard_file = _resume_guard_path(output_path)
    current_config = _build_resume_guard_config(
        queries_path=queries_path,
        output_path=output_path,
        top_k=top_k,
        recall_top_n=recall_top_n,
        use_rerank=use_rerank,
        rerank_top_n=rerank_top_n,
        use_prefilter=use_prefilter,
        prefilter_threshold=prefilter_threshold,
        use_dynamic_topk=use_dynamic_topk,
        dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
        dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
        dynamic_score_gap_threshold=dynamic_score_gap_threshold,
        use_expansion=use_expansion,
        use_contextual=use_contextual,
        query_concurrency=query_concurrency,
        strict_cache_guard=strict_cache_guard,
        chunk_store_dir=chunk_store_dir,
        embedding_cache_path=embedding_cache_path,
        template_flags_path=template_flags_path,
        offset=offset,
        limit=limit,
        progress_path=progress_path,
        progress_every=progress_every,
        per_query_output=per_query_output,
        rerank_trace_output=rerank_trace_output,
    )
    has_resume_data = _has_resume_data(progress_path) or _has_resume_data(per_query_output)
    if has_resume_data:
        if not guard_file.exists():
            raise ValueError(
                f"Resume parity guard rejected: missing guard file {guard_file}. "
                "Start a fresh run with empty append targets first."
            )
        try:
            previous_config = json.loads(guard_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Resume parity guard rejected: unreadable guard file {guard_file}."
            ) from exc
        if previous_config != current_config:
            raise ValueError(
                "Resume parity guard rejected: run config mismatch with existing artifact."
            )
        return
    guard_file.parent.mkdir(parents=True, exist_ok=True)
    guard_file.write_text(
        json.dumps(current_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_run_provenance(
    *,
    queries_path: str,
    evaluated_query_count: int,
    top_k: int,
    recall_top_n: int,
    use_rerank: bool,
    rerank_top_n: int,
    use_prefilter: bool,
    prefilter_threshold: float,
    use_dynamic_topk: bool,
    dynamic_low_rerank_top_n: int,
    dynamic_high_rerank_top_n: int,
    dynamic_score_gap_threshold: float,
    use_expansion: bool,
    use_contextual: bool,
    query_concurrency: int,
    strict_cache_guard: bool,
    chunk_store_dir: str | None,
    embedding_cache_path: str | None,
    template_flags_path: str | None,
    offset: int,
    limit: int | None,
) -> dict[str, Any]:
    return {
        "queries": {
            "path": _normalize_path(queries_path),
            "sha256": _file_sha256(queries_path),
            "source_total_queries": _count_nonempty_lines(queries_path),
            "evaluated_queries": int(evaluated_query_count),
            "offset": int(offset),
            "limit": int(limit) if limit is not None else None,
        },
        "template_flags": {
            "enabled": bool(template_flags_path),
            "path": _normalize_path(template_flags_path),
            "sha256": _file_sha256(template_flags_path),
        },
        "retrieval_config": {
            "top_k": int(top_k),
            "recall_top_n": int(recall_top_n),
            "use_rerank": bool(use_rerank),
            "rerank_model": _resolve_rerank_model_identity(use_rerank),
            "rerank_top_n": int(rerank_top_n),
            "rerank_pre_top_n": _configured_rerank_pre_top_n(),
            "rerank_pre_top_n_hard_cap": _configured_rerank_pre_top_n_hard_cap(),
            "use_prefilter": bool(use_prefilter),
            "prefilter_threshold": float(prefilter_threshold),
            "use_dynamic_topk": bool(use_dynamic_topk),
            "dynamic_low_rerank_top_n": int(dynamic_low_rerank_top_n),
            "dynamic_high_rerank_top_n": int(dynamic_high_rerank_top_n),
            "dynamic_score_gap_threshold": float(dynamic_score_gap_threshold),
            "use_expansion": bool(use_expansion),
            "use_contextual": bool(use_contextual),
            "query_concurrency": int(query_concurrency),
            "strict_cache_guard": bool(strict_cache_guard),
            "chunk_store_dir": _normalize_path(chunk_store_dir),
            "embedding_cache_path": _normalize_path(embedding_cache_path),
            "cost_profile": get_cost_profile(),
        },
    }


def _calculate_mrr(relevance_list: list[bool]) -> float:
    for idx, is_rel in enumerate(relevance_list):
        if is_rel:
            return 1.0 / (idx + 1)
    return 0.0


def _calculate_recall_at_k(relevance_list: list[bool], k: int) -> float:
    return 1.0 if any(relevance_list[:k]) else 0.0


def _extract_candidate_doc_ids(hit: dict[str, Any]) -> set[str]:
    candidates = {
        str(hit.get("material_id", "")).strip(),
        str(hit.get("doc_id", "")).strip(),
        str(hit.get("id", "")).strip(),
    }
    chunk_id = str(hit.get("chunk_id", "")).strip()
    if chunk_id and "_chunk_" in chunk_id:
        candidates.add(chunk_id.split("_chunk_")[0])
    return {x for x in candidates if x}


def _trace_hit(hit: dict[str, Any], rank: int) -> dict[str, Any]:
    record: dict[str, Any] = {"rank": int(rank)}
    for key in ("chunk_id", "material_id", "doc_id", "id"):
        value = str(hit.get(key, "")).strip()
        if value:
            record[key] = value
    candidate_doc_ids = sorted(_extract_candidate_doc_ids(hit))
    if candidate_doc_ids:
        record["candidate_doc_ids"] = candidate_doc_ids
    for key in ("rrf_score", "rerank_score", "dense_score", "score"):
        value = hit.get(key)
        if value is None:
            continue
        try:
            record[key] = float(value)
        except (TypeError, ValueError):
            continue
    warning = str(hit.get("warning", "")).strip()
    if warning:
        record["warning"] = warning
    if bool(hit.get("rerank_fallback")):
        record["rerank_fallback"] = True
    return record


def _trace_rerank_fallback_detected(returned_hits: list[dict[str, Any]]) -> bool:
    return any(bool(hit.get("rerank_fallback")) for hit in returned_hits if isinstance(hit, dict))


def _trace_rerank_warning(returned_hits: list[dict[str, Any]]) -> str | None:
    for hit in returned_hits:
        if not isinstance(hit, dict):
            continue
        warning = str(hit.get("warning", "")).strip()
        if warning:
            return warning
    return None


def _record_rerank_trace(
    trace: dict[str, Any] | None,
    *,
    use_rerank: bool,
    candidates_before_rerank: list[dict[str, Any]],
    returned_hits: list[dict[str, Any]],
    retrieval_stage: str,
    rerank_pre_top_n: int | None = None,
    rerank_fallback: bool = False,
) -> None:
    if trace is None:
        return
    trace_rerank_fallback = bool(rerank_fallback) or _trace_rerank_fallback_detected(returned_hits)
    trace_rerank_warning = _trace_rerank_warning(returned_hits)
    trace.update(
        {
            "use_rerank": bool(use_rerank),
            "retrieval_stage": retrieval_stage,
            "rerank_pre_top_n": int(rerank_pre_top_n) if rerank_pre_top_n is not None else None,
            "rerank_fallback": trace_rerank_fallback,
            "candidates_before_rerank": [
                _trace_hit(hit, rank)
                for rank, hit in enumerate(candidates_before_rerank, start=1)
                if isinstance(hit, dict)
            ],
            "returned_hits": [
                _trace_hit(hit, rank)
                for rank, hit in enumerate(returned_hits, start=1)
                if isinstance(hit, dict)
            ],
        }
    )
    if trace_rerank_warning:
        trace["rerank_warning"] = trace_rerank_warning


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "aggregated_metrics": {
                "recall_at_1": 0.0,
                "recall_at_3": 0.0,
                "recall_at_5": 0.0,
                "recall_at_10": 0.0,
                "mrr": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "rerank_api_avg_ms": 0.0,
                "rerank_api_p95_ms": 0.0,
                "rerank_queue_avg_ms": 0.0,
                "rerank_queue_p95_ms": 0.0,
            },
            "per_difficulty": {},
        }

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    def _p95(values: list[float]) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        return round(s[min(len(s) - 1, int(len(s) * 0.95))], 2)

    latencies = sorted(float(r.get("latency_ms", 0.0)) for r in results)
    p95_idx = min(len(latencies) - 1, int(len(latencies) * 0.95))

    api_ms_list = [float(r["rerank_api_ms"]) for r in results if r.get("rerank_api_ms") is not None]
    queue_ms_list = [float(r["rerank_queue_wait_ms"]) for r in results if r.get("rerank_queue_wait_ms") is not None]

    aggregated = {
        "recall_at_1": _avg([float(r.get("recall_at_1", 0.0)) for r in results]),
        "recall_at_3": _avg([float(r.get("recall_at_3", 0.0)) for r in results]),
        "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in results]),
        "recall_at_10": _avg([float(r.get("recall_at_10", 0.0)) for r in results]),
        "mrr": _avg([float(r.get("mrr", 0.0)) for r in results]),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
        "p95_latency_ms": round(latencies[p95_idx], 2),
        "rerank_api_avg_ms": round(sum(api_ms_list) / len(api_ms_list), 2) if api_ms_list else 0.0,
        "rerank_api_p95_ms": _p95(api_ms_list),
        "rerank_queue_avg_ms": round(sum(queue_ms_list) / len(queue_ms_list), 2) if queue_ms_list else 0.0,
        "rerank_queue_p95_ms": _p95(queue_ms_list),
    }

    per_difficulty: dict[str, dict[str, Any]] = {}
    for diff in sorted({str(r.get("difficulty", "unknown")) for r in results}):
        subset = [r for r in results if str(r.get("difficulty", "unknown")) == diff]
        per_difficulty[diff] = {
            "count": len(subset),
            "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in subset]),
            "mrr": _avg([float(r.get("mrr", 0.0)) for r in subset]),
        }

    payload: dict[str, Any] = {
        "aggregated_metrics": aggregated,
        "per_difficulty": per_difficulty,
    }

    # Wave 1: template/non_template 分桶(仅当 results 里出现 is_template 字段时输出)
    if any("is_template" in r for r in results):
        per_template_bucket: dict[str, dict[str, Any]] = {}
        for flag in (True, False):
            subset = [r for r in results if r.get("is_template") is flag]
            if not subset:
                continue
            key = "template" if flag else "non_template"
            per_template_bucket[key] = {
                "count": len(subset),
                "recall_at_5": _avg([float(r.get("recall_at_5", 0.0)) for r in subset]),
                "mrr": _avg([float(r.get("mrr", 0.0)) for r in subset]),
            }
        if per_template_bucket:
            payload["per_template_bucket"] = per_template_bucket

    return payload


def _load_queries(queries_path: Path) -> list[dict[str, Any]]:
    if not queries_path.exists():
        raise FileNotFoundError(f"Query file not found: {queries_path}")
    with queries_path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _flatten_chunk_payload(payload: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if isinstance(payload, list):
        chunks.extend([x for x in payload if isinstance(x, dict)])
    elif isinstance(payload, dict):
        raw = payload.get("chunks")
        if isinstance(raw, list):
            chunks.extend([x for x in raw if isinstance(x, dict)])
        else:
            for val in payload.values():
                if isinstance(val, list):
                    chunks.extend([x for x in val if isinstance(x, dict)])
    return chunks


def _read_v2_material_jsonl(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    chunks.append(payload)
    except OSError:
        return []
    return chunks


def _load_v2_project_chunks(project_dir: Path) -> list[dict[str, Any]]:
    manifest_path = project_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    materials = manifest.get("materials")
    if not isinstance(materials, dict):
        return []
    chunks: list[dict[str, Any]] = []
    for entry in materials.values():
        if not isinstance(entry, dict):
            continue
        relative_path = entry.get("relative_path") or entry.get("file")
        if not relative_path:
            continue
        chunks.extend(_read_v2_material_jsonl(project_dir / str(relative_path)))
    return chunks


def _load_retrieval_corpus(chunk_store_dir: Path | None = None) -> dict[str, Any]:
    """Load retrieval corpus from chunk_store, preferring v2 manifest layout."""
    chunk_store_dir = chunk_store_dir or (Path("output") / "chunk_store")
    if not chunk_store_dir.exists():
        return {"chunks": [], "oversize_count": 0}
    if (chunk_store_dir / "manifest.json").exists():
        chunks = _load_v2_project_chunks(chunk_store_dir)
        return {"chunks": chunks, **summarize_oversize_chunks(chunks)}

    chunks: list[dict[str, Any]] = []
    v2_projects: set[str] = set()

    for project_dir in sorted(path for path in chunk_store_dir.iterdir() if path.is_dir()):
        manifest_path = project_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        v2_projects.add(project_dir.name)
        chunks.extend(_load_v2_project_chunks(project_dir))

    for fp in sorted(chunk_store_dir.glob("*.json")):
        legacy_project_id = fp.name[: -len("_chunks.json")] if fp.name.endswith("_chunks.json") else None
        if legacy_project_id and legacy_project_id in v2_projects:
            continue
        try:
            with fp.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            chunks.extend(_flatten_chunk_payload(payload))
            if legacy_project_id:
                logger.warning(
                    "legacy chunk view detected at %s; run scripts/migrate_chunk_store_to_jsonl.py",
                    fp,
                )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return {"chunks": chunks, **summarize_oversize_chunks(chunks)}


async def retrieve_then_rerank(
    query_text: str,
    corpus: dict[str, Any],
    top_k: int = DEFAULT_TOP_K,
    *,
    recall_top_n: int = DEFAULT_RECALL_TOP_N,
    use_rerank: bool = DEFAULT_USE_RERANK,
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    use_prefilter: bool = DEFAULT_USE_PREFILTER,
    prefilter_threshold: float = DEFAULT_PREFILTER_THRESHOLD,
    use_dynamic_topk: bool = DEFAULT_USE_DYNAMIC_TOPK,
    dynamic_low_rerank_top_n: int = DEFAULT_DYNAMIC_LOW_RERANK_TOP_N,
    dynamic_high_rerank_top_n: int = DEFAULT_DYNAMIC_HIGH_RERANK_TOP_N,
    dynamic_score_gap_threshold: float = DEFAULT_DYNAMIC_SCORE_GAP_THRESHOLD,
    use_expansion: bool = DEFAULT_USE_EXPANSION,
    strict_cache_guard: bool = DEFAULT_STRICT_CACHE_GUARD,
) -> list[dict[str, Any]]:
    """Thin public retrieval → rerank wrapper for smoke tests and integrations."""
    chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []

    keyword_graph: dict[str, Any] | None = None
    if build_keyword_graph and chunks:
        try:
            keyword_graph = build_keyword_graph(chunks)
        except (RuntimeError, TypeError, ValueError):
            keyword_graph = None

    vector_store = None
    query_vec = None
    if ChunkVectorStore is not None and chunks:
        try:
            vector_store = await ChunkVectorStore.build(
                chunks,
                strict_cache_guard=strict_cache_guard,
                concurrency=_get_env_int("EMBED_CONCURRENCY", 32),
            )
        except (RuntimeError, TypeError, ValueError):
            vector_store = None
        if vector_store is not None and vector_store.has_embeddings:
            try:
                query_vec = await vector_store.embed_query(query_text)
            except (RuntimeError, TypeError, ValueError):
                query_vec = None

    rerank_semaphore = asyncio.Semaphore(
        int(os.getenv("SILICONFLOW_RERANK_CONCURRENCY", str(DEFAULT_RERANK_CONCURRENCY)))
    ) if use_rerank else None
    # Tier 2 optimization: Increase concurrency from 5 to 10 (1-2s savings).
    # Override with WIKI_EXPANSION_CONCURRENCY env var for testing different concurrency levels.
    expansion_concurrency = int(os.getenv("WIKI_EXPANSION_CONCURRENCY", "10"))
    expansion_semaphore = asyncio.Semaphore(expansion_concurrency) if use_expansion else None

    if use_rerank and warm_rerank_live_candidate is not None:
        try:
            await warm_rerank_live_candidate()
        except (RuntimeError, TypeError, ValueError):
            pass

    return await _retrieve_with_expansion(
        query_text,
        corpus,
        top_k=top_k,
        keyword_graph=keyword_graph,
        vector_store=vector_store,
        query_vec=query_vec,
        use_rerank=use_rerank,
        rerank_top_n=rerank_top_n,
        use_prefilter=use_prefilter,
        prefilter_threshold=prefilter_threshold,
        use_dynamic_topk=use_dynamic_topk,
        dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
        dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
        dynamic_score_gap_threshold=dynamic_score_gap_threshold,
        rerank_semaphore=rerank_semaphore,
        use_expansion=use_expansion,
        expansion_semaphore=expansion_semaphore,
        recall_top_n=recall_top_n,
    )


async def _retrieve(
    query_text: str,
    corpus: dict[str, Any],
    top_k: int,
    *,
    keyword_graph: dict[str, Any] | None = None,
    vector_store: Any | None = None,
    query_vec: Any | None = None,
    use_rerank: bool = True,
    rerank_top_n: int = 20,
    use_prefilter: bool = False,
    prefilter_threshold: float = DEFAULT_PREFILTER_THRESHOLD,
    use_dynamic_topk: bool = False,
    dynamic_low_rerank_top_n: int = DEFAULT_DYNAMIC_LOW_RERANK_TOP_N,
    dynamic_high_rerank_top_n: int = DEFAULT_DYNAMIC_HIGH_RERANK_TOP_N,
    dynamic_score_gap_threshold: float = DEFAULT_DYNAMIC_SCORE_GAP_THRESHOLD,
    rerank_semaphore: Any | None = None,
    rerank_timings: dict[str, float] | None = None,
    rerank_trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    hybrid_hits: list[dict[str, Any]] = []
    graph_hits: list[dict[str, Any]] = []
    dense_hits: list[dict[str, Any]] = []

    retrieval_top_n = max(
        top_k,
        rerank_top_n,
        dynamic_high_rerank_top_n if use_dynamic_topk else rerank_top_n,
    )

    if hybrid_search_async:
        try:
            hits = await hybrid_search_async(corpus, query_text, top_k=retrieval_top_n)
            hybrid_hits = hits if isinstance(hits, list) else []
        except (RuntimeError, TypeError, ValueError):
            hybrid_hits = []

    if keyword_graph and graph_keyword_search:
        try:
            chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
            graph_hits = graph_keyword_search(keyword_graph, chunks, query=query_text, top_k=retrieval_top_n)
        except (RuntimeError, TypeError, ValueError):
            graph_hits = []

    if vector_store is not None:
        try:
            dense_hits = await _dense_retrieve_precomputed(vector_store, query_vec, retrieval_top_n)
        except (RuntimeError, TypeError, ValueError):
            dense_hits = []

    merged_hits = _rrf_fuse([hybrid_hits, graph_hits, dense_hits], top_k=retrieval_top_n)
    effective_rerank_top_n = rerank_top_n
    if use_dynamic_topk and merged_hits:
        effective_rerank_top_n = _compute_dynamic_rerank_top_n(
            query_text,
            merged_hits,
            low_top_n=dynamic_low_rerank_top_n,
            high_top_n=dynamic_high_rerank_top_n,
            score_gap_threshold=dynamic_score_gap_threshold,
        )
    if use_prefilter and merged_hits:
        merged_hits = _prefilter_hits(
            merged_hits,
            threshold=prefilter_threshold,
            keep_top_n=max(top_k, effective_rerank_top_n),
        )
    if use_rerank and rerank_async and merged_hits:
        rerank_pre_top_n = _resolve_rerank_pre_top_n(
            query_text,
            merged_hits,
            rerank_top_n=effective_rerank_top_n,
            hybrid_hit_count=len(hybrid_hits),
        )
        rerank_candidates = merged_hits[:rerank_pre_top_n]
        try:
            reranked_hits = await rerank_async(
                query_text, rerank_candidates, top_k=top_k,
                semaphore=rerank_semaphore, timings=rerank_timings,
            )
            _record_rerank_trace(
                rerank_trace,
                use_rerank=True,
                candidates_before_rerank=rerank_candidates,
                returned_hits=reranked_hits,
                retrieval_stage="standard",
                rerank_pre_top_n=rerank_pre_top_n,
            )
            return reranked_hits
        except (RuntimeError, TypeError, ValueError):
            fallback_hits = merged_hits[:top_k]
            _record_rerank_trace(
                rerank_trace,
                use_rerank=True,
                candidates_before_rerank=rerank_candidates,
                returned_hits=fallback_hits,
                retrieval_stage="standard",
                rerank_pre_top_n=rerank_pre_top_n,
                rerank_fallback=True,
            )
    final_hits = merged_hits[:top_k]
    _record_rerank_trace(
        rerank_trace,
        use_rerank=False,
        candidates_before_rerank=final_hits,
        returned_hits=final_hits,
        retrieval_stage="standard",
    )
    return final_hits


async def _dense_retrieve_precomputed(
    vector_store: Any, query_vec: Any, top_k: int
) -> list[dict[str, Any]]:
    """Dense retrieval with a pre-computed query vector (no API call)."""
    if query_vec is None:
        return []
    return vector_store.cosine_search(query_vec, top_k=top_k)


async def _retrieve_with_expansion(
    query_text: str,
    corpus: dict[str, Any],
    top_k: int,
    *,
    keyword_graph: dict[str, Any] | None = None,
    vector_store: Any | None = None,
    query_vec: Any | None = None,
    use_rerank: bool = True,
    rerank_top_n: int = 20,
    use_prefilter: bool = False,
    prefilter_threshold: float = DEFAULT_PREFILTER_THRESHOLD,
    use_dynamic_topk: bool = False,
    dynamic_low_rerank_top_n: int = DEFAULT_DYNAMIC_LOW_RERANK_TOP_N,
    dynamic_high_rerank_top_n: int = DEFAULT_DYNAMIC_HIGH_RERANK_TOP_N,
    dynamic_score_gap_threshold: float = DEFAULT_DYNAMIC_SCORE_GAP_THRESHOLD,
    rerank_semaphore: Any | None = None,
    use_expansion: bool = False,
    expansion_semaphore: Any | None = None,
    recall_top_n: int = 100,
    rerank_timings: dict[str, float] | None = None,
    rerank_trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Phase 5.2: split-routing translated retrieval.

    Why split-routing: r_layer_hybrid_retriever 的 BM25 把中英文 token
    分开统计（en_tokens / cn_tokens），英文 query 匹不到中文 chunk；
    graph_keyword_retriever 同理只在 token-level 命中。因此翻译只能
    喂给 bge-m3 dense 这一路，BM25 + Graph 必须保留中文原 query，
    否则 3 路 RRF 退化成 1 路，指标反而下降。

    接线：
      - BM25 (hybrid) + Graph：原中文 query_text
      - Dense：英文 translated query + 对应重嵌的 query_vec
      - Rerank：原中文 query_text（Qwen3-Reranker-8B 支持跨语言）
    """

    merge_top = max(
        top_k,
        rerank_top_n,
        recall_top_n,
        dynamic_high_rerank_top_n if use_dynamic_topk else rerank_top_n,
    )

    # --- 1. 非扩展路径：走原来的单 query 三路 -----------------------
    if not use_expansion or translate_query_async is None:
        return await _retrieve(
            query_text,
            corpus,
            top_k=merge_top,
            keyword_graph=keyword_graph,
            vector_store=vector_store,
            query_vec=query_vec,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            use_prefilter=use_prefilter,
            prefilter_threshold=prefilter_threshold,
            use_dynamic_topk=use_dynamic_topk,
            dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
            dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
            dynamic_score_gap_threshold=dynamic_score_gap_threshold,
            rerank_semaphore=rerank_semaphore,
            rerank_timings=rerank_timings,
            rerank_trace=rerank_trace,
        )

    # --- 2. 翻译（失败则降级到原 query）------------------------------
    translated = ""
    try:
        translated = await translate_query_async(query_text, semaphore=expansion_semaphore)
    except (RuntimeError, TypeError, ValueError):
        translated = ""

    translated = (translated or "").strip()
    if not translated or translated == query_text:
        # 翻译无效 / 无 API key，整个路径回退
        return await _retrieve(
            query_text,
            corpus,
            top_k=merge_top,
            keyword_graph=keyword_graph,
            vector_store=vector_store,
            query_vec=query_vec,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            use_prefilter=use_prefilter,
            prefilter_threshold=prefilter_threshold,
            use_dynamic_topk=use_dynamic_topk,
            dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
            dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
            dynamic_score_gap_threshold=dynamic_score_gap_threshold,
            rerank_semaphore=rerank_semaphore,
            rerank_timings=rerank_timings,
            rerank_trace=rerank_trace,
        )

    # --- 3. 并行：翻译 + 重嵌 与 BM25+Graph 同时进行 ---------------
    async def _embed_translated() -> Any:
        if vector_store is None:
            return query_vec
        try:
            return await vector_store.embed_query(translated)
        except (RuntimeError, TypeError, ValueError):
            return query_vec

    embed_task = asyncio.create_task(_embed_translated())

    hybrid_hits: list[dict[str, Any]] = []
    graph_hits: list[dict[str, Any]] = []
    dense_hits: list[dict[str, Any]] = []

    # BM25 + Graph 用原中文 query，与翻译重嵌并行
    hybrid_task = None
    if hybrid_search_async:
        hybrid_task = asyncio.create_task(
            hybrid_search_async(corpus, query_text, top_k=merge_top)
        )

    if keyword_graph and graph_keyword_search:
        try:
            chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
            graph_hits = graph_keyword_search(
                keyword_graph, chunks, query=query_text, top_k=merge_top
            )
        except (RuntimeError, TypeError, ValueError):
            graph_hits = []

    # 等待重嵌完成后再跑 dense 检索
    translated_vec = await embed_task
    if vector_store is not None and translated_vec is not None:
        try:
            dense_hits = await _dense_retrieve_precomputed(
                vector_store, translated_vec, merge_top
            )
        except (RuntimeError, TypeError, ValueError):
            dense_hits = []

    if hybrid_task is not None:
        try:
            hits = await hybrid_task
            hybrid_hits = hits if isinstance(hits, list) else []
        except (RuntimeError, TypeError, ValueError):
            hybrid_hits = []

    # --- 5. RRF 合并 + 中文 query rerank ------------------------------
    merged = _rrf_fuse([hybrid_hits, graph_hits, dense_hits], top_k=merge_top)
    effective_rerank_top_n = rerank_top_n
    if use_dynamic_topk and merged:
        effective_rerank_top_n = _compute_dynamic_rerank_top_n(
            query_text,
            merged,
            low_top_n=dynamic_low_rerank_top_n,
            high_top_n=dynamic_high_rerank_top_n,
            score_gap_threshold=dynamic_score_gap_threshold,
        )
    if use_prefilter and merged:
        merged = _prefilter_hits(
            merged,
            threshold=prefilter_threshold,
            keep_top_n=max(top_k, effective_rerank_top_n),
        )

    if use_rerank and rerank_async and merged:
        rerank_pre_top_n = _resolve_rerank_pre_top_n(
            query_text,
            merged,
            rerank_top_n=effective_rerank_top_n,
            hybrid_hit_count=len(hybrid_hits),
        )
        rerank_candidates = merged[:rerank_pre_top_n]
        try:
            reranked_hits = await rerank_async(
                query_text, rerank_candidates, top_k=top_k,
                semaphore=rerank_semaphore, timings=rerank_timings,
            )
            _record_rerank_trace(
                rerank_trace,
                use_rerank=True,
                candidates_before_rerank=rerank_candidates,
                returned_hits=reranked_hits,
                retrieval_stage="expanded",
                rerank_pre_top_n=rerank_pre_top_n,
            )
            return reranked_hits
        except (RuntimeError, TypeError, ValueError):
            fallback_hits = merged[:top_k]
            _record_rerank_trace(
                rerank_trace,
                use_rerank=True,
                candidates_before_rerank=rerank_candidates,
                returned_hits=fallback_hits,
                retrieval_stage="expanded",
                rerank_pre_top_n=rerank_pre_top_n,
                rerank_fallback=True,
            )

    final_hits = merged[:top_k]
    _record_rerank_trace(
        rerank_trace,
        use_rerank=False,
        candidates_before_rerank=final_hits,
        returned_hits=final_hits,
        retrieval_stage="expanded",
    )
    return final_hits


def _rrf_fuse(rank_lists: list[list[dict[str, Any]]], top_k: int, rrf_k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion for multiple ranked lists."""
    score_map: dict[str, float] = {}
    item_map: dict[str, dict[str, Any]] = {}
    label_map: dict[str, list[str]] = {}

    def _item_key(item: dict[str, Any]) -> str:
        chunk_id = str(item.get("chunk_id", "")).strip()
        if chunk_id:
            return f"chunk::{chunk_id}"
        material_id = str(item.get("material_id", "")).strip()
        text = str(item.get("content") or item.get("claim") or item.get("text") or "").strip()
        return f"mat::{material_id}::{hash(text)}"

    source_order = ["hybrid", "graph", "dense"]
    for list_index, rank_list in enumerate(rank_lists):
        branch_label = source_order[list_index] if list_index < len(source_order) else f"rank_list_{list_index + 1}"
        for rank, item in enumerate(rank_list):
            if not isinstance(item, dict):
                continue
            key = _item_key(item)
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in item_map:
                item_map[key] = dict(item)
                label_map[key] = []
            label_map[key] = merge_source_labels(label_map.get(key), item.get("source_labels"), branch_label)

    ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    fused: list[dict[str, Any]] = []
    for key, score in ranked:
        item = attach_source_labels(item_map[key], merge_source_labels(label_map.get(key), "rrf"))
        item["rrf_score"] = round(score, 6)
        fused.append(item)
    return fused


def _extract_prefilter_score(hit: dict[str, Any]) -> float:
    for key in ("rrf_score", "dense_score", "score"):
        value = hit.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _resolve_rerank_pre_top_n(
    query_text: str,
    hits: list[dict[str, Any]],
    *,
    rerank_top_n: int,
    hybrid_hit_count: int,
) -> int:
    requested = max(1, int(rerank_top_n))
    hard_cap = _configured_rerank_pre_top_n_hard_cap()
    profile = str(get_cost_profile() or "balanced").strip().lower()

    if profile == "aggressive":
        return min(requested, min(20, hard_cap))

    if profile == "quality":
        base_limit = min(50, hard_cap)
    else:
        base_limit = _configured_rerank_pre_top_n()

    top1 = _extract_prefilter_score(hits[0]) if len(hits) >= 1 else 0.0
    top2 = _extract_prefilter_score(hits[1]) if len(hits) >= 2 else 0.0
    short_query = len(str(query_text or "").strip()) < 6
    sparse_hybrid_hits = int(hybrid_hit_count) < 5
    uncertain_gap = len(hits) >= 2 and top1 < 0.6 and abs(top1 - top2) < 0.05
    should_expand = short_query or sparse_hybrid_hits or (short_query and uncertain_gap)
    target_limit = hard_cap if should_expand else base_limit
    return min(requested, max(1, target_limit))


def _is_high_risk_query_text(query_text: str) -> bool:
    q = str(query_text or "").strip().lower()
    if not q:
        return True
    if len(q) <= 4:
        return True
    risk_markers = (
        "为什么", "怎么", "如何", "区别", "比较", "机制", "原理",
        "why", "how", "difference", "compare",
    )
    return any(marker in q for marker in risk_markers)


def _compute_dynamic_rerank_top_n(
    query_text: str,
    hits: list[dict[str, Any]],
    *,
    low_top_n: int,
    high_top_n: int,
    score_gap_threshold: float,
) -> int:
    if not hits:
        return 0

    safe_low = max(1, int(low_top_n))
    safe_high = max(safe_low, int(high_top_n))
    pool_n = len(hits)

    if pool_n <= safe_low:
        return pool_n

    top_window = hits[: min(10, pool_n)]
    scores = [_extract_prefilter_score(h) for h in top_window]
    top1 = scores[0] if scores else 0.0
    tail = scores[-1] if scores else 0.0
    gap = top1 - tail

    low_confidence = top1 < max(0.10, float(score_gap_threshold))
    flat_ranking = gap < float(score_gap_threshold)
    high_risk_query = _is_high_risk_query_text(query_text)

    target = safe_high if (low_confidence or flat_ranking or high_risk_query) else safe_low
    return min(pool_n, target)


def _prefilter_hits(
    hits: list[dict[str, Any]],
    *,
    threshold: float,
    keep_top_n: int,
) -> list[dict[str, Any]]:
    """Filter low-score candidates before rerank.

    Guardrail: if threshold filters out all candidates, fallback to original top_n
    to avoid empty downstream retrieval.
    """
    if keep_top_n <= 0:
        return []

    base = hits[:keep_top_n]
    if threshold <= 0:
        return base

    filtered = [h for h in base if _extract_prefilter_score(h) >= threshold]
    return filtered if filtered else base


def run_eval(
    queries_path: str = DEFAULT_QUERIES_PATH,
    output_path: str = "BASELINE_METRICS.json",
    top_k: int = DEFAULT_TOP_K,
    recall_top_n: int = DEFAULT_RECALL_TOP_N,
    use_rerank: bool = DEFAULT_USE_RERANK,
    rerank_top_n: int = DEFAULT_RERANK_TOP_N,
    use_prefilter: bool = DEFAULT_USE_PREFILTER,
    prefilter_threshold: float = DEFAULT_PREFILTER_THRESHOLD,
    use_dynamic_topk: bool = DEFAULT_USE_DYNAMIC_TOPK,
    dynamic_low_rerank_top_n: int = DEFAULT_DYNAMIC_LOW_RERANK_TOP_N,
    dynamic_high_rerank_top_n: int = DEFAULT_DYNAMIC_HIGH_RERANK_TOP_N,
    dynamic_score_gap_threshold: float = DEFAULT_DYNAMIC_SCORE_GAP_THRESHOLD,
    use_expansion: bool = DEFAULT_USE_EXPANSION,
    use_contextual: bool = False,
    query_concurrency: int = DEFAULT_QUERY_CONCURRENCY,
    strict_cache_guard: bool = DEFAULT_STRICT_CACHE_GUARD,
    chunk_store_dir: str | None = None,
    embedding_cache_path: str | None = None,
    template_flags_path: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    progress_path: str | None = None,
    progress_every: int = 100,
    per_query_output: str | None = None,
    rerank_trace_output: str | None = None,
) -> dict[str, Any]:
    # 当前默认策略（Phase 5.2 分路路由修复后）：
    # - use_expansion=True：BM25/Graph 走中文原 query，Dense 走英文翻译，
    #   Rerank 走中文原 query。在翻译无效或无 API key 时优雅降级。
    # - recall_top_n=100 / rerank_top_n=40：提升召回深度与重排候选量，
    #   Qwen3-Reranker-8B 足以处理 top-40 而不显著拖累延迟（并发 8）。
    #
    # 后续调参建议：
    # 1) 若召回仍不足（Recall@10 偏低），把 recall_top_n 进一步上调到 150/200。
    # 2) 若排序不足（MRR 偏低），再上调 rerank_top_n 到 60，或尝试 --contextual。
    # 3) top_k 是产品展示策略（5 更精简，10 候选更多），不应替代检索质量调参。
    _enforce_resume_parity_guard(
        queries_path=queries_path,
        output_path=output_path,
        top_k=top_k,
        recall_top_n=recall_top_n,
        use_rerank=use_rerank,
        rerank_top_n=rerank_top_n,
        use_prefilter=use_prefilter,
        prefilter_threshold=prefilter_threshold,
        use_dynamic_topk=use_dynamic_topk,
        dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
        dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
        dynamic_score_gap_threshold=dynamic_score_gap_threshold,
        use_expansion=use_expansion,
        use_contextual=use_contextual,
        query_concurrency=query_concurrency,
        strict_cache_guard=strict_cache_guard,
        chunk_store_dir=chunk_store_dir,
        embedding_cache_path=embedding_cache_path,
        template_flags_path=template_flags_path,
        offset=offset,
        limit=limit,
        progress_path=progress_path,
        progress_every=progress_every,
        per_query_output=per_query_output,
        rerank_trace_output=rerank_trace_output,
    )
    queries = _load_queries(Path(queries_path))
    if offset or limit is not None:
        start = max(0, int(offset))
        end = start + int(limit) if limit is not None else None
        queries = queries[start:end]
    corpus = _load_retrieval_corpus(Path(chunk_store_dir)) if chunk_store_dir else _load_retrieval_corpus()

    # Phase 6: optionally prepend document-level context to chunks
    if use_contextual and batch_contextualize:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            contextualized_chunks = batch_contextualize(chunks)
            corpus = {**corpus, "chunks": contextualized_chunks}

    # Pre-build keyword graph once (Phase 3 perf fix)
    keyword_graph: dict[str, Any] | None = None
    if build_keyword_graph:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            keyword_graph = build_keyword_graph(chunks)

    # Wave 1: load template flags sidecar, used to tag results with is_template
    template_flags_map: dict[str, bool] | None = None
    if template_flags_path:
        flag_path = Path(template_flags_path)
        if flag_path.exists():
            template_flags_map = {}
            with flag_path.open("r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    rec = json.loads(stripped)
                    qid = rec.get("query_id")
                    if qid:
                        template_flags_map[qid] = bool(rec.get("is_template", False))

    # Run async portion (build vector store + batch embed queries + retrieve) in one event loop
    results = asyncio.run(
        _run_eval_async(
            queries,
            corpus,
            keyword_graph,
            top_k,
            recall_top_n=recall_top_n,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            use_prefilter=use_prefilter,
            prefilter_threshold=prefilter_threshold,
            use_dynamic_topk=use_dynamic_topk,
            dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
            dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
            dynamic_score_gap_threshold=dynamic_score_gap_threshold,
            use_expansion=use_expansion,
            query_concurrency=query_concurrency,
            strict_cache_guard=strict_cache_guard,
            embedding_cache_path=embedding_cache_path,
            template_flags_map=template_flags_map,
            progress_path=progress_path,
            progress_every=progress_every,
            per_query_output=per_query_output,
            rerank_trace_output=rerank_trace_output,
        )
    )

    summary = aggregate_metrics(results)
    payload = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_queries": len(queries),
        "oversize_count": int(corpus.get("oversize_count") or 0),
        "run_provenance": _build_run_provenance(
            queries_path=queries_path,
            evaluated_query_count=len(queries),
            top_k=top_k,
            recall_top_n=recall_top_n,
            use_rerank=use_rerank,
            rerank_top_n=rerank_top_n,
            use_prefilter=use_prefilter,
            prefilter_threshold=prefilter_threshold,
            use_dynamic_topk=use_dynamic_topk,
            dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
            dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
            dynamic_score_gap_threshold=dynamic_score_gap_threshold,
            use_expansion=use_expansion,
            use_contextual=use_contextual,
            query_concurrency=query_concurrency,
            strict_cache_guard=strict_cache_guard,
            chunk_store_dir=chunk_store_dir,
            embedding_cache_path=embedding_cache_path,
            template_flags_path=template_flags_path,
            offset=offset,
            limit=limit,
        ),
        **summary,
    }

    with Path(output_path).open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload


async def _run_eval_async(
    queries: list[dict[str, Any]],
    corpus: dict[str, Any],
    keyword_graph: dict[str, Any] | None,
    top_k: int,
    *,
    recall_top_n: int,
    use_rerank: bool,
    rerank_top_n: int,
    use_prefilter: bool,
    prefilter_threshold: float,
    use_dynamic_topk: bool,
    dynamic_low_rerank_top_n: int,
    dynamic_high_rerank_top_n: int,
    dynamic_score_gap_threshold: float,
    use_expansion: bool,
    query_concurrency: int = DEFAULT_QUERY_CONCURRENCY,
    strict_cache_guard: bool = DEFAULT_STRICT_CACHE_GUARD,
    embedding_cache_path: str | None = None,
    template_flags_map: dict[str, bool] | None = None,
    progress_path: str | None = None,
    progress_every: int = 100,
    per_query_output: str | None = None,
    rerank_trace_output: str | None = None,
) -> list[dict[str, Any]]:
    """Async eval loop — single event-loop, batch query embedding."""

    # Pre-build vector store (Phase 2 dense retrieval)
    vector_store = None
    if ChunkVectorStore is not None:
        chunks = corpus.get("chunks", []) if isinstance(corpus.get("chunks"), list) else []
        if chunks:
            filter_report = filter_embedding_safe_chunks(chunks)
            clean_chunks = filter_report["chunks"]
            oversize_count = filter_report["filtered_count"]
            if oversize_count > 0:
                logger.warning(
                    "Filtered %d/%d chunks outside embedding hard guard (%d tokens, %d chars)",
                    oversize_count,
                    len(chunks),
                    filter_report["hard_max_tokens"],
                    filter_report["hard_max_chars"],
                )
            cache_path = (
                Path(embedding_cache_path)
                if embedding_cache_path
                else Path("output") / "embedding_cache" / "corpus_embeddings.npy"
            )
            vector_store = await ChunkVectorStore.build(
                clean_chunks,
                cache_path=cache_path,
                strict_cache_guard=strict_cache_guard,
                concurrency=_get_env_int("EMBED_CONCURRENCY", 32),
            )

    # Pre-embed all query texts in batch (avoids 414 individual API calls)
    query_texts = [str(q.get("query_text", "")) for q in queries]
    query_vecs: list[Any] = [None] * len(queries)
    if vector_store is not None and vector_store.has_embeddings:
        try:
            query_vecs = await vector_store.batch_embed_queries(query_texts)
        except (RuntimeError, TypeError, ValueError):
            pass

    rerank_semaphore = asyncio.Semaphore(
        int(os.getenv("SILICONFLOW_RERANK_CONCURRENCY", str(DEFAULT_RERANK_CONCURRENCY)))
    ) if use_rerank else None

    # Tier 2 optimization: Increase concurrency from 5 to 10 (1-2s savings).
    # Override with WIKI_EXPANSION_CONCURRENCY env var for testing different concurrency levels.
    expansion_concurrency = int(os.getenv("WIKI_EXPANSION_CONCURRENCY", "10"))
    expansion_semaphore = asyncio.Semaphore(expansion_concurrency) if use_expansion else None

    if use_rerank and warm_rerank_live_candidate is not None:
        try:
            await warm_rerank_live_candidate()
        except (RuntimeError, TypeError, ValueError):
            pass

    # 查询级 gather 闸：避免 414 个协程同时挤在 rerank_semaphore 门口，
    # 导致 latency_ms 被"排队等"污染。默认与 rerank 并发对齐。
    query_gate = asyncio.Semaphore(max(1, int(query_concurrency)))
    progress_file = Path(progress_path) if progress_path else None
    per_query_file = Path(per_query_output) if per_query_output else None
    rerank_trace_file = Path(rerank_trace_output) if rerank_trace_output else None
    progress_lock = asyncio.Lock()
    progress_done = {"count": 0}
    safe_progress_every = max(1, int(progress_every)) if progress_file else 0

    async def _eval_one(i: int, q: dict[str, Any]) -> dict[str, Any]:
        async with query_gate:
            query_text = query_texts[i]
            difficulty = str(q.get("difficulty_level", "unknown"))
            evidence = q.get("evidence_set", []) if isinstance(q.get("evidence_set", []), list) else []
            expected_doc_ids = {
                str(item.get("doc_id", "")).strip() for item in evidence if isinstance(item, dict)
            }
            expected_doc_ids = {x for x in expected_doc_ids if x}

            rerank_timings: dict[str, float] = {}
            rerank_trace: dict[str, Any] | None = {} if rerank_trace_file else None
            t0 = time.perf_counter()
            hits = await _retrieve_with_expansion(
                query_text, corpus, top_k=top_k,
                keyword_graph=keyword_graph,
                vector_store=vector_store,
                query_vec=query_vecs[i],
                use_rerank=use_rerank,
                rerank_top_n=rerank_top_n,
                use_prefilter=use_prefilter,
                prefilter_threshold=prefilter_threshold,
                use_dynamic_topk=use_dynamic_topk,
                dynamic_low_rerank_top_n=dynamic_low_rerank_top_n,
                dynamic_high_rerank_top_n=dynamic_high_rerank_top_n,
                dynamic_score_gap_threshold=dynamic_score_gap_threshold,
                rerank_semaphore=rerank_semaphore,
                use_expansion=use_expansion,
                expansion_semaphore=expansion_semaphore,
                recall_top_n=recall_top_n,
                rerank_timings=rerank_timings,
                rerank_trace=rerank_trace,
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            relevance_list: list[bool] = []
            for hit in hits:
                if not isinstance(hit, dict):
                    relevance_list.append(False)
                    continue
                candidate_ids = _extract_candidate_doc_ids(hit)
                relevance_list.append(bool(candidate_ids.intersection(expected_doc_ids)))

            result = {
                "query_id": q.get("query_id"),
                "difficulty": difficulty,
                "latency_ms": latency_ms,
                "rerank_api_ms": rerank_timings.get("api_ms"),
                "rerank_queue_wait_ms": rerank_timings.get("queue_wait_ms"),
                "rerank_attempts": rerank_timings.get("attempts"),
                "recall_at_1": _calculate_recall_at_k(relevance_list, 1),
                "recall_at_3": _calculate_recall_at_k(relevance_list, 3),
                "recall_at_5": _calculate_recall_at_k(relevance_list, 5),
                "recall_at_10": _calculate_recall_at_k(relevance_list, 10),
                "mrr": _calculate_mrr(relevance_list),
                **(
                    {"is_template": bool(template_flags_map.get(q.get("query_id"), False))}
                    if template_flags_map is not None
                    else {}
                ),
            }
            if per_query_file or rerank_trace_file or (progress_file and safe_progress_every):
                async with progress_lock:
                    if per_query_file:
                        per_query_file.parent.mkdir(parents=True, exist_ok=True)
                        with per_query_file.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(result, ensure_ascii=False) + "\n")
                    if rerank_trace_file:
                        trace_record = {
                            "query_id": q.get("query_id"),
                            "difficulty": difficulty,
                            "query_text_sha256": hashlib.sha256(
                                query_text.encode("utf-8")
                            ).hexdigest(),
                            "expected_doc_ids": sorted(expected_doc_ids),
                            "top_k": int(top_k),
                            "recall_top_n": int(recall_top_n),
                            "requested_use_rerank": bool(use_rerank),
                            "rerank_top_n": int(rerank_top_n),
                            **(rerank_trace or {}),
                        }
                        if "returned_hits" not in trace_record:
                            trace_record["returned_hits"] = [
                                _trace_hit(hit, rank)
                                for rank, hit in enumerate(hits, start=1)
                                if isinstance(hit, dict)
                            ]
                        rerank_trace_file.parent.mkdir(parents=True, exist_ok=True)
                        with rerank_trace_file.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(trace_record, ensure_ascii=False) + "\n")
                    if progress_file and safe_progress_every:
                        progress_done["count"] += 1
                        done = progress_done["count"]
                        if done % safe_progress_every == 0 or done == len(queries):
                            snapshot = {
                                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "done": done,
                                "total": len(queries),
                                "percent": round(done / max(1, len(queries)) * 100, 2),
                                "last_query_id": result.get("query_id"),
                            }
                            progress_file.parent.mkdir(parents=True, exist_ok=True)
                            with progress_file.open("a", encoding="utf-8") as f:
                                f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
            return result

    results: list[dict[str, Any]] = list(
        await asyncio.gather(*[_eval_one(i, q) for i, q in enumerate(queries)])
    )
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation.")
    parser.add_argument("--queries", default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", default="BASELINE_METRICS.json")
    parser.add_argument(
        "--chunk-store-dir",
        type=str,
        default=None,
        help="可选：指定评测语料目录；可为 chunk_store root 或单个 v2 project manifest 目录。",
    )
    parser.add_argument(
        "--embedding-cache-path",
        type=str,
        default=None,
        help="可选：指定 dense embedding cache base .npy；实际文件仍会追加 contextual/model 后缀。",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="返回结果数（偏产品展示策略：5 更精简，10 候选更多）。",
    )
    parser.add_argument(
        "--recall-top-n",
        type=int,
        default=DEFAULT_RECALL_TOP_N,
        help="首轮召回深度；召回不足时优先上调到 80/100。",
    )
    parser.add_argument(
        "--rerank-top-n",
        type=int,
        default=DEFAULT_RERANK_TOP_N,
        help="重排候选深度；MRR 不足时可上调到 30/40。",
    )
    prefilter_group = parser.add_mutually_exclusive_group()
    prefilter_group.add_argument(
        "--prefilter",
        dest="use_prefilter",
        action="store_true",
        help="启用 rerank 前候选预筛（默认关闭）。",
    )
    prefilter_group.add_argument(
        "--no-prefilter",
        dest="use_prefilter",
        action="store_false",
        help="禁用 rerank 前候选预筛。",
    )
    parser.set_defaults(use_prefilter=DEFAULT_USE_PREFILTER)
    parser.add_argument(
        "--prefilter-threshold",
        type=float,
        default=DEFAULT_PREFILTER_THRESHOLD,
        help="预筛分数阈值（优先使用 rrf_score）。所有候选被过滤时会自动回退。",
    )
    dynamic_group = parser.add_mutually_exclusive_group()
    dynamic_group.add_argument(
        "--dynamic-topk",
        dest="use_dynamic_topk",
        action="store_true",
        help="启用动态 rerank 候选深度（默认关闭）。",
    )
    dynamic_group.add_argument(
        "--no-dynamic-topk",
        dest="use_dynamic_topk",
        action="store_false",
        help="禁用动态 rerank 候选深度。",
    )
    parser.set_defaults(use_dynamic_topk=DEFAULT_USE_DYNAMIC_TOPK)
    parser.add_argument(
        "--dynamic-low-rerank-top-n",
        type=int,
        default=DEFAULT_DYNAMIC_LOW_RERANK_TOP_N,
        help="动态TopK低风险候选深度。",
    )
    parser.add_argument(
        "--dynamic-high-rerank-top-n",
        type=int,
        default=DEFAULT_DYNAMIC_HIGH_RERANK_TOP_N,
        help="动态TopK高风险候选深度。",
    )
    parser.add_argument(
        "--dynamic-score-gap-threshold",
        type=float,
        default=DEFAULT_DYNAMIC_SCORE_GAP_THRESHOLD,
        help="动态TopK置信阈值（top1-尾部score差小于该值视为不确定）。",
    )
    parser.add_argument("--no-rerank", action="store_true")
    expansion_group = parser.add_mutually_exclusive_group()
    expansion_group.add_argument(
        "--expansion",
        dest="use_expansion",
        action="store_true",
        help="启用 query expansion（仅在评测确认有效时开启）。",
    )
    expansion_group.add_argument(
        "--no-expansion",
        dest="use_expansion",
        action="store_false",
        help="禁用 query expansion（默认）。",
    )
    parser.set_defaults(use_expansion=DEFAULT_USE_EXPANSION)
    parser.add_argument("--contextual", action="store_true")
    strict_guard_group = parser.add_mutually_exclusive_group()
    strict_guard_group.add_argument(
        "--strict-cache-guard",
        dest="strict_cache_guard",
        action="store_true",
        help="启用 embedding cache manifest/hash 硬校验（默认开启）。",
    )
    strict_guard_group.add_argument(
        "--no-strict-cache-guard",
        dest="strict_cache_guard",
        action="store_false",
        help="关闭 embedding cache 硬校验（不推荐，仅用于兼容旧缓存）。",
    )
    parser.set_defaults(strict_cache_guard=DEFAULT_STRICT_CACHE_GUARD)
    parser.add_argument(
        "--query-concurrency",
        type=int,
        default=DEFAULT_QUERY_CONCURRENCY,
        help="同时发起的 query 协程数；设为 1 时串行（对齐 Phase 4 原版）。",
    )
    parser.add_argument(
        "--template-flags",
        type=str,
        default=None,
        help="Wave 1: audit 工具产出的 template_flags.jsonl；载入后按 template/non_template 分桶输出指标。",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="评测查询起始偏移量（用于分段执行）。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="评测查询数量上限（用于分段执行）。",
    )
    parser.add_argument(
        "--progress",
        type=str,
        default=None,
        help="可选：追加写入评测进度 JSONL（心跳/断点观测）。",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="进度心跳间隔（每 N 条查询写一次）。",
    )
    parser.add_argument(
        "--per-query-output",
        type=str,
        default=None,
        help="可选：追加写入每条 query 质量结果 JSONL（中断后可复算）。",
    )
    parser.add_argument(
        "--rerank-trace-output",
        type=str,
        default=None,
        help="可选：追加写入非正文 rerank trace JSONL（ID/rank/score，用于诊断重排降级）。",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="将完整评测结果 JSON 打印到 stdout；仍会按 --output 写文件。",
    )
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    final_metrics = run_eval(
        queries_path=args.queries,
        output_path=args.output,
        top_k=args.top_k,
        recall_top_n=args.recall_top_n,
        use_rerank=not args.no_rerank,
        rerank_top_n=args.rerank_top_n,
        use_prefilter=args.use_prefilter,
        prefilter_threshold=args.prefilter_threshold,
        use_dynamic_topk=args.use_dynamic_topk,
        dynamic_low_rerank_top_n=args.dynamic_low_rerank_top_n,
        dynamic_high_rerank_top_n=args.dynamic_high_rerank_top_n,
        dynamic_score_gap_threshold=args.dynamic_score_gap_threshold,
        use_expansion=args.use_expansion,
        use_contextual=args.contextual,
        query_concurrency=args.query_concurrency,
        strict_cache_guard=args.strict_cache_guard,
        chunk_store_dir=args.chunk_store_dir,
        embedding_cache_path=args.embedding_cache_path,
        template_flags_path=args.template_flags,
        offset=args.offset,
        limit=args.limit,
        progress_path=args.progress,
        progress_every=args.progress_every,
        per_query_output=args.per_query_output,
        rerank_trace_output=args.rerank_trace_output,
    )
    if args.json_output:
        print(json.dumps(final_metrics, ensure_ascii=False))
        return final_metrics

    agg = final_metrics.get("aggregated_metrics", {})
    print("Evaluation completed.")
    print(
        f"Recall@5={agg.get('recall_at_5', 0.0)} | "
        f"MRR={agg.get('mrr', 0.0)} | "
        f"P95={agg.get('p95_latency_ms', 0.0)}ms | "
        f"API-p95={agg.get('rerank_api_p95_ms', 0.0)}ms | "
        f"Queue-p95={agg.get('rerank_queue_p95_ms', 0.0)}ms"
    )
    return final_metrics


if __name__ == "__main__":
    main()

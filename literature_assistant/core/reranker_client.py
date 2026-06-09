from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
import weakref
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import model_call_gateway as gateway_mod
import provider_rate_limit

from ai_cost_profile import rerank_cache_enabled, rerank_short_circuit_score_gap, rerank_telemetry_enabled
from chunk_size_guard import hard_max_chars, hard_max_tokens, inspect_text
from model_call_gateway import _compute_corpus_version, get_cached_call
from project_paths import output_path
from rerank_cache import candidate_cache_id
from runtime_env import _dotenv_disabled, env_value
from token_utils import count_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)

DEFAULT_SILICONFLOW_RERANKER_URL = "https://api.siliconflow.cn/v1/rerank"
DEFAULT_SILICONFLOW_RERANKER_MODEL = "qwen3-rerank"
DEFAULT_DASHSCOPE_RERANKER_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
DEFAULT_DASHSCOPE_RERANKER_MODEL = "qwen3-rerank"
DEFAULT_RERANKER_URL = DEFAULT_SILICONFLOW_RERANKER_URL
DEFAULT_RERANKER_MODEL = DEFAULT_SILICONFLOW_RERANKER_MODEL
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_BACKOFF_SECONDS = 60.0
BASE_BACKOFF_SECONDS = 0.5
SAFE_RERANK_DOC_TOKENS = 7500  # per-document token ceiling; leaves query headroom
# DashScope text rerank endpoints enforce an 8000-character per-document limit.
# Use 7500 to leave a small safety margin.
SAFE_RERANK_DOC_CHARS_DASHSCOPE = 7500
DEFAULT_RERANK_DAILY_CALL_CAP = 5000
DEFAULT_RERANK_DAILY_TOKEN_CAP = 1_500_000
DEFAULT_RERANK_DAILY_BUDGET_USD = 5.0
DEFAULT_RERANK_COST_PER_1K_TOKENS_USD = 0.001
_OUTPUT_DIR = output_path()
RERANK_BUDGET_STATE_PATH = _OUTPUT_DIR / "rerank_budget_state.json"
RERANK_COST_LOG_PATH = _OUTPUT_DIR / "rerank_cost.jsonl"
_RERANK_COST_LOG_LOCK = threading.Lock()
_GLOBAL_RERANK_BUDGET_GUARD = None
_KEY_PROBE_CACHE: dict[tuple[str, str, str], bool] = {}
_KEY_PROBE_TIMEOUT_S = 5.0
DEFAULT_RERANK_CREDENTIAL_COOLDOWN_SECONDS = 900.0
_RERANK_CREDENTIAL_COOLDOWN: dict[tuple[str, str, str], float] = {}
_RERANK_CREDENTIAL_COOLDOWN_LOCK = threading.Lock()
_RERANK_HTTP_TIMEOUT_SECONDS = 45.0
_RERANK_ASYNC_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[int, float, int, int], httpx.AsyncClient]] = weakref.WeakKeyDictionary()
_RERANK_ASYNC_CLIENTS_LOCK = threading.Lock()
_RERANK_PROVIDER_SEMAPHORES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[int, asyncio.Semaphore]] = weakref.WeakKeyDictionary()
_RERANK_PROVIDER_SEMAPHORES_LOCK = threading.Lock()
_RERANK_WARMED_CANDIDATES: set[tuple[str, str, str]] = set()
_RERANK_WARMED_CANDIDATES_LOCK = threading.Lock()


class _RerankGatewayStatusError(Exception):
    def __init__(self, response: Any, message: str | None = None) -> None:
        self.response = response
        super().__init__(message or f"Reranker API {getattr(response, 'status_code', 'error')}")


class _RerankBudgetBlocked(Exception):
    def __init__(self, decision: dict[str, Any]) -> None:
        self.decision = decision
        super().__init__(str(decision.get("reason") or "budget_capped"))


def is_dashscope_rerank_url(url: str | None) -> bool:
    return "dashscope.aliyuncs.com" in str(url or "")


def _looks_like_dashscope_rerank_model(model: str | None) -> bool:
    return str(model or "").strip().lower() == DEFAULT_DASHSCOPE_RERANKER_MODEL


def _probe_rerank_key(
    api_key: str,
    base_url: str,
    model: str,
    *,
    timeout: float = _KEY_PROBE_TIMEOUT_S,
) -> bool:
    if not api_key or not base_url or not model:
        return False

    cache_key = (base_url, model, api_key)
    cached = _KEY_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if is_dashscope_rerank_url(base_url):
        payload = {
            "model": model,
            "input": {"query": "probe", "documents": ["probe"]},
            "parameters": {"top_n": 1, "return_documents": False},
        }
    else:
        payload = {
            "model": model,
            "query": "probe",
            "documents": ["probe"],
            "top_n": 1,
        }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(base_url, headers=headers, json=payload)
        ok = 200 <= response.status_code < 300
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError):
        ok = False

    _KEY_PROBE_CACHE[cache_key] = ok
    if not ok:
        suffix = api_key[-4:] if len(api_key) >= 4 else "****"
        logger.warning(
            "Rerank key probe failed: base_url=%s model=%s key_len=%d key_suffix=***%s",
            base_url,
            model,
            len(api_key),
            suffix,
        )
    return ok


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def _rerank_request_token_count(query: str, documents: list[str]) -> int:
    return max(1, count_tokens(query)) + sum(max(1, count_tokens(doc)) for doc in documents)


def _rerank_http_pool_limits() -> tuple[int, int]:
    concurrency_hint = _env_positive_int(
        "MODEL_CALL_GATEWAY_RERANK_CONCURRENCY",
        _env_positive_int(
            "SILICONFLOW_RERANK_CONCURRENCY",
            _env_positive_int("RERANK_CONCURRENCY", 32),
        ),
    )
    max_connections = _env_positive_int("RERANK_HTTP_MAX_CONNECTIONS", max(32, concurrency_hint))
    max_keepalive = _env_positive_int("RERANK_HTTP_MAX_KEEPALIVE_CONNECTIONS", max_connections)
    return max_connections, max_keepalive


def _shared_rerank_async_client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    max_connections, max_keepalive = _rerank_http_pool_limits()
    client_factory = httpx.AsyncClient
    cache_key = (id(client_factory), _RERANK_HTTP_TIMEOUT_SECONDS, max_connections, max_keepalive)
    with _RERANK_ASYNC_CLIENTS_LOCK:
        clients_for_loop = _RERANK_ASYNC_CLIENTS.get(loop)
        if clients_for_loop is None:
            clients_for_loop = {}
            _RERANK_ASYNC_CLIENTS[loop] = clients_for_loop
        client = clients_for_loop.get(cache_key)
        if client is None:
            client = client_factory(
                timeout=_RERANK_HTTP_TIMEOUT_SECONDS,
                limits=httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive,
                ),
            )
            clients_for_loop[cache_key] = client
        return client


def _rerank_gateway_concurrency() -> int:
    return _env_positive_int(
        "MODEL_CALL_GATEWAY_RERANK_CONCURRENCY",
        _env_positive_int("SILICONFLOW_RERANK_CONCURRENCY", 3),
    )


def _shared_rerank_provider_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    limit = _rerank_gateway_concurrency()
    with _RERANK_PROVIDER_SEMAPHORES_LOCK:
        semaphores_for_loop = _RERANK_PROVIDER_SEMAPHORES.get(loop)
        if semaphores_for_loop is None:
            semaphores_for_loop = {}
            _RERANK_PROVIDER_SEMAPHORES[loop] = semaphores_for_loop
        semaphore = semaphores_for_loop.get(limit)
        if semaphore is None:
            semaphore = asyncio.Semaphore(limit)
            semaphores_for_loop[limit] = semaphore
        return semaphore


def _append_rerank_gateway_metric(
    *,
    cache_key_parts: dict[str, Any],
    started_at: float,
    retry_count: int,
    fallback_reason: str = "",
    budget_estimate_tokens: int = 0,
) -> None:
    gateway_mod._append_metric(
        {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "kind": "rerank",
            "stage": gateway_mod._normalize_stage("query"),
            "model": str(cache_key_parts.get("model") or ""),
            "task": str(cache_key_parts.get("task") or ""),
            "cache_status": "miss",
            "decision": "invoke",
            "retry_count": int(retry_count),
            "fallback_reason": fallback_reason,
            "budget_estimate_tokens": int(budget_estimate_tokens or 0),
            "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
        }
    )


def _rerank_live_warmup_enabled() -> bool:
    raw = str(os.getenv("RERANK_LIVE_WARMUP_ENABLED", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _warmup_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("RERANK_LIVE_WARMUP_TIMEOUT_SECONDS", "45")))
    except (TypeError, ValueError):
        return 45.0


def _build_rerank_payload(query: str, documents: list[str], *, model: str, base_url: str) -> dict[str, Any]:
    if is_dashscope_rerank_url(base_url):
        return {
            "model": model,
            "input": {"query": query, "documents": documents},
            "parameters": {"top_n": min(len(documents), 1), "return_documents": False},
        }
    return {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": min(len(documents), 1),
        "return_documents": False,
    }


async def warm_rerank_live_candidate(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, Any] | None:
    if not _rerank_live_warmup_enabled():
        return None

    candidate_entries = _ordered_rerank_candidates(api_key, base_url=base_url, model=model)
    available_candidates = [
        candidate
        for candidate in candidate_entries
        if not _is_rerank_candidate_cooled_down(candidate[0], candidate[1], candidate[2])
    ]
    if not available_candidates:
        return None

    candidate_api_key, candidate_base_url, candidate_model, candidate_source = available_candidates[0]
    candidate_signature = _rerank_candidate_signature(candidate_api_key, candidate_base_url, candidate_model)
    with _RERANK_WARMED_CANDIDATES_LOCK:
        if candidate_signature in _RERANK_WARMED_CANDIDATES:
            return {
                "warmed": False,
                "candidate_source": candidate_source,
                "candidate_model": candidate_model,
                "candidate_base_url": candidate_base_url,
                "reason": "already_warmed",
            }

    payload = _build_rerank_payload(
        "warmup",
        ["warmup"],
        model=candidate_model,
        base_url=candidate_base_url,
    )
    headers = {
        "Authorization": f"Bearer {candidate_api_key}",
        "Content-Type": "application/json",
    }

    started_at = time.perf_counter()
    try:
        client = _shared_rerank_async_client()
        response = await asyncio.wait_for(
            client.post(candidate_base_url, headers=headers, json=payload),
            timeout=_warmup_timeout_seconds(),
        )
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        if response.status_code != 200:
            logger.warning(
                "Rerank live warm-up failed: source=%s status=%s model=%s base_url=%s body=%s",
                candidate_source,
                response.status_code,
                candidate_model,
                candidate_base_url,
                str(getattr(response, "text", ""))[:240],
            )
            return {
                "warmed": False,
                "candidate_source": candidate_source,
                "candidate_model": candidate_model,
                "candidate_base_url": candidate_base_url,
                "status_code": response.status_code,
            }

        _rerank_log_call(
            model=candidate_model or "",
            n_docs=1,
            latency_ms=latency_ms,
            extra={
                "event": "warmup",
                "candidate_source": candidate_source,
                "base_url": candidate_base_url,
            },
        )
        with _RERANK_WARMED_CANDIDATES_LOCK:
            _RERANK_WARMED_CANDIDATES.add(candidate_signature)
        return {
            "warmed": True,
            "candidate_source": candidate_source,
            "candidate_model": candidate_model,
            "candidate_base_url": candidate_base_url,
            "latency_ms": latency_ms,
        }
    except asyncio.TimeoutError:
        logger.warning(
            "Rerank live warm-up timed out: source=%s model=%s base_url=%s timeout_s=%s",
            candidate_source,
            candidate_model,
            candidate_base_url,
            _warmup_timeout_seconds(),
        )
        return {
            "warmed": False,
            "candidate_source": candidate_source,
            "candidate_model": candidate_model,
            "candidate_base_url": candidate_base_url,
            "timeout": True,
        }
    except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
        logger.warning(
            "Rerank live warm-up errored: source=%s model=%s base_url=%s error=%s",
            candidate_source,
            candidate_model,
            candidate_base_url,
            exc,
        )
        return {
            "warmed": False,
            "candidate_source": candidate_source,
            "candidate_model": candidate_model,
            "candidate_base_url": candidate_base_url,
            "error": exc.__class__.__name__,
        }


def _clean(value: str | None) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _normalize_rerank_base_url(value: str | None) -> str | None:
    text = _clean(value)
    if text and is_dashscope_rerank_url(text) and "compatible-mode" in text.lower():
        return DEFAULT_DASHSCOPE_RERANKER_URL
    return text


def _rerank_candidate_signature(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> tuple[str, str, str]:
    return (
        str(api_key or "").strip(),
        str(_normalize_rerank_base_url(base_url) or ""),
        str(model or "").strip(),
    )


def _is_rerank_candidate_cooled_down(
    api_key: str,
    base_url: str,
    model: str,
) -> bool:
    sig = _rerank_candidate_signature(api_key, base_url, model)
    with _RERANK_CREDENTIAL_COOLDOWN_LOCK:
        until = _RERANK_CREDENTIAL_COOLDOWN.get(sig, 0.0)
    return until > time.time()


def _mark_rerank_candidate_cooldown(
    api_key: str,
    base_url: str,
    model: str,
    *,
    cooldown_seconds: float = DEFAULT_RERANK_CREDENTIAL_COOLDOWN_SECONDS,
) -> None:
    sig = _rerank_candidate_signature(api_key, base_url, model)
    with _RERANK_CREDENTIAL_COOLDOWN_LOCK:
        _RERANK_CREDENTIAL_COOLDOWN[sig] = time.time() + cooldown_seconds


def _resolve_rerank_targets(
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, str | None]:
    # Runtime override (Settings UI) takes precedence over .env for users
    # who configured a local BGE rerank server or a different SiliconFlow
    # account from the UI. The override file is small (4 fields) and
    # read once per resolve — see literature_assistant.core.rerank_runtime_config.
    try:
        from rerank_runtime_config import get_resolved_field as _rerank_override

        override_provider = _rerank_override("provider")
        override_base_url = _rerank_override("base_url")
        override_model = _rerank_override("model")
    except Exception:
        override_provider = override_base_url = override_model = None

    explicit_base_url = _normalize_rerank_base_url(base_url) or _normalize_rerank_base_url(override_base_url)
    explicit_model = _clean(model) or _clean(override_model)

    siliconflow_specific_api_key = env_value("SILICONFLOW_RERANK_API_KEY")
    siliconflow_generic_api_key = env_value("SILICONFLOW_API_KEY")
    dashscope_specific_api_key = env_value("DASHSCOPE_RERANK_API_KEY")
    dashscope_generic_api_key = env_value("DASHSCOPE_API_KEY")

    # Override api_key (when present) takes priority over env keys; it is
    # bucketed by the override provider hint so SiliconFlow / DashScope
    # selection downstream still picks the right candidate.
    try:
        from rerank_runtime_config import get_resolved_field as _rerank_override
        override_api_key = _rerank_override("api_key")
    except Exception:
        override_api_key = None
    if override_api_key:
        if (override_provider or "").lower() == "dashscope" or is_dashscope_rerank_url(explicit_base_url):
            dashscope_specific_api_key = override_api_key
        else:
            siliconflow_specific_api_key = override_api_key

    siliconflow_base_url = _normalize_rerank_base_url(env_value("SILICONFLOW_RERANK_BASE_URL"))
    dashscope_base_url = _normalize_rerank_base_url(env_value("DASHSCOPE_RERANK_BASE_URL"))
    legacy_base_url = _normalize_rerank_base_url(env_value("RERANK_BASE_URL"))

    siliconflow_model = env_value("SILICONFLOW_RERANK_MODEL")
    dashscope_model = env_value("DASHSCOPE_RERANK_MODEL")
    legacy_model = env_value("RERANK_MODEL")

    explicit_is_dashscope = is_dashscope_rerank_url(explicit_base_url) or _looks_like_dashscope_rerank_model(explicit_model)
    explicit_is_siliconflow = bool(explicit_base_url or explicit_model) and not explicit_is_dashscope

    if explicit_is_dashscope:
        provider = "dashscope"
    elif explicit_is_siliconflow:
        provider = "siliconflow"
    elif any(value is not None for value in (siliconflow_specific_api_key, siliconflow_generic_api_key, siliconflow_base_url, siliconflow_model)):
        provider = "siliconflow"
    elif any(value is not None for value in (dashscope_specific_api_key, dashscope_generic_api_key, dashscope_base_url, dashscope_model)):
        provider = "dashscope"
    elif is_dashscope_rerank_url(legacy_base_url) or _looks_like_dashscope_rerank_model(legacy_model):
        provider = "dashscope"
    else:
        provider = "siliconflow"

    use_legacy_dashscope = provider == "dashscope" and not any(
        value is not None for value in (dashscope_base_url, dashscope_model)
    )
    use_legacy_siliconflow = provider == "siliconflow" and not any(
        value is not None for value in (siliconflow_base_url, siliconflow_model)
    )

    dashscope_target_base_url = (
        explicit_base_url
        if explicit_is_dashscope and explicit_base_url
        else dashscope_base_url
        or (legacy_base_url if use_legacy_dashscope else None)
        or DEFAULT_DASHSCOPE_RERANKER_URL
    )
    dashscope_target_model = (
        explicit_model
        if explicit_is_dashscope and explicit_model
        else dashscope_model
        or (legacy_model if use_legacy_dashscope else None)
        or DEFAULT_DASHSCOPE_RERANKER_MODEL
    )
    siliconflow_target_base_url = (
        explicit_base_url
        if explicit_is_siliconflow and explicit_base_url
        else siliconflow_base_url
        or (legacy_base_url if use_legacy_siliconflow else None)
        or DEFAULT_SILICONFLOW_RERANKER_URL
    )
    siliconflow_target_model = (
        explicit_model
        if explicit_is_siliconflow and explicit_model
        else siliconflow_model
        or (legacy_model if use_legacy_siliconflow else None)
        or DEFAULT_SILICONFLOW_RERANKER_MODEL
    )

    resolved_base_url = dashscope_target_base_url if provider == "dashscope" else siliconflow_target_base_url
    resolved_model = dashscope_target_model if provider == "dashscope" else siliconflow_target_model

    return {
        "provider": provider,
        "explicit_base_url": explicit_base_url,
        "explicit_model": explicit_model,
        "resolved_base_url": resolved_base_url,
        "resolved_model": resolved_model,
        "siliconflow_specific_api_key": siliconflow_specific_api_key,
        "siliconflow_generic_api_key": siliconflow_generic_api_key,
        "dashscope_specific_api_key": dashscope_specific_api_key,
        "dashscope_generic_api_key": dashscope_generic_api_key,
        "legacy_api_key": env_value("RERANK_API_KEY"),
        "siliconflow_target_base_url": siliconflow_target_base_url,
        "siliconflow_target_model": siliconflow_target_model,
        "dashscope_target_base_url": dashscope_target_base_url,
        "dashscope_target_model": dashscope_target_model,
    }


def _rerank_candidates_from_key_pool(
    *,
    target_base_url: str | None = None,
    target_model: str | None = None,
) -> list[tuple[str, str, str, str]]:
    if _dotenv_disabled():
        return []
    try:
        from key_pool import get_pool
    except ImportError:
        return []

    try:
        credentials = get_pool().list("rerank")
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return []

    if not credentials:
        return []

    target_base_url = _normalize_rerank_base_url(target_base_url)
    target_model = _clean(target_model)
    ordered = sorted(
        credentials,
        key=lambda cred: (
            target_base_url is not None and _normalize_rerank_base_url(getattr(cred, "base_url", None)) != target_base_url,
            target_model is not None and _clean(getattr(cred, "model", None)) != target_model,
            int(getattr(cred, "line_no", 0) or 0),
        ),
    )

    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for cred in ordered:
        api_key = _clean(getattr(cred, "api_key", None))
        base_url = _normalize_rerank_base_url(getattr(cred, "base_url", None))
        model = _clean(getattr(cred, "model", None))
        if not api_key or not base_url or not model:
            continue
        sig = _rerank_candidate_signature(api_key, base_url, model)
        if sig in seen:
            continue
        seen.add(sig)
        provider = _clean(getattr(cred, "provider", None)) or "unknown"
        out.append((api_key, base_url, model, f"key-pool:{provider}"))
    return out


def resolve_rerank_candidates(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> list[tuple[str, str, str, str]]:
    explicit_api_key = _clean(api_key)
    targets = _resolve_rerank_targets(base_url=base_url, model=model)
    resolved_base_url = str(targets["resolved_base_url"] or DEFAULT_RERANKER_URL)
    resolved_model = str(targets["resolved_model"] or DEFAULT_RERANKER_MODEL)
    explicit_base_url = _normalize_rerank_base_url(base_url)
    explicit_model = _clean(model)

    if explicit_api_key is not None:
        return [(explicit_api_key, resolved_base_url, resolved_model, "explicit")]

    candidates: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    key_pool_candidates = _rerank_candidates_from_key_pool(
        target_base_url=explicit_base_url,
        target_model=explicit_model,
    )
    for candidate in key_pool_candidates:
        sig = _rerank_candidate_signature(candidate[0], candidate[1], candidate[2])
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append(candidate)

    env_candidates = [
        (
            _clean(targets["siliconflow_specific_api_key"]),
            str(targets["siliconflow_target_base_url"] or DEFAULT_SILICONFLOW_RERANKER_URL),
            str(targets["siliconflow_target_model"] or DEFAULT_SILICONFLOW_RERANKER_MODEL),
            "siliconflow-specific",
        ),
        (
            _clean(targets["dashscope_specific_api_key"]),
            str(targets["dashscope_target_base_url"] or DEFAULT_DASHSCOPE_RERANKER_URL),
            str(targets["dashscope_target_model"] or DEFAULT_DASHSCOPE_RERANKER_MODEL),
            "dashscope-specific",
        ),
        (
            _clean(targets["legacy_api_key"]),
            resolved_base_url,
            resolved_model,
            "legacy-rerank",
        ),
        (
            _clean(targets["siliconflow_generic_api_key"]),
            str(targets["siliconflow_target_base_url"] or DEFAULT_SILICONFLOW_RERANKER_URL),
            str(targets["siliconflow_target_model"] or DEFAULT_SILICONFLOW_RERANKER_MODEL),
            "siliconflow-generic",
        ),
        (
            _clean(targets["dashscope_generic_api_key"]),
            str(targets["dashscope_target_base_url"] or DEFAULT_DASHSCOPE_RERANKER_URL),
            str(targets["dashscope_target_model"] or DEFAULT_DASHSCOPE_RERANKER_MODEL),
            "dashscope-generic",
        ),
    ]

    for candidate_key, candidate_base_url, candidate_model, source in env_candidates:
        if not candidate_key:
            continue
        sig = _rerank_candidate_signature(candidate_key, candidate_base_url, candidate_model)
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append((candidate_key, candidate_base_url, candidate_model, source))

    if explicit_base_url or explicit_model:
        indexed_candidates = list(enumerate(candidates))
        indexed_candidates.sort(
            key=lambda pair: (
                explicit_base_url is not None and pair[1][1] != explicit_base_url,
                explicit_model is not None and pair[1][2] != explicit_model,
                pair[0],
            ),
        )
        candidates = [candidate for _idx, candidate in indexed_candidates]

    return candidates


def _ordered_rerank_candidates(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    probe_candidates: bool = True,
) -> list[tuple[str, str, str, str]]:
    candidates = resolve_rerank_candidates(api_key, base_url=base_url, model=model)
    if _clean(api_key) is not None:
        return candidates
    if not probe_candidates or env_value("RERANK_KEY_PROBE_DISABLE") == "1":
        return candidates

    viable: list[tuple[str, str, str, str]] = []
    for candidate_key, candidate_base_url, candidate_model, source in candidates:
        if _probe_rerank_key(candidate_key, candidate_base_url, candidate_model):
            logger.info("Rerank key selected: source=%s key_len=%d", source, len(candidate_key))
            viable.append((candidate_key, candidate_base_url, candidate_model, source))

    if viable:
        return viable
    if candidates:
        logger.warning(
            "All rerank key probes failed; falling back to static order (source=%s). Expect 401/403 downstream.",
            candidates[0][3],
        )
        return candidates

    logger.error("No rerank credential found in configured environment variables.")
    return []


def _static_rerank_fallback_candidate(
    candidates: list[tuple[str, str, str, str]],
    *,
    provider: str,
) -> tuple[str, str, str, str] | None:
    if not candidates:
        return None

    if provider == "dashscope":
        preferred_sources = (
            "dashscope-specific",
            "dashscope-generic",
            "legacy-rerank",
        )
    else:
        preferred_sources = (
            "siliconflow-specific",
            "siliconflow-generic",
            "legacy-rerank",
        )

    for source in preferred_sources:
        for candidate in candidates:
            if candidate[3] == source:
                return candidate
    return candidates[0]


def resolve_rerank_config(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
) -> tuple[str | None, str, str]:
    targets = _resolve_rerank_targets(base_url=base_url, model=model)
    resolved_base_url = str(targets["resolved_base_url"] or DEFAULT_RERANKER_URL)
    resolved_model = str(targets["resolved_model"] or DEFAULT_RERANKER_MODEL)
    candidates = resolve_rerank_candidates(api_key, base_url=base_url, model=model)
    if _clean(api_key) is not None:
        if candidates:
            candidate_key, candidate_base_url, candidate_model, _source = candidates[0]
            return candidate_key, candidate_base_url, candidate_model
        return _clean(api_key), resolved_base_url, resolved_model

    static_fallback = _static_rerank_fallback_candidate(
        candidates,
        provider=str(targets["provider"] or "siliconflow"),
    )

    if env_value("RERANK_KEY_PROBE_DISABLE") == "1":
        if static_fallback is not None:
            return static_fallback[0], static_fallback[1], static_fallback[2]
        return None, resolved_base_url, resolved_model

    for candidate_key, candidate_base_url, candidate_model, source in candidates:
        if _probe_rerank_key(candidate_key, candidate_base_url, candidate_model):
            logger.info("Rerank key selected: source=%s key_len=%d", source, len(candidate_key))
            return candidate_key, candidate_base_url, candidate_model

    if static_fallback is not None:
        logger.warning(
            "All rerank key probes failed; falling back to static order (source=%s). Expect 401/403 downstream.",
            static_fallback[3],
        )
        return static_fallback[0], static_fallback[1], static_fallback[2]

    return None, resolved_base_url, resolved_model


def _today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _daily_call_cap() -> int:
    return max(
        0,
        _env_int(
            "RERANK_DAILY_CALL_CAP",
            _env_int("RERANK_DAILY_BUDGET_CALLS", DEFAULT_RERANK_DAILY_CALL_CAP),
        ),
    )


def _daily_token_cap() -> int:
    return max(
        0,
        _env_int(
            "RERANK_DAILY_TOKEN_CAP",
            _env_int("RERANK_DAILY_BUDGET_TOKENS", DEFAULT_RERANK_DAILY_TOKEN_CAP),
        ),
    )


def _daily_budget_usd() -> float:
    return max(0.0, _env_float("RERANK_DAILY_BUDGET_USD", DEFAULT_RERANK_DAILY_BUDGET_USD))


def _estimated_rerank_cost_usd(token_count: int, model: str | None) -> float:
    _ = model
    return max(0.0, float(token_count) / 1000.0 * DEFAULT_RERANK_COST_PER_1K_TOKENS_USD)


class RerankBudgetGuard:
    def __init__(
        self,
        *,
        state_path: str | Path | None = None,
        telemetry_path: str | Path | None = None,
    ) -> None:
        self.state_path = Path(state_path) if state_path else RERANK_BUDGET_STATE_PATH
        self.telemetry_path = Path(telemetry_path) if telemetry_path else RERANK_COST_LOG_PATH
        self._lock = threading.Lock()

    def _default_state(self) -> dict[str, Any]:
        return {
            "date": _today_utc(),
            "call_count": 0,
            "token_count": 0,
            "cost_usd": 0.0,
        }

    def _read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return self._default_state()
        if not isinstance(data, dict):
            return self._default_state()
        return {
            "date": str(data.get("date") or _today_utc()),
            "call_count": max(0, int(data.get("call_count") or 0)),
            "token_count": max(0, int(data.get("token_count") or 0)),
            "cost_usd": max(0.0, float(data.get("cost_usd") or 0.0)),
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, self.state_path)

    def try_acquire(self, query: str, documents: list[str], *, model: str) -> dict[str, Any]:
        estimated_tokens = max(0, count_tokens(query)) + sum(max(0, count_tokens(doc)) for doc in documents)
        estimated_cost_usd = round(_estimated_rerank_cost_usd(estimated_tokens, model), 6)

        # 设置 RERANK_DISABLE_BUDGET=1 可完全跳过预算检查（适用于免费模型额度充足的场景）
        if os.getenv("RERANK_DISABLE_BUDGET", "").strip().lower() in ("1", "true", "yes"):
            return {
                "allowed": True,
                "event": None,
                "reason": None,
                "warning": None,
                "estimated_tokens": estimated_tokens,
                "estimated_cost_usd": 0.0,
                "state": {"budget_disabled": True},
            }

        today = _today_utc()

        with self._lock:
            state = self._read_state()
            if state["date"] != today:
                state = self._default_state()

            if state["call_count"] >= _daily_call_cap():
                return {
                    "allowed": False,
                    "event": "budget_capped",
                    "reason": "daily_call_cap",
                    "warning": "budget_capped",
                    "cap_dim": "call",
                    "estimated_tokens": estimated_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "state": state,
                }

            if state["token_count"] + estimated_tokens > _daily_token_cap():
                return {
                    "allowed": False,
                    "event": "budget_capped",
                    "reason": "daily_token_cap",
                    "warning": "budget_capped",
                    "cap_dim": "token",
                    "estimated_tokens": estimated_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "state": state,
                }

            next_state = {
                "date": today,
                "call_count": state["call_count"] + 1,
                "token_count": state["token_count"] + estimated_tokens,
                "cost_usd": round(state["cost_usd"] + estimated_cost_usd, 6),
            }
            self._write_state(next_state)
            usd_budget = _daily_budget_usd()
            if usd_budget > 0 and next_state["cost_usd"] > usd_budget:
                logger.warning(
                    "Rerank USD budget soft warning: cost_usd=%s budget_usd=%s",
                    next_state["cost_usd"],
                    usd_budget,
                )
                return {
                    "allowed": True,
                    "event": "budget_soft_warn",
                    "reason": "daily_budget_usd",
                    "warning": "budget_soft_warn",
                    "cap_dim": "usd",
                    "estimated_tokens": estimated_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "state": next_state,
                }
            return {
                "allowed": True,
                "event": None,
                "reason": None,
                "warning": None,
                "cap_dim": None,
                "estimated_tokens": estimated_tokens,
                "estimated_cost_usd": estimated_cost_usd,
                "state": next_state,
            }


def _get_rerank_budget_guard() -> RerankBudgetGuard:
    global _GLOBAL_RERANK_BUDGET_GUARD
    if (
        _GLOBAL_RERANK_BUDGET_GUARD is None
        or _GLOBAL_RERANK_BUDGET_GUARD.state_path != RERANK_BUDGET_STATE_PATH
        or _GLOBAL_RERANK_BUDGET_GUARD.telemetry_path != RERANK_COST_LOG_PATH
    ):
        _GLOBAL_RERANK_BUDGET_GUARD = RerankBudgetGuard()
    return _GLOBAL_RERANK_BUDGET_GUARD


def _rerank_log_call(
    *,
    model: str,
    n_docs: int,
    latency_ms: float,
    cached: bool = False,
    short_circuit: str | None = None,
    budget_blocked: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    if not rerank_telemetry_enabled():
        return

    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": str(model or ""),
        "n_docs": int(n_docs),
        "latency_ms": round(float(latency_ms), 2),
        "cached": bool(cached),
        "short_circuit": short_circuit,
        "budget_blocked": bool(budget_blocked),
    }
    if budget_blocked:
        record["event"] = "budget_capped"
    if extra:
        record.update({str(key): value for key, value in extra.items()})

    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _RERANK_COST_LOG_LOCK:
            RERANK_COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with RERANK_COST_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        pass


def _apply_scores_by_candidate_id(
    candidates: list[dict[str, Any]],
    score_by_candidate_id: dict[str, float],
    top_k: int,
    *,
    rerank_model: str | None = None,
    rerank_source: str | None = None,
) -> list[dict[str, Any]]:
    reranked: list[dict[str, Any]] = []
    for i, item in enumerate(candidates):
        cid = candidate_cache_id(item, i)
        updated = dict(item)
        updated["rerank_score"] = float(score_by_candidate_id.get(cid, _fallback_score(item)))
        try:
            from retrieval_provenance import attach_source_labels

            updated = attach_source_labels(updated, ["rerank"])
        except (ImportError, TypeError, ValueError):
            pass
        if rerank_model:
            updated["rerank_model"] = rerank_model
        if rerank_source:
            updated["rerank_source"] = rerank_source
        reranked.append(updated)
    reranked.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
    return reranked[:top_k]


def _parse_retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    try:
        ms = headers.get("retry-after-ms")
    except (AttributeError, TypeError):
        return None
    if ms is not None:
        try:
            value = float(ms) / 1000.0
            if value >= 0:
                return min(value, MAX_BACKOFF_SECONDS)
        except (TypeError, ValueError):
            pass
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
        if value >= 0:
            return min(value, MAX_BACKOFF_SECONDS)
    except (TypeError, ValueError):
        return None
    return None


def _compute_backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return retry_after + random.uniform(0.0, 0.1)
    delay = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
    return delay + random.uniform(0.0, delay)


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def _extract_document(item: dict[str, Any]) -> str:
    # raw_content 优先：content 可能注入上下文摘要前缀，
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


def _apply_fallback(
    candidates: list[dict[str, Any]],
    top_k: int,
    *,
    warning: str | None = None,
) -> list[dict[str, Any]]:
    preserved: list[dict[str, Any]] = []
    for item in candidates[:top_k]:
        updated = dict(item)
        updated["rerank_score"] = _fallback_score(item)
        updated["rerank_fallback"] = True
        try:
            from retrieval_provenance import attach_source_labels

            updated = attach_source_labels(updated, ["rerank_fallback"])
        except (ImportError, TypeError, ValueError):
            pass
        if warning:
            updated["warning"] = warning
        preserved.append(updated)
    return preserved


def _resolve_rerank_corpus_version(candidates: list[dict[str, Any]]) -> str:
    explicit_versions = {
        str(item.get("corpus_version") or "").strip()
        for item in candidates
        if str(item.get("corpus_version") or "").strip()
    }
    if len(explicit_versions) == 1:
        return next(iter(explicit_versions))

    project_ids = {
        str(item.get("project_id") or "").strip()
        for item in candidates
        if str(item.get("project_id") or "").strip()
    }
    if len(project_ids) == 1:
        try:
            return _compute_corpus_version(next(iter(project_ids)))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    return str(os.getenv("RERANK_CACHE_VERSION", "v1"))


def _validate_gateway_rerank_scores(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    try:
        for key, value in result.items():
            if not isinstance(key, str):
                return False
            float(value)
    except (TypeError, ValueError):
        return False
    return True


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
            - candidate_source / candidate_model / candidate_base_url: active live candidate
            - last_phase / last_status_code: last observed stage before return or cancellation
    """
    if top_k <= 0:
        raise ValueError(f"rerank_async: top_k must be positive, got {top_k!r}")
    if not candidates:
        return []
    # A11.R4.1: a single candidate has no reorder work — skip the provider call.
    if len(candidates) == 1:
        return candidates[:top_k]

    rerank_targets = _resolve_rerank_targets(base_url=base_url, model=model)
    resolved_model = str(rerank_targets["resolved_model"] or DEFAULT_RERANKER_MODEL)
    candidate_entries = _ordered_rerank_candidates(
        api_key,
        base_url=base_url,
        model=model,
    )
    available_candidates = [
        candidate
        for candidate in candidate_entries
        if not _is_rerank_candidate_cooled_down(candidate[0], candidate[1], candidate[2])
    ]

    # Short-circuit: incoming similarity scores already show a confident gap
    # between rank #1 and #2 — paying for a rerank is unlikely to change the
    # final ordering meaningfully. Threshold is env-tunable; 0 disables.
    _gap_threshold = rerank_short_circuit_score_gap()
    if _gap_threshold > 0 and len(candidates) >= 2:
        _scores_sorted = sorted(
            (_fallback_score(c) for c in candidates), reverse=True
        )
        if _scores_sorted[0] - _scores_sorted[1] >= _gap_threshold:
            _rerank_log_call(
                model=resolved_model or "",
                n_docs=len(candidates),
                latency_ms=0.0,
                short_circuit="score_gap",
                extra={"gap": round(_scores_sorted[0] - _scores_sorted[1], 4)},
            )
            return _apply_fallback(candidates, top_k)

    documents = [_extract_document(item) for item in candidates]
    valid_pairs = [(idx, doc) for idx, doc in enumerate(documents) if doc]
    if not valid_pairs:
        return _apply_fallback(candidates, top_k)

    oversize_hits: list[dict[str, int]] = []
    for orig_idx, doc in valid_pairs:
        metrics = inspect_text(doc)
        if metrics["is_oversize"]:
            oversize_hits.append(
                {
                    "candidate_index": orig_idx,
                    "char_count": int(metrics["char_count"]),
                    "token_count": int(metrics["token_count"]),
                }
            )
    if oversize_hits:
        _rerank_log_call(
            model=resolved_model or "",
            n_docs=len(candidates),
            latency_ms=0.0,
            short_circuit="oversize_skipped",
            extra={
                "event": "oversize_skipped",
                "oversize_count": len(oversize_hits),
                "first_oversize_index": oversize_hits[0]["candidate_index"],
                "max_char_count": max(item["char_count"] for item in oversize_hits),
                "max_token_count": max(item["token_count"] for item in oversize_hits),
                "chunk_hard_max_chars": hard_max_chars(),
                "chunk_hard_max_tokens": hard_max_tokens(),
            },
        )
        return _apply_fallback(candidates, top_k, warning="oversize_skipped")

    if not available_candidates:
        _rerank_log_call(
            model=resolved_model or "",
            n_docs=len(candidates),
            latency_ms=0.0,
            short_circuit="no_api_key",
        )
        return _apply_fallback(candidates, top_k, warning="no_api_key")

    cache_enabled = rerank_cache_enabled()

    def _prepare_candidate_context(
        candidate_api_key: str,
        candidate_base_url: str,
        candidate_model: str,
        candidate_source: str,
    ) -> dict[str, Any]:
        is_dashscope_candidate = is_dashscope_rerank_url(candidate_base_url)
        truncated_pairs: list[tuple[int, str]] = []
        for orig_idx, doc in valid_pairs:
            doc_tokens = count_tokens(doc)
            if doc_tokens > SAFE_RERANK_DOC_TOKENS:
                clipped = truncate_to_tokens(doc, SAFE_RERANK_DOC_TOKENS)
                logger.info(
                    "rerank: truncated doc #%d from %d to %d tokens",
                    orig_idx,
                    doc_tokens,
                    count_tokens(clipped),
                )
            else:
                clipped = doc
            if is_dashscope_candidate and len(clipped) > SAFE_RERANK_DOC_CHARS_DASHSCOPE:
                clipped = clipped[:SAFE_RERANK_DOC_CHARS_DASHSCOPE]
            truncated_pairs.append((orig_idx, clipped))

        docs_list = [doc for _, doc in truncated_pairs]
        top_n = min(top_k, len(truncated_pairs))
        if is_dashscope_candidate:
            payload: dict[str, Any] = {
                "model": candidate_model,
                "input": {"query": query, "documents": docs_list},
                "parameters": {"top_n": top_n, "return_documents": False},
            }
        else:
            payload = {
                "model": candidate_model,
                "query": query,
                "documents": docs_list,
                "top_n": top_n,
                "return_documents": False,
            }

        headers = {
            "Authorization": f"Bearer {candidate_api_key}",
            "Content-Type": "application/json",
        }
        cache_key_parts = {
            "model": candidate_model,
            "base_url": candidate_base_url,
            "query_normalized": _normalize_text(query).lower(),
            "candidate_chunk_ids": [candidate_cache_id(item, idx) for idx, item in enumerate(candidates)],
            "corpus_version": _resolve_rerank_corpus_version(candidates),
        }
        return {
            "api_key": candidate_api_key,
            "base_url": candidate_base_url,
            "model": candidate_model,
            "source": candidate_source,
            "is_dashscope": is_dashscope_candidate,
            "truncated_pairs": truncated_pairs,
            "docs_list": docs_list,
            "payload": payload,
            "headers": headers,
            "cache_key_parts": cache_key_parts,
        }

    prepared_candidates = [
        _prepare_candidate_context(candidate_api_key, candidate_base_url, candidate_model, candidate_source)
        for candidate_api_key, candidate_base_url, candidate_model, candidate_source in available_candidates
    ]

    for prepared in prepared_candidates:
        cache_hit, cached_scores = get_cached_call(
            kind="rerank",
            cache_key_parts=prepared["cache_key_parts"],
            budget_estimate_tokens=0,
            cache_enabled=cache_enabled,
            stage="query",
        )
        if cache_hit:
            if timings is not None:
                timings["queue_wait_ms"] = 0.0
                timings["api_ms"] = 0.0
                timings["attempts"] = 0
            _rerank_log_call(
                model=str(prepared["model"] or ""),
                n_docs=len(candidates),
                latency_ms=0.0,
                cached=True,
                extra={
                    "candidate_source": prepared["source"],
                    "base_url": prepared["base_url"],
                },
            )
            return _apply_scores_by_candidate_id(
                candidates,
                cached_scores,
                top_k,
                rerank_model=str(prepared["model"]),
                rerank_source=str(prepared["source"]),
            )

    _ctx = semaphore if semaphore is not None else _shared_rerank_provider_semaphore()
    t_call = time.perf_counter()
    async with _ctx:
        t_acquired = time.perf_counter()
        if timings is not None:
            timings["queue_wait_ms"] = (t_acquired - t_call) * 1000.0
        for prepared in prepared_candidates:
            candidate_api_key = str(prepared["api_key"])
            candidate_base_url = str(prepared["base_url"])
            candidate_model = str(prepared["model"])
            candidate_source = str(prepared["source"])
            is_dashscope_candidate = bool(prepared["is_dashscope"])
            truncated_pairs = list(prepared["truncated_pairs"])
            payload = dict(prepared["payload"])
            headers = dict(prepared["headers"])
            cache_key_parts = dict(prepared["cache_key_parts"])
            invoke_state: dict[str, float | int | str | None] = {
                "attempts": 0,
                "api_ms": 0.0,
                "budget_event": None,
                "budget_reason": None,
                "budget_warning": None,
                "budget_cap_dim": None,
                "estimated_tokens": None,
                "estimated_cost_usd": None,
                "last_phase": "candidate_selected",
                "last_status_code": None,
            }
            if timings is not None:
                timings["candidate_source"] = candidate_source
                timings["candidate_model"] = candidate_model
                timings["candidate_base_url"] = candidate_base_url
                timings["last_phase"] = "candidate_selected"

            async def _invoke_remote_once(
                *,
                _truncated_pairs: list[tuple[int, str]] = truncated_pairs,
                _candidate_model: str = candidate_model,
                _candidate_base_url: str = candidate_base_url,
                _headers: dict[str, str] = headers,
                _payload: dict[str, Any] = payload,
                _is_dashscope_candidate: bool = is_dashscope_candidate,
                _invoke_state: dict[str, float | int | str | None] = invoke_state,
            ) -> dict[str, float]:
                budget_decision = _get_rerank_budget_guard().try_acquire(
                    query,
                    [doc for _, doc in _truncated_pairs],
                    model=_candidate_model or "",
                )
                _invoke_state["budget_event"] = budget_decision["event"]
                _invoke_state["budget_reason"] = budget_decision["reason"]
                _invoke_state["budget_warning"] = budget_decision["warning"]
                _invoke_state["budget_cap_dim"] = budget_decision.get("cap_dim")
                _invoke_state["estimated_tokens"] = budget_decision["estimated_tokens"]
                _invoke_state["estimated_cost_usd"] = budget_decision["estimated_cost_usd"]
                _invoke_state["last_phase"] = "budget_checked"
                if timings is not None:
                    timings["last_phase"] = "budget_checked"
                if not budget_decision["allowed"]:
                    raise _RerankBudgetBlocked(budget_decision)

                _invoke_state["attempts"] = int(_invoke_state["attempts"]) + 1
                if timings is not None:
                    timings["attempts"] = int(_invoke_state["attempts"])
                    timings["last_phase"] = "provider_wait"
                await provider_rate_limit.maybe_wait_for_rate_limit_async(
                    _candidate_base_url,
                    kind="rerank",
                    token_count=_rerank_request_token_count(query, [doc for _, doc in _truncated_pairs]),
                )
                t_api = time.perf_counter()
                try:
                    client = _shared_rerank_async_client()
                    response = await client.post(_candidate_base_url, headers=_headers, json=_payload)
                except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
                    synthetic_response = type("SyntheticResponse", (), {"status_code": 503, "headers": {}, "text": str(exc)})()
                    raise _RerankGatewayStatusError(synthetic_response, str(exc)) from exc
                _invoke_state["api_ms"] = (time.perf_counter() - t_api) * 1000.0
                _invoke_state["last_status_code"] = int(getattr(response, "status_code", 0) or 0)
                _invoke_state["last_phase"] = "response_received"
                if timings is not None:
                    timings["api_ms"] = float(_invoke_state["api_ms"])
                    timings["last_status_code"] = int(_invoke_state["last_status_code"])
                    timings["last_phase"] = "response_received"

                if response.status_code != 200:
                    response_headers = dict(getattr(response, "headers", {}) or {})
                    retry_after = _parse_retry_after(response_headers)
                    if retry_after is not None:
                        response_headers["Retry-After"] = str(retry_after)
                    synthetic_response = type(
                        "GatewayResponse",
                        (),
                        {
                            "status_code": response.status_code,
                            "headers": response_headers,
                            "text": str(getattr(response, "text", "")),
                        },
                    )()
                    raise _RerankGatewayStatusError(synthetic_response)

                _invoke_state["last_phase"] = "parse"
                if timings is not None:
                    timings["last_phase"] = "parse"
                body = response.json() if hasattr(response, "json") else {}
                if _is_dashscope_candidate:
                    output = body.get("output", {}) if isinstance(body, dict) else {}
                    result_items = output.get("results", []) if isinstance(output, dict) else []
                else:
                    result_items = body.get("results", []) if isinstance(body, dict) else []
                if not isinstance(result_items, list) or not result_items:
                    raise ValueError("rerank result payload missing results")

                score_by_original_index: dict[int, float] = {}
                original_indices = [idx for idx, _ in _truncated_pairs]
                for raw in result_items:
                    if not isinstance(raw, dict):
                        continue
                    rerank_index = raw.get("index")
                    score = raw.get("relevance_score")
                    if not isinstance(rerank_index, int) or not isinstance(score, (int, float)):
                        continue
                    if 0 <= rerank_index < len(original_indices):
                        score_by_original_index[original_indices[rerank_index]] = float(score)

                return {
                    candidate_cache_id(item, idx): float(score_by_original_index.get(idx, _fallback_score(item)))
                    for idx, item in enumerate(candidates)
                }
            cache_key = gateway_mod._make_cache_key("rerank", cache_key_parts)
            metric_started_at = time.monotonic()
            retry_count = 0

            try:
                while True:
                    try:
                        score_by_candidate_id = await _invoke_remote_once()
                        gateway_mod._validate_result(score_by_candidate_id, _validate_gateway_rerank_scores)
                        if cache_enabled:
                            gateway_mod._write_cache("rerank", cache_key, cache_key_parts, score_by_candidate_id)
                        _append_rerank_gateway_metric(
                            cache_key_parts=cache_key_parts,
                            started_at=metric_started_at,
                            retry_count=retry_count,
                        )
                        break
                    except _RerankGatewayStatusError as exc:
                        if retry_count < gateway_mod.MAX_RETRIES - 1 and gateway_mod._is_retryable(exc):
                            retry_count += 1
                            await asyncio.sleep(gateway_mod._backoff_seconds(retry_count - 1, exc))
                            continue
                        _append_rerank_gateway_metric(
                            cache_key_parts=cache_key_parts,
                            started_at=metric_started_at,
                            retry_count=retry_count,
                            fallback_reason=exc.__class__.__name__,
                        )
                        raise
                    except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError):
                        _append_rerank_gateway_metric(
                            cache_key_parts=cache_key_parts,
                            started_at=metric_started_at,
                            retry_count=retry_count,
                            fallback_reason="ValueError",
                        )
                        raise
            except _RerankBudgetBlocked as exc:
                budget_decision = exc.decision
                _rerank_log_call(
                    model=candidate_model or "",
                    n_docs=len(candidates),
                    latency_ms=0.0,
                    budget_blocked=True,
                    extra={
                        "reason": budget_decision["reason"],
                        "cap_dim": budget_decision.get("cap_dim"),
                        "estimated_tokens": budget_decision["estimated_tokens"],
                        "estimated_cost_usd": budget_decision["estimated_cost_usd"],
                        "candidate_source": candidate_source,
                        "base_url": candidate_base_url,
                    },
                )
                return _apply_fallback(candidates, top_k, warning=budget_decision["warning"])
            except _RerankGatewayStatusError as exc:
                _mark_rerank_candidate_cooldown(candidate_api_key, candidate_base_url, candidate_model)
                logger.warning(
                    "Reranker candidate failed: source=%s status=%s model=%s base_url=%s body=%s",
                    candidate_source,
                    getattr(exc.response, "status_code", "error"),
                    candidate_model,
                    candidate_base_url,
                    str(getattr(exc.response, "text", ""))[:240],
                )
                continue
            except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as exc:  # pragma: no cover - unexpected parse errors
                _mark_rerank_candidate_cooldown(candidate_api_key, candidate_base_url, candidate_model)
                logger.warning(
                    "Reranker candidate failed: source=%s model=%s base_url=%s error=%s",
                    candidate_source,
                    candidate_model,
                    candidate_base_url,
                    exc,
                )
                continue

            if timings is not None:
                timings["api_ms"] = float(invoke_state["api_ms"])
                timings["attempts"] = int(invoke_state["attempts"])
                timings["last_phase"] = "done"
                timings["last_status_code"] = invoke_state["last_status_code"]
            if int(invoke_state["attempts"]) == 0:
                _rerank_log_call(
                    model=candidate_model or "",
                    n_docs=len(candidates),
                    latency_ms=0.0,
                    cached=True,
                    extra={
                        "candidate_source": candidate_source,
                        "base_url": candidate_base_url,
                    },
                )
            else:
                log_extra: dict[str, Any] = {
                    "attempts": int(invoke_state["attempts"]),
                    "candidate_source": candidate_source,
                    "base_url": candidate_base_url,
                }
                if invoke_state["budget_event"]:
                    log_extra.update(
                        {
                            "event": invoke_state["budget_event"],
                            "reason": invoke_state["budget_reason"],
                            "warning": invoke_state["budget_warning"],
                            "cap_dim": invoke_state["budget_cap_dim"],
                            "estimated_tokens": invoke_state["estimated_tokens"],
                            "estimated_cost_usd": invoke_state["estimated_cost_usd"],
                        }
                    )
                _rerank_log_call(
                    model=candidate_model or "",
                    n_docs=len(candidates),
                    latency_ms=float(invoke_state["api_ms"]),
                    extra=log_extra,
                )
            return _apply_scores_by_candidate_id(
                candidates,
                score_by_candidate_id,
                top_k,
                rerank_model=candidate_model,
                rerank_source=candidate_source,
            )

        _rerank_log_call(
            model=available_candidates[0][2] if available_candidates else resolved_model or "",
            n_docs=len(candidates),
            latency_ms=0.0,
            short_circuit="all_credentials_failed",
            extra={"candidate_count": len(available_candidates)},
        )
        return _apply_fallback(candidates, top_k, warning="all_credentials_failed")
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

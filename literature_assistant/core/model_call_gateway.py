from __future__ import annotations

import json
import os
import random
import tempfile
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Literal

from project_paths import output_path


GatewayKind = Literal["embedding", "rerank", "llm"]

GATEWAY_SCHEMA_VERSION = "1"
CHUNK_SCHEMA_VERSION = "2"
CHUNKING_VERSION = "800-150-v1"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 8.0
_DEFAULT_CONCURRENCY = {"embedding": 4, "rerank": 3, "llm": 2}
_METRICS_LOCK = threading.Lock()
_LLM_CACHE_LOCK = threading.Lock()
_LLM_CACHE: OrderedDict[str, Any] = OrderedDict()


def _env_concurrency(names: tuple[str, ...], default: int) -> int:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            continue
    return default


def _truthy_env(name: str, default: str = "1") -> bool:
    raw = str(os.getenv(name, default)).strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _cache_root() -> Path | None:
    raw = os.getenv("MODEL_CALL_GATEWAY_CACHE_DIR", str(output_path("model_gateway_cache")))
    if not raw or str(raw).strip().lower() in {"0", "false", "no", "off", "disabled"}:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _metrics_path() -> Path:
    return Path(os.getenv("MODEL_CALL_GATEWAY_METRICS_PATH", str(output_path("gateway_metrics.jsonl"))))


def _canonicalize_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonicalize_value(str(k), v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        items = [_canonicalize_value(key, item) for item in value]
        if key == "candidate_chunk_ids":
            return sorted(str(item) for item in items)
        return items
    return value


def _stable_json(payload: dict[str, Any]) -> str:
    normalized = {str(k): _canonicalize_value(str(k), v) for k, v in sorted(payload.items(), key=lambda item: str(item[0]))}
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _make_cache_key(kind: GatewayKind, cache_key_parts: dict[str, Any]) -> str:
    material = _stable_json(
        {
            "kind": kind,
            "schema_version": GATEWAY_SCHEMA_VERSION,
            "parts": cache_key_parts,
        }
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _disk_cache_path(kind: GatewayKind, cache_key: str) -> Path | None:
    root = _cache_root()
    if root is None:
        return None
    return root / kind / cache_key[:2] / f"{cache_key}.json"


def _read_disk_cache(kind: GatewayKind, cache_key: str) -> Any | None:
    path = _disk_cache_path(kind, cache_key)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload.get("value")


def _write_disk_cache(kind: GatewayKind, cache_key: str, value: Any) -> None:
    path = _disk_cache_path(kind, cache_key)
    if path is None:
        return
    try:
        serialized = json.dumps(
            {
                "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "value": value,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            tmp_path = Path(fh.name)
            fh.write(serialized)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _llm_cache_max_entries() -> int:
    try:
        return max(1, int(os.getenv("MODEL_CALL_GATEWAY_LLM_CACHE_SIZE", "256")))
    except (TypeError, ValueError):
        return 256


def _read_llm_cache(cache_key: str) -> Any | None:
    with _LLM_CACHE_LOCK:
        if cache_key not in _LLM_CACHE:
            return None
        value = deepcopy(_LLM_CACHE[cache_key])
        _LLM_CACHE.move_to_end(cache_key)
        return value


def _write_llm_cache(cache_key: str, value: Any) -> None:
    with _LLM_CACHE_LOCK:
        _LLM_CACHE[cache_key] = deepcopy(value)
        _LLM_CACHE.move_to_end(cache_key)
        while len(_LLM_CACHE) > _llm_cache_max_entries():
            _LLM_CACHE.popitem(last=False)


def _llm_cache_enabled(cache_key_parts: dict[str, Any]) -> bool:
    task = str(cache_key_parts.get("task") or "").strip().lower()
    if task == "generation":
        return _truthy_env("LLM_GENERATION_CACHE_ENABLED", "0")
    return True


def _read_cache(kind: GatewayKind, cache_key: str, cache_key_parts: dict[str, Any]) -> Any | None:
    if kind == "llm":
        if not _llm_cache_enabled(cache_key_parts):
            return None
        return _read_llm_cache(cache_key)
    return _read_disk_cache(kind, cache_key)


def _write_cache(kind: GatewayKind, cache_key: str, cache_key_parts: dict[str, Any], value: Any) -> None:
    if kind == "llm":
        if not _llm_cache_enabled(cache_key_parts):
            return
        _write_llm_cache(cache_key, value)
        return
    _write_disk_cache(kind, cache_key, value)


def _kind_semaphore(kind: GatewayKind) -> threading.BoundedSemaphore:
    attr = f"_SEMAPHORE_{kind.upper()}"
    limit_attr = f"{attr}_LIMIT"
    semaphore = globals().get(attr)
    if kind == "rerank":
        concurrency = _env_concurrency(
            (
                "MODEL_CALL_GATEWAY_RERANK_CONCURRENCY",
                "SILICONFLOW_RERANK_CONCURRENCY",
            ),
            _DEFAULT_CONCURRENCY[kind],
        )
    else:
        concurrency = _env_concurrency(
            (f"MODEL_CALL_GATEWAY_{kind.upper()}_CONCURRENCY",),
            _DEFAULT_CONCURRENCY[kind],
        )
    configured_concurrency = globals().get(limit_attr)
    if semaphore is None or configured_concurrency != concurrency:
        semaphore = threading.BoundedSemaphore(concurrency)
        globals()[attr] = semaphore
        globals()[limit_attr] = concurrency
    return semaphore


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    retry_after = headers.get("Retry-After")
    if retry_after is None:
        return None
    try:
        return max(0.0, float(retry_after))
    except (TypeError, ValueError):
        return None


def _status_code(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        return int(response.status_code)
    except (TypeError, ValueError):
        return None


def _is_retryable(exc: BaseException) -> bool:
    status = _status_code(exc)
    return status in RETRYABLE_STATUS_CODES


def _backoff_seconds(attempt: int, exc: BaseException) -> float:
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return retry_after
    base = min(BASE_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)
    return base + random.uniform(0.0, base)


def _append_metric(record: dict[str, Any]) -> None:
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    path = _metrics_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _METRICS_LOCK:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError:
        return


def _normalize_stage(stage: str | None) -> str:
    value = str(stage or "").strip().lower()
    return value or "unspecified"


def _validate_result(result: Any, validator: Callable[[Any], bool] | None) -> None:
    if validator is None:
        return
    if not validator(result):
        raise ValueError("schema validation failed for gateway result")


def _compute_corpus_version(project_id: str, chunk_store_root: Path | None = None) -> str:
    project_id = str(project_id or "").strip()
    if not project_id:
        raise ValueError("project_id is required")
    root = chunk_store_root or output_path("chunk_store")
    manifest_path = Path(root) / project_id / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    materials = payload.get("materials")
    if not isinstance(materials, dict):
        raise ValueError(f"manifest materials missing in {manifest_path}")
    material_hashes = sorted(
        str(entry.get("sha256") or "").strip()
        for entry in materials.values()
        if isinstance(entry, dict) and str(entry.get("sha256") or "").strip()
    )
    material = "\n".join([*material_hashes, CHUNK_SCHEMA_VERSION, CHUNKING_VERSION])
    return sha256(material.encode("utf-8")).hexdigest()


def gated_call(
    *,
    kind: GatewayKind,
    cache_key_parts: dict[str, Any],
    payload: Any,
    invoke: Callable[[], Any],
    budget_estimate_tokens: int = 0,
    skip_predicate: Callable[[], bool] | None = None,
    validate_result: Callable[[Any], bool] | None = None,
    cache_enabled: bool = True,
    on_decision: Callable[[str, str], None] | None = None,
    stage: str | None = None,
) -> Any:
    del payload
    started_at = time.monotonic()
    cache_key = _make_cache_key(kind, cache_key_parts)
    metric_stage = _normalize_stage(stage)

    def _notify(cache_status: str, decision: str) -> None:
        if on_decision is None:
            return
        on_decision(cache_status, decision)

    if cache_enabled:
        cache_hit = _read_cache(kind, cache_key, cache_key_parts)
        if cache_hit is not None:
            _notify("hit", "cache_hit")
            _append_metric(
                {
                    "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                    "kind": kind,
                    "stage": metric_stage,
                    "model": str(cache_key_parts.get("model") or ""),
                    "task": str(cache_key_parts.get("task") or ""),
                    "cache_status": "hit",
                    "decision": "cache_hit",
                    "retry_count": 0,
                    "fallback_reason": "",
                    "budget_estimate_tokens": int(budget_estimate_tokens or 0),
                    "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                }
            )
            return cache_hit

    if skip_predicate is not None and skip_predicate():
        _notify("miss", "skip")
        _append_metric(
            {
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "kind": kind,
                "stage": metric_stage,
                "model": str(cache_key_parts.get("model") or ""),
                "task": str(cache_key_parts.get("task") or ""),
                "cache_status": "miss",
                "decision": "skip",
                "retry_count": 0,
                "fallback_reason": "skip_predicate",
                "budget_estimate_tokens": int(budget_estimate_tokens or 0),
                "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
            }
        )
        return None

    semaphore = _kind_semaphore(kind)
    retry_count = 0
    with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                result = invoke()
                _validate_result(result, validate_result)
                if cache_enabled:
                    _write_cache(kind, cache_key, cache_key_parts, result)
                _notify("miss", "invoke")
                _append_metric(
                    {
                        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                        "kind": kind,
                        "stage": metric_stage,
                        "model": str(cache_key_parts.get("model") or ""),
                        "task": str(cache_key_parts.get("task") or ""),
                        "cache_status": "miss",
                        "decision": "invoke",
                        "retry_count": retry_count,
                        "fallback_reason": "",
                        "budget_estimate_tokens": int(budget_estimate_tokens or 0),
                        "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                    }
                )
                return result
            except Exception as exc:
                if attempt >= MAX_RETRIES - 1 or not _is_retryable(exc):
                    _notify("miss", "invoke")
                    _append_metric(
                        {
                            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                            "kind": kind,
                            "stage": metric_stage,
                            "model": str(cache_key_parts.get("model") or ""),
                            "task": str(cache_key_parts.get("task") or ""),
                            "cache_status": "miss",
                            "decision": "invoke",
                            "retry_count": retry_count,
                            "fallback_reason": exc.__class__.__name__,
                            "budget_estimate_tokens": int(budget_estimate_tokens or 0),
                            "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
                        }
                    )
                    raise
                retry_count += 1
                time.sleep(_backoff_seconds(attempt, exc))


def get_cached_call(
    *,
    kind: GatewayKind,
    cache_key_parts: dict[str, Any],
    budget_estimate_tokens: int = 0,
    cache_enabled: bool = True,
    on_decision: Callable[[str, str], None] | None = None,
    stage: str | None = None,
) -> tuple[bool, Any]:
    """Return a cached gateway result without entering provider semaphores."""
    if not cache_enabled:
        return False, None

    started_at = time.monotonic()
    cache_key = _make_cache_key(kind, cache_key_parts)
    metric_stage = _normalize_stage(stage)
    cache_hit = _read_cache(kind, cache_key, cache_key_parts)
    if cache_hit is None:
        return False, None

    if on_decision is not None:
        on_decision("hit", "cache_hit")
    _append_metric(
        {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "kind": kind,
            "stage": metric_stage,
            "model": str(cache_key_parts.get("model") or ""),
            "task": str(cache_key_parts.get("task") or ""),
            "cache_status": "hit",
            "decision": "cache_hit",
            "retry_count": 0,
            "fallback_reason": "",
            "budget_estimate_tokens": int(budget_estimate_tokens or 0),
            "latency_ms": round((time.monotonic() - started_at) * 1000, 2),
        }
    )
    return True, cache_hit


__all__ = [
    "CHUNK_SCHEMA_VERSION",
    "CHUNKING_VERSION",
    "GATEWAY_SCHEMA_VERSION",
    "_compute_corpus_version",
    "gated_call",
    "get_cached_call",
]

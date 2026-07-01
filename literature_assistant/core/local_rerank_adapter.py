# -*- coding: utf-8 -*-
"""Local cross-encoder rerank adapter — production drop-in for offline / firewalled env.

When upstream rerank API (DashScope / SiliconFlow / etc.) is unreachable due to:
  - outbound security policy (`dns_resolved_to_unsafe_ip`)
  - missing / 403 credentials
  - air-gapped deployment

…fall back to a locally-hosted cross-encoder (default ``BAAI/bge-reranker-v2-m3``)
that scores ``(query, candidate)`` pairs on-device. Weights live in the user's
``~/.cache/huggingface/hub`` and are loaded lazily on first call.

Design:
  - **Strict offline by default**: ``from_pretrained(local_files_only=True)``.
    No hub network reach unless ``LOCAL_RERANK_ALLOW_DOWNLOAD=1``.
  - **Two-stage probe**: ``is_available()`` checks env + transformers/torch import
    + tokenizer/weights cache presence WITHOUT actually loading the model.
  - **Lazy singleton**: weights load once per process on first ``score_pairs()``.
  - **Async surface**: ``ascore_pairs()`` runs the sync torch path in a worker
    thread via ``asyncio.to_thread`` so it does NOT block the FastAPI event loop.

Env knobs:
  - ``LOCAL_RERANK_MODEL_NAME``       default ``"BAAI/bge-reranker-v2-m3"``
  - ``LOCAL_RERANK_DEVICE``           default ``"cpu"`` (``"cuda"`` if GPU available)
  - ``LOCAL_RERANK_MAX_LENGTH``       default ``512``  (clamped to [16, 8192])
  - ``LOCAL_RERANK_BATCH_SIZE``       default ``8``    (clamped to [1, 128])
  - ``LOCAL_RERANK_DISABLED``         default unset; ``"1"/"true"/"yes"`` → fail-closed
  - ``LOCAL_RERANK_ALLOW_DOWNLOAD``   default unset; ``"1"/"true"/"yes"`` → allow HF hub
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
_DEFAULT_MAX_LEN = 512
_DEFAULT_BATCH = 8

# Clamp ranges defend against bad env values without crashing.
_MAX_LEN_MIN, _MAX_LEN_MAX = 16, 8192
_BATCH_MIN, _BATCH_MAX = 1, 128

_LOCAL_RERANKER: Any = None
_LOCAL_RERANKER_LOADED = False
_LOCAL_RERANKER_NAME: str | None = None


def _detect_default_device() -> str:
    """Pick the most efficient device available without forcing it.

    Returns ``"cuda"`` when a working CUDA-enabled torch is importable,
    otherwise ``"cpu"``. The detection happens lazily (only when this
    function is called) so importing the module on a CPU-only box does
    NOT pay the torch import cost.

    Why dynamic default:
        Main pipeline is API-first (SiliconFlow / DashScope rerank), so
        local rerank only runs when the configured API path is unavailable. When it does fire, picking
        CPU on a GPU box wastes the user's hardware and produces 3+s
        latencies; picking CUDA on a CPU box crashes at model load.
        Auto-detection makes the fallback fast without surprising
        CPU-only users.

    Override:
        Set ``LOCAL_RERANK_DEVICE`` env var to force ``"cpu"`` /
        ``"cuda"`` / ``"cuda:0"`` etc. — bypasses detection entirely.
    """
    try:
        import torch  # local import — keeps adapter importable offline
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _is_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _is_disabled() -> bool:
    return _is_truthy("LOCAL_RERANK_DISABLED")


def _allow_download() -> bool:
    return _is_truthy("LOCAL_RERANK_ALLOW_DOWNLOAD")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    """Parse env var to int, clamp to [lo, hi]. Bad value → default (no crash)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        logger.warning("local_rerank_adapter: %s=%r is not int; using default %d", name, raw, default)
        return default
    return max(lo, min(hi, val))


def _model_name() -> str:
    return os.environ.get("LOCAL_RERANK_MODEL_NAME", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _hf_cache_dir() -> Path:
    """Return the HF hub cache root, honoring HF_HOME if set."""
    hf_home = os.environ.get("HF_HOME", "").strip()
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _model_cache_dir(model_name: str) -> Path:
    """Map ``BAAI/bge-reranker-v2-m3`` → cache directory under hub/."""
    safe = "models--" + model_name.replace("/", "--")
    return _hf_cache_dir() / safe


def _weights_present(model_name: str) -> bool:
    """Cheap on-disk probe — does NOT load torch / transformers.

    Returns True iff ``snapshots/<hash>/`` contains at least one weights file
    (``model.safetensors`` or ``pytorch_model.bin``) AND a tokenizer file.
    """
    cache = _model_cache_dir(model_name)
    if not cache.exists():
        return False
    snapshots = cache / "snapshots"
    if not snapshots.exists():
        return False
    for snap in snapshots.iterdir():
        if not snap.is_dir():
            continue
        has_weights = any(
            (snap / fn).exists() for fn in ("model.safetensors", "pytorch_model.bin")
        )
        has_tokenizer = any(
            (snap / fn).exists()
            for fn in ("tokenizer.json", "tokenizer_config.json", "sentencepiece.bpe.model")
        )
        if has_weights and has_tokenizer:
            return True
    return False


def is_available() -> bool:
    """Cheap probe — does NOT load weights or torch modules.

    Returns False when:
      - ``LOCAL_RERANK_DISABLED=1`` (fail-closed)
      - ``transformers`` or ``torch`` not importable
      - model weights are NOT present in HF cache AND ``LOCAL_RERANK_ALLOW_DOWNLOAD``
        is not set (strict-offline default)
    """
    if _is_disabled():
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    if _weights_present(_model_name()):
        return True
    return _allow_download()


def _missing_dependency_names() -> list[str]:
    """Return missing import packages required by in-process local loading."""
    missing: list[str] = []
    if importlib.util.find_spec("torch") is None:
        missing.append("torch")
    if importlib.util.find_spec("transformers") is None:
        missing.append("transformers")
    return missing


def _unavailable_reason(model_name: str) -> str:
    """Explain why in-process local loading cannot be invoked safely."""
    if _is_disabled():
        return "LOCAL_RERANK_DISABLED=1 已关闭本机进程加载。"
    missing = _missing_dependency_names()
    if missing:
        return f"缺少 Python 依赖：{', '.join(missing)}。"
    if not _weights_present(model_name) and not _allow_download():
        return "模型权重未在缓存中，且未设置 LOCAL_RERANK_ALLOW_DOWNLOAD=1。"
    return ""


def get_status() -> dict[str, Any]:
    """Aggregate status snapshot for UI / settings endpoints.

    Does NOT load model weights or import torch eagerly beyond
    detection (the same lazy probes ``is_available()`` uses). Safe to
    call on every Settings page render — runs in well under 1ms on a
    warm process.

    The returned dict is the contract that frontends should render as a
    status chip / badge. Field semantics:

    - ``available`` — true when in-process local loading can actually be invoked
      (weights on disk OR download allowed + libs importable + not
      disabled). Frontend should show a green chip; false → red chip.
    - ``disabled`` — true when ``LOCAL_RERANK_DISABLED=1``. Distinct
      from "available=false because no weights" — disabled is an
      operator opt-out, not a missing dependency.
    - ``weights_present`` — true when the HF cache has the chosen
      model. Frontend can show "Click to download (XX MB)" when false
      and ``allow_download=true``.
    - ``allow_download`` — true when ``LOCAL_RERANK_ALLOW_DOWNLOAD=1``;
      controls whether ``is_available()`` returns true on a fresh box.
    - ``model_name`` — currently selected model. Users who want to
      swap to a different open-source reranker set
      ``LOCAL_RERANK_MODEL_NAME`` env var (see workspace docs).
    - ``device`` — resolved device that ``_get_reranker()`` would pick
      if invoked right now. ``"cuda"`` / ``"cpu"`` / explicit override.
    - ``max_length`` / ``batch_size`` — runtime knobs the user has
      set via env (or defaults).
    - ``loaded`` — true when the model has actually been pulled into
      memory this process. Always false on a cold worker.

    Why a single aggregator: the frontend can render the entire local-
    rerank state from one HTTP round-trip; without this it would have
    to probe weights, env vars, and torch separately, leaking
    implementation details into the UI layer.
    """
    model_name = _model_name()
    device_env_override = os.environ.get("LOCAL_RERANK_DEVICE", "").strip() or None
    available = is_available()
    return {
        "available": available,
        "disabled": _is_disabled(),
        "weights_present": _weights_present(model_name),
        "allow_download": _allow_download(),
        "model_name": model_name,
        "device": device_env_override or _detect_default_device(),
        "device_source": "env_override" if device_env_override else "auto_detected",
        "max_length": _env_int(
            "LOCAL_RERANK_MAX_LENGTH",
            _DEFAULT_MAX_LEN,
            _MAX_LEN_MIN,
            _MAX_LEN_MAX,
        ),
        "batch_size": _env_int(
            "LOCAL_RERANK_BATCH_SIZE",
            _DEFAULT_BATCH,
            _BATCH_MIN,
            _BATCH_MAX,
        ),
        "loaded": _LOCAL_RERANKER is not None and _LOCAL_RERANKER_LOADED,
        "hf_cache_dir": str(_hf_cache_dir()),
        "unavailable_reason": "" if available else _unavailable_reason(model_name),
    }


def _get_reranker() -> Any:
    """Lazy singleton — returns ``(tokenizer, model, device, torch)`` or None."""
    global _LOCAL_RERANKER, _LOCAL_RERANKER_LOADED, _LOCAL_RERANKER_NAME
    if _LOCAL_RERANKER_LOADED:
        return _LOCAL_RERANKER

    _LOCAL_RERANKER_LOADED = True

    if _is_disabled():
        logger.info("local_rerank_adapter: LOCAL_RERANK_DISABLED=1; skipping model load")
        _LOCAL_RERANKER = None
        return None

    model_name = _model_name()
    device = (
        os.environ.get("LOCAL_RERANK_DEVICE", "").strip()
        or _detect_default_device()
    )

    # Strict-offline guard: don't even try if weights missing and download not allowed.
    if not _weights_present(model_name) and not _allow_download():
        logger.warning(
            "local_rerank_adapter: weights for %s not in HF cache and "
            "LOCAL_RERANK_ALLOW_DOWNLOAD unset; rerank unavailable",
            model_name,
        )
        _LOCAL_RERANKER = None
        return None

    try:
        import torch  # type: ignore
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore
    except ImportError as exc:
        logger.warning(
            "local_rerank_adapter: transformers/torch not installed (%s); rerank unavailable",
            exc,
        )
        _LOCAL_RERANKER = None
        return None

    local_only = not _allow_download()
    if local_only:
        # local_files_only=True 仍会试 HEAD 请求查 ETag(transformers 内部行为)。
        # 真正禁网必须设这俩 env,且要在 import transformers 前或 from_pretrained 前。
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=False, local_files_only=local_only
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name, trust_remote_code=False, local_files_only=local_only
        )
        model.eval()
        if device != "cpu":
            try:
                model = model.to(device)
            except Exception as dev_exc:  # noqa: BLE001
                logger.warning(
                    "local_rerank_adapter: device=%s failed (%s); fallback to cpu", device, dev_exc
                )
                device = "cpu"
        _LOCAL_RERANKER = (tokenizer, model, device, torch)
        _LOCAL_RERANKER_NAME = model_name
        logger.info(
            "local_rerank_adapter: loaded %s on %s (local_only=%s)",
            model_name, device, local_only,
        )
        return _LOCAL_RERANKER
    except Exception as exc:  # noqa: BLE001 - hub miss / corrupt cache / OOM all routed here
        logger.warning(
            "local_rerank_adapter: load failed for %s (%s); rerank unavailable",
            model_name, exc,
        )
        _LOCAL_RERANKER = None
        return None


def reset_for_tests() -> None:
    """Force the singleton to reload on next ``_get_reranker()`` call.

    Test-only — call after monkey-patching env / imports between cases.
    """
    global _LOCAL_RERANKER, _LOCAL_RERANKER_LOADED, _LOCAL_RERANKER_NAME
    _LOCAL_RERANKER = None
    _LOCAL_RERANKER_LOADED = False
    _LOCAL_RERANKER_NAME = None


def _score_pairs_sync(query: str, candidate_texts: list[str]) -> list[float] | None:
    """Internal sync scoring — used by both sync and async public surfaces."""
    if not candidate_texts:
        return []
    if not query:
        return None

    bundle = _get_reranker()
    if bundle is None:
        return None
    tokenizer, model, device, torch = bundle

    max_length = _env_int("LOCAL_RERANK_MAX_LENGTH", _DEFAULT_MAX_LEN, _MAX_LEN_MIN, _MAX_LEN_MAX)
    batch_size = _env_int("LOCAL_RERANK_BATCH_SIZE", _DEFAULT_BATCH, _BATCH_MIN, _BATCH_MAX)

    scores: list[float] = []
    with torch.no_grad():
        for start in range(0, len(candidate_texts), batch_size):
            batch = candidate_texts[start : start + batch_size]
            pairs = [[query, t or ""] for t in batch]
            encoded = tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            if device != "cpu":
                encoded = {k: v.to(device) for k, v in encoded.items()}
            logits = model(**encoded).logits.view(-1).float().cpu().tolist()
            scores.extend(logits)
    return scores


def score_pairs(query: str, candidate_texts: list[str]) -> list[float] | None:
    """Sync scoring (Block while loading + inference).

    For use in scripts / sync code paths only. async retriever MUST use
    ``ascore_pairs()`` instead — calling this from an event loop blocks it.
    """
    return _score_pairs_sync(query, candidate_texts)


async def ascore_pairs(query: str, candidate_texts: list[str]) -> list[float] | None:
    """Async wrapper — runs the sync torch path in a worker thread.

    This is the production-safe entry point for the async retriever:
      - Model load (first call, ~5-10 sec) does NOT block the event loop
      - Inference (1-2 sec per pair on CPU) does NOT block the event loop
    """
    import asyncio
    return await asyncio.to_thread(_score_pairs_sync, query, candidate_texts)


def rerank_dicts(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    text_keys: tuple[str, ...] = ("content", "claim", "text", "raw_content"),
    score_key: str = "rerank_score",
) -> list[dict[str, Any]] | None:
    """Convenience: score candidates dicts, inject ``rerank_score``, sort desc.

    Picks the first non-empty value among ``text_keys`` for each candidate.
    Returns ``None`` if scoring is unavailable (caller falls back further).
    """
    if not candidates:
        return list(candidates)

    def _pick_text(c: dict[str, Any]) -> str:
        for k in text_keys:
            v = c.get(k)
            if v:
                return str(v)
        return ""

    texts = [_pick_text(c) for c in candidates]
    scores = _score_pairs_sync(query, texts)
    if scores is None:
        return None

    out: list[dict[str, Any]] = []
    for c, s in zip(candidates, scores):
        cc = dict(c)
        cc[score_key] = float(s)
        out.append(cc)
    out.sort(key=lambda x: float(x.get(score_key) or 0.0), reverse=True)
    return out


async def arerank_dicts(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    text_keys: tuple[str, ...] = ("content", "claim", "text", "raw_content"),
    score_key: str = "rerank_score",
) -> list[dict[str, Any]] | None:
    """Async version of ``rerank_dicts`` for event-loop callers."""
    if not candidates:
        return list(candidates)

    def _pick_text(c: dict[str, Any]) -> str:
        for k in text_keys:
            v = c.get(k)
            if v:
                return str(v)
        return ""

    texts = [_pick_text(c) for c in candidates]
    scores = await ascore_pairs(query, texts)
    if scores is None:
        return None

    out: list[dict[str, Any]] = []
    for c, s in zip(candidates, scores):
        cc = dict(c)
        cc[score_key] = float(s)
        out.append(cc)
    out.sort(key=lambda x: float(x.get(score_key) or 0.0), reverse=True)
    return out

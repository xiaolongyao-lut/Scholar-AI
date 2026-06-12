# -*- coding: utf-8 -*-
"""Local embedding adapter — production drop-in for offline / firewalled env.

When upstream embedding API (SiliconFlow / DashScope / etc.) is unreachable due to:
  - outbound security policy (``dns_resolved_to_unsafe_ip``)
  - missing / 403 credentials
  - air-gapped deployment

…fall back to a locally-hosted sentence encoder (default
``BAAI/bge-m3``) that returns dense vectors on-device. Weights live in the
user's ``~/.cache/huggingface/hub`` and are loaded lazily on first call.

Mirrors ``local_rerank_adapter.py`` design — same env knobs, same status
contract, same lazy probe pattern — so the Settings UI can render both
with one chip pattern.

Design:
  - **Strict offline by default**: weights must already be on disk unless
    ``LOCAL_EMBEDDING_ALLOW_DOWNLOAD=1``.
  - **Two-stage probe**: ``is_available()`` checks env + sentence-
    transformers/torch importability + weights cache presence WITHOUT
    actually loading the model.
  - **Lazy singleton**: weights load once per process on first
    ``encode_texts()``.
  - **Async surface**: ``aencode_texts()`` runs the sync torch path in a
    worker thread via ``asyncio.to_thread`` so it does NOT block the
    FastAPI event loop.

Env knobs (mirror LOCAL_RERANK_*):
  - ``LOCAL_EMBEDDING_MODEL_NAME``       default ``"BAAI/bge-m3"``
  - ``LOCAL_EMBEDDING_DEVICE``           default ``"cpu"`` (``"cuda"`` if available)
  - ``LOCAL_EMBEDDING_BATCH_SIZE``       default ``32``    (clamped to [1, 256])
  - ``LOCAL_EMBEDDING_DISABLED``         default unset; ``"1"/"true"/"yes"`` → fail-closed
  - ``LOCAL_EMBEDDING_ALLOW_DOWNLOAD``   default unset; ``"1"/"true"/"yes"`` → allow HF hub
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-m3"
_DEFAULT_BATCH = 32

_BATCH_MIN, _BATCH_MAX = 1, 256

_LOCAL_ENCODER: Any = None
_LOCAL_ENCODER_LOADED = False
_LOCAL_ENCODER_NAME: str | None = None


def _detect_default_device() -> str:
    """Pick the most efficient device available without forcing it.

    Same logic as local_rerank_adapter — auto-detect cuda when present,
    otherwise cpu. ``LOCAL_EMBEDDING_DEVICE`` env var overrides.
    """
    try:
        import torch  # local import — keeps adapter importable offline

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _model_name() -> str:
    return os.environ.get("LOCAL_EMBEDDING_MODEL_NAME", "").strip() or _DEFAULT_MODEL


def _is_disabled() -> bool:
    flag = os.environ.get("LOCAL_EMBEDDING_DISABLED", "").strip().lower()
    return flag in {"1", "true", "yes"}


def _allow_download() -> bool:
    flag = os.environ.get("LOCAL_EMBEDDING_ALLOW_DOWNLOAD", "").strip().lower()
    return flag in {"1", "true", "yes"}


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _hf_cache_root() -> Path:
    """Resolve the HuggingFace cache root the same way transformers does."""
    candidates = [
        os.environ.get("HF_HUB_CACHE"),
        os.environ.get("HUGGINGFACE_HUB_CACHE"),
        os.environ.get("TRANSFORMERS_CACHE"),
    ]
    for c in candidates:
        if c:
            return Path(c)
    return Path.home() / ".cache" / "huggingface" / "hub"


def _weights_present(model_name: str) -> bool:
    """Check whether the model is in HF cache without doing a network call.

    Heuristic: look for ``models--<org>--<name>/snapshots/`` containing at
    least one revision dir with a tokenizer + weights file (any of
    pytorch_model.bin / model.safetensors / pytorch_model-*.bin).
    """
    if not model_name or "/" not in model_name:
        # User-supplied filesystem path — defer to model loader to validate.
        return Path(model_name).exists()
    org, name = model_name.split("/", 1)
    safe = f"models--{org}--{name}"
    snapshots = _hf_cache_root() / safe / "snapshots"
    if not snapshots.is_dir():
        return False
    for revision in snapshots.iterdir():
        if not revision.is_dir():
            continue
        has_tokenizer = any(revision.glob("tokenizer*"))
        has_weights = any(revision.glob("*.safetensors")) or any(
            revision.glob("pytorch_model*.bin")
        )
        if has_weights and has_tokenizer:
            return True
    return False


def is_available() -> bool:
    """Cheap probe — does NOT load weights or torch modules.

    Returns False when:
      - ``LOCAL_EMBEDDING_DISABLED=1`` (fail-closed)
      - ``sentence-transformers`` or ``torch`` not importable
      - model weights are NOT present in HF cache AND
        ``LOCAL_EMBEDDING_ALLOW_DOWNLOAD`` is not set (strict-offline default)
    """
    if _is_disabled():
        return False
    try:
        import torch  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    if _weights_present(_model_name()):
        return True
    return _allow_download()


def get_status() -> dict[str, Any]:
    """Aggregate status snapshot for UI / settings endpoints.

    Mirrors ``local_rerank_adapter.get_status()`` field-by-field so the
    frontend can render the local embedding chip from the same component
    as the rerank chip.

    Does NOT load model weights — only probes env + filesystem.
    """
    model_name = _model_name()
    device_env_override = os.environ.get("LOCAL_EMBEDDING_DEVICE", "").strip() or None
    return {
        "available": is_available(),
        "disabled": _is_disabled(),
        "weights_present": _weights_present(model_name),
        "allow_download": _allow_download(),
        "model_name": model_name,
        "device": device_env_override or _detect_default_device(),
        "device_source": "env_override" if device_env_override else "auto_detected",
        "batch_size": _env_int(
            "LOCAL_EMBEDDING_BATCH_SIZE", _DEFAULT_BATCH, _BATCH_MIN, _BATCH_MAX
        ),
        "loaded": _LOCAL_ENCODER_LOADED and _LOCAL_ENCODER is not None,
        "hf_cache_dir": str(_hf_cache_root()),
    }


def _get_encoder() -> Any:
    """Lazy singleton — returns the SentenceTransformer instance or None."""
    global _LOCAL_ENCODER, _LOCAL_ENCODER_LOADED, _LOCAL_ENCODER_NAME

    if _LOCAL_ENCODER_LOADED:
        return _LOCAL_ENCODER

    _LOCAL_ENCODER_LOADED = True

    if _is_disabled():
        logger.info(
            "local_embedding_adapter: LOCAL_EMBEDDING_DISABLED=1; skipping model load"
        )
        _LOCAL_ENCODER = None
        return None

    model_name = _model_name()
    device = (
        os.environ.get("LOCAL_EMBEDDING_DEVICE", "").strip() or _detect_default_device()
    )

    if not _weights_present(model_name) and not _allow_download():
        logger.warning(
            "local_embedding_adapter: weights for %s not in HF cache and "
            "LOCAL_EMBEDDING_ALLOW_DOWNLOAD unset; embedding fallback unavailable",
            model_name,
        )
        _LOCAL_ENCODER = None
        return None

    try:
        import torch  # noqa: F401
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as exc:
        logger.warning(
            "local_embedding_adapter: sentence-transformers/torch not installed (%s); "
            "embedding fallback unavailable",
            exc,
        )
        _LOCAL_ENCODER = None
        return None

    local_only = not _allow_download()
    if local_only:
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    try:
        encoder = SentenceTransformer(model_name, device=device)
        _LOCAL_ENCODER = encoder
        _LOCAL_ENCODER_NAME = model_name
        logger.info(
            "local_embedding_adapter: loaded %s on %s (local_only=%s)",
            model_name,
            device,
            local_only,
        )
        return _LOCAL_ENCODER
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "local_embedding_adapter: load failed for %s (%s); embedding fallback unavailable",
            model_name,
            exc,
        )
        _LOCAL_ENCODER = None
        return None


def encode_texts(texts: list[str], target_dim: int) -> list[list[float]] | None:
    """Encode a batch of texts on-device. Returns None on any failure.

    Output vectors are L2-normalized and truncated/padded to ``target_dim``
    so they slot directly into ``np.array(vec[:EMBEDDING_DIM])`` callers
    without further reshaping.
    """
    encoder = _get_encoder()
    if encoder is None or not texts:
        return [] if encoder is not None else None
    batch_size = _env_int(
        "LOCAL_EMBEDDING_BATCH_SIZE", _DEFAULT_BATCH, _BATCH_MIN, _BATCH_MAX
    )
    try:
        # normalize_embeddings=True 让 cosine 计算可直接用点积
        vectors = encoder.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "local_embedding_adapter: encode failed (%s); returning None to trigger upstream fallback",
            exc,
        )
        return None
    out: list[list[float]] = []
    for vec in vectors:
        v = vec.tolist()
        if len(v) >= target_dim:
            out.append(v[:target_dim])
        else:
            # pad to target_dim with zeros (best-effort, only if backend model
            # dims < expected — shouldn't happen with bge-m3 → 1024)
            out.append(v + [0.0] * (target_dim - len(v)))
    return out


async def aencode_texts(texts: list[str], target_dim: int) -> list[list[float]] | None:
    """Async wrapper around ``encode_texts()``. Runs in a thread pool to
    avoid blocking the FastAPI event loop on a multi-second batch."""
    return await asyncio.to_thread(encode_texts, texts, target_dim)

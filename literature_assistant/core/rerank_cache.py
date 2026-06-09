from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from project_paths import output_path

CacheMode = Literal["ttl", "corpus_version"]


@dataclass
class _Entry:
    value: dict[str, float]
    expires_at: float
    corpus_version: str | None = None


def _resolve_cache_mode() -> CacheMode:
    """Return the configured cache mode: ttl (default) or corpus_version."""
    raw = os.environ.get("RERANK_CACHE_MODE", "ttl").strip().lower()
    if raw == "corpus_version":
        return "corpus_version"
    return "ttl"


def _resolve_disk_dir() -> Path | None:
    """Return the configured disk cache dir, or None if disabled."""
    raw = os.environ.get("RERANK_DISK_CACHE_DIR", str(output_path("rerank_cache")))
    if not raw or raw.lower() in {"0", "false", "off", "no", "disabled"}:
        return None
    path = Path(raw)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return path


def _compute_corpus_version_fallback() -> str | None:
    """Compute current corpus version from chunk store manifest.
    
    Returns None if manifest is missing or invalid (fail-open).
    """
    try:
        candidate_roots: list[Path] = []
        configured_root = os.environ.get("RERANK_CHUNK_STORE_DIR", "").strip()
        if configured_root:
            candidate_roots.append(Path(configured_root).expanduser())
        disk_dir = _resolve_disk_dir()
        if disk_dir is not None:
            candidate_roots.append(disk_dir.parent / "chunk_store")
        candidate_roots.append(output_path("chunk_store"))
        
        # Collect all project manifests
        hashes: list[str] = []
        seen_roots: set[Path] = set()
        for chunk_store_root in candidate_roots:
            root = chunk_store_root.expanduser().resolve()
            if root in seen_roots or not root.exists():
                continue
            seen_roots.add(root)
            for project_dir in root.iterdir():
                if not project_dir.is_dir():
                    continue
                manifest_path = project_dir / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    materials = payload.get("materials", {})
                    if isinstance(materials, dict):
                        for entry in materials.values():
                            if isinstance(entry, dict):
                                sha = str(entry.get("sha256") or "").strip()
                                if sha:
                                    hashes.append(sha)
                except (OSError, json.JSONDecodeError):
                    continue
        
        if not hashes:
            return None
        
        # Sort and hash to create stable corpus version
        material = "\n".join(sorted(hashes))
        return sha256(material.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _shard_path(root: Path, key: str) -> Path:
    # 2-hex shard keeps any single dir well under FS limits at high cardinality.
    return root / key[:2] / f"{key}.json"


class RerankResultCache:
    """Process-local LRU+TTL cache for rerank scores, transparently backed by disk.

    Layered behavior:
    * In-memory LRU+TTL is the fast path (unchanged contract).
    * On in-memory miss, falls back to JSON file under ``RERANK_DISK_CACHE_DIR``
      (default ``output/rerank_cache``); a hit warms the in-memory layer.
    * ``set`` writes both layers; disk write is atomic (tmp + ``os.replace``).
    * Disable disk layer by exporting ``RERANK_DISK_CACHE_DIR=0``.

    Cache expiry modes (via ``RERANK_CACHE_MODE`` env):
    * ``ttl`` (default): Entries expire after ttl_seconds, typical runtime behavior.
    * ``corpus_version``: Entries persist as long as corpus SHA unchanged; ideal for
      evaluation scripts that repeatedly query the same corpus. Fails open to TTL
      when manifest unavailable.

    Usage for evaluation:
        export RERANK_CACHE_MODE=corpus_version
        python eval_retrieval_runtime.py  # cache persists across runs
    """

    def __init__(self, max_size: int = 10_000, ttl_seconds: int = 43_200) -> None:
        self.max_size = max(1, int(max_size))
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = Lock()
        self._disk_dir = _resolve_disk_dir()
        self._cache_mode = _resolve_cache_mode()
        self._mem_hits = 0
        self._disk_hits = 0
        self._misses = 0

    def get(self, key: str) -> dict[str, float] | None:
        now = time.time()
        current_corpus_version: str | None = None
        if self._cache_mode == "corpus_version":
            current_corpus_version = _compute_corpus_version_fallback()
        
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                # Check expiry based on mode
                if self._is_entry_valid(entry, now, current_corpus_version):
                    self._store.move_to_end(key)
                    self._mem_hits += 1
                    return dict(entry.value)
                self._store.pop(key, None)
        
        disk_value = self._disk_get(key, now, current_corpus_version)
        if disk_value is not None:
            with self._lock:
                self._store[key] = _Entry(
                    value=dict(disk_value),
                    expires_at=now + self.ttl_seconds,
                    corpus_version=current_corpus_version,
                )
                self._store.move_to_end(key)
                self._evict_locked()
                self._disk_hits += 1
            return dict(disk_value)
        with self._lock:
            self._misses += 1
        return None

    def set(self, key: str, value: dict[str, float]) -> None:
        now = time.time()
        expires_at = now + self.ttl_seconds
        current_corpus_version: str | None = None
        if self._cache_mode == "corpus_version":
            current_corpus_version = _compute_corpus_version_fallback()
        
        with self._lock:
            self._store[key] = _Entry(
                value=dict(value),
                expires_at=expires_at,
                corpus_version=current_corpus_version,
            )
            self._store.move_to_end(key)
            self._evict_locked()
        self._disk_set(key, value, expires_at, current_corpus_version)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "mem_hits": self._mem_hits,
                "disk_hits": self._disk_hits,
                "misses": self._misses,
                "in_memory_entries": len(self._store),
            }

    def _evict_locked(self) -> None:
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def _is_entry_valid(self, entry: _Entry, now: float, current_corpus_version: str | None) -> bool:
        """Check if entry is still valid based on cache mode."""
        if self._cache_mode == "corpus_version":
            # In corpus_version mode, cache is valid if corpus hasn't changed
            if current_corpus_version is None:
                # Fallback to TTL if corpus version unavailable
                return entry.expires_at > now
            # Entry valid if corpus version matches
            return entry.corpus_version == current_corpus_version
        else:
            # TTL mode: check time-based expiry
            return entry.expires_at > now

    def _disk_get(self, key: str, now: float, current_corpus_version: str | None = None) -> dict[str, float] | None:
        if self._disk_dir is None:
            return None
        path = _shard_path(self._disk_dir, key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        
        # Check validity based on mode
        if self._cache_mode == "corpus_version":
            stored_version = payload.get("corpus_version")
            if current_corpus_version is None:
                # Fallback to TTL if corpus version unavailable
                expires_at = float(payload.get("expires_at", 0))
                if expires_at <= now:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    return None
            elif stored_version != current_corpus_version:
                # Corpus changed, invalidate cache
                try:
                    path.unlink()
                except OSError:
                    pass
                return None
        else:
            # TTL mode: check time-based expiry
            expires_at = float(payload.get("expires_at", 0))
            if expires_at <= now:
                try:
                    path.unlink()
                except OSError:
                    pass
                return None
        
        value = payload.get("value")
        if not isinstance(value, dict):
            return None
        try:
            return {str(k): float(v) for k, v in value.items()}
        except (TypeError, ValueError):
            return None

    def _disk_set(
        self,
        key: str,
        value: dict[str, float],
        expires_at: float,
        corpus_version: str | None = None,
    ) -> None:
        if self._disk_dir is None:
            return
        path = _shard_path(self._disk_dir, key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = {
            "value": {str(k): float(v) for k, v in value.items()},
            "expires_at": float(expires_at),
            "written_at": time.time(),
        }
        if corpus_version is not None:
            payload["corpus_version"] = corpus_version
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass


_GLOBAL_RERANK_CACHE = RerankResultCache()


def candidate_cache_id(item: dict[str, Any], idx: int) -> str:
    chunk_id = str(item.get("chunk_id", "")).strip()
    if chunk_id:
        return f"chunk::{chunk_id}"
    material_id = str(item.get("material_id", "")).strip()
    raw = str(item.get("raw_content") or item.get("content") or item.get("text") or "")
    digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
    if material_id:
        return f"mat::{material_id}::{digest}"
    return f"idx::{idx}::{digest}"


def make_cache_key(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    model: str,
    version: str,
) -> str:
    q = " ".join((query or "").strip().lower().split())
    candidate_ids = sorted(candidate_cache_id(item, i) for i, item in enumerate(candidates))
    material = "|".join([version, model, q, *candidate_ids])
    return sha256(material.encode("utf-8")).hexdigest()

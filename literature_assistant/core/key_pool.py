"""Key pool: parse multi-credential local env catalogs and rotate on failure.

Background: this repo's local env catalog intentionally lists multiple credentials per
category (embedding / rerank / generation), but standard dotenv only keeps
the *last* assignment to any given variable name. This module parses the
file directly, accumulates per-section credentials, and offers a small
``try_call`` helper that iterates them on auth/rate failures.

Parsing rules (kept deliberately small):
- Section breaks are inferred from new ``API_KEY`` / ``KEY`` /
  ``RERANK_API_KEY`` / ``ARK_API_KEY`` / ``VOLCANO_API_KEY`` assignments
  (a new key starts a new credential).
- Comment lines like ``##embeding##`` / ``##rerank##`` / ``##回答模型##``
  set the active category.
- Variable name prefixes are authoritative when present
  (``EMBEDDING_MODEL`` -> embedding, ``RERANK_*`` -> rerank,
  ``ARK_*`` / ``VOLCANO_*`` -> generation).
- For the legacy top section that uses bare ``KEY`` / ``URL`` / ``MODEL``,
  the URL substring (``embedding`` vs ``rerank``) decides the category and
  causes a flush when the URL flips mid-section.

The module keeps values as-is except for a narrow URL repair: if a URL line is
mistakenly written as ``EMBEDDING_BASE_URL=OPENAI_BASE_URL=https://...`` (or a
similar nested env assignment), the leading ``OPENAI_BASE_URL=`` wrapper is
stripped before grouping so long-running jobs do not inherit malformed request
URLs.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

logger = logging.getLogger(__name__)

Category = str  # "embedding" | "rerank" | "generation"
T = TypeVar("T")


@dataclass(frozen=True)
class Credential:
    category: Category
    provider: str
    api_key: str
    base_url: str
    model: str
    line_no: int = 0
    # GPT rule 3(b) — env var name that introduced this credential's key,
    # used by KeyPool.sort_provider_specific_first() to prioritize
    # SILICONFLOW_RERANK_API_KEY over generic RERANK_API_KEY.
    key_var_name: str = ""

    @property
    def cred_id(self) -> tuple[str, str, str]:
        return (self.api_key[:12], self.base_url, self.model)

    @property
    def is_provider_specific_key(self) -> bool:
        """True if key came from a provider-specific env var like
        ``SILICONFLOW_RERANK_API_KEY``,not generic ``RERANK_API_KEY``."""
        name_upper = (self.key_var_name or "").upper()
        # Generic forms have no provider prefix.
        return name_upper not in (
            "API_KEY", "KEY",
            "RERANK_API_KEY", "EMBEDDING_API_KEY",
            "BASE_URL", "URL",
        ) and bool(self.key_var_name)


_CATEGORY_HEADER_RE = re.compile(
    r"^\s*#+\s*(embeding|embedding|rerank|回答模型|generation)\b",
    re.IGNORECASE,
)
_PROVIDER_HEADER_RE = re.compile(r"^\s*#+\s*([^#=\n]+?)\s*#+\s*$")
_AUTH_FAIL_HINTS = ("401", "403", "429", "404", "400", "unauthor", "invalid api key", "invalid_api_key")
_NESTED_ENV_URL_VALUE_RE = re.compile(r"^(?:[A-Z][A-Z0-9_]*=)+(https?://.+)$")
_EMPTY_POOLS: dict[Category, list[Credential]] = {"embedding": [], "rerank": [], "generation": []}


def _dotenv_disabled() -> bool:
    """Return whether default key-pool env catalog loading is disabled."""

    return os.environ.get("RUNTIME_ENV_DISABLE_DOTENV", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def _default_env_catalog_path() -> Path | None:
    """Return the shared runtime env catalog path used by runtime_env.py."""

    if _dotenv_disabled():
        return None
    cwd_dotenv = (Path.cwd() / ".env").resolve()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        cwd_dotenv.relative_to(repo_root)
        cwd_inside_repo = True
    except ValueError:
        cwd_inside_repo = False
    if cwd_dotenv.exists() and not cwd_inside_repo and cwd_dotenv != Path(__file__).resolve().with_name(".env"):
        return cwd_dotenv
    try:
        from runtime_env import _runtime_env_path

        return _runtime_env_path()
    except Exception:
        return Path("workspace_artifacts/runtime_state/local_env/literature_assistant.env")


def _empty_pools() -> dict[Category, list[Credential]]:
    """Return a fresh empty key-pool mapping."""

    return {category: [] for category in _EMPTY_POOLS}


def _normalize_url_value(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = _NESTED_ENV_URL_VALUE_RE.match(text)
    if match:
        return match.group(1).strip() or None
    return text


def _model_indicates_rerank(model: str | None) -> bool:
    haystack = str(model or "").strip().lower()
    return "rerank" in haystack or "reranker" in haystack


def _model_indicates_embedding(model: str | None) -> bool:
    haystack = str(model or "").strip().lower()
    if not haystack:
        return False
    if "embedding" in haystack:
        return True
    return "bge-" in haystack and not _model_indicates_rerank(haystack)


def _url_indicates_rerank(base_url: str | None) -> bool:
    return "rerank" in str(base_url or "").strip().lower()


def _url_indicates_embedding(base_url: str | None) -> bool:
    haystack = str(base_url or "").strip().lower()
    return any(token in haystack for token in ("/embeddings", "/embedding", "multimodal-embedding"))


def infer_credential_category(
    base_url: str | None,
    model: str | None,
    *,
    preferred: Category | None = None,
) -> Category:
    """Infer credential category from endpoint/model semantics first, hints second."""
    if _model_indicates_rerank(model):
        return "rerank"
    if _model_indicates_embedding(model):
        return "embedding"
    if _url_indicates_rerank(base_url):
        return "rerank"
    if _url_indicates_embedding(base_url):
        return "embedding"
    if preferred in {"embedding", "rerank", "generation"}:
        return preferred
    return "generation"


def _normalise_category(token: str) -> Category:
    token_l = token.lower()
    if "rerank" in token_l:
        return "rerank"
    if "embed" in token_l:
        return "embedding"
    return "generation"


def _classify_var(name: str) -> tuple[str, Category | None]:
    """Return (field, forced_category) for a known variable name."""
    n = name.upper()
    if n in (
        "SILICONFLOW_EMBEDDING_API_KEY",
        "EMBEDDING_API_KEY",
        "JINA_API_KEY",
    ):
        return ("key", "embedding")
    if n in (
        "SILICONFLOW_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
    ):
        return ("key", None)
    if n in ("API_KEY", "KEY"):
        return ("key", None)
    if n == "RERANK_API_KEY":
        return ("key", "rerank")
    if n in ("SILICONFLOW_RERANK_API_KEY", "DASHSCOPE_RERANK_API_KEY"):
        return ("key", "rerank")
    if n in ("ARK_API_KEY", "VOLCANO_API_KEY"):
        return ("key", "generation")
    if n in (
        "SILICONFLOW_EMBEDDING_BASE_URL",
        "JINA_EMBEDDING_BASE_URL",
        "EMBEDDING_BASE_URL",
    ):
        return ("url", "embedding")
    if n in (
        "SILICONFLOW_BASE_URL",
        "DASHSCOPE_BASE_URL",
        "OPENAI_BASE_URL",
    ):
        return ("url", None)
    if n in ("BASE_URL", "URL"):
        return ("url", None)
    if n == "RERANK_BASE_URL":
        return ("url", "rerank")
    if n in ("SILICONFLOW_RERANK_BASE_URL", "DASHSCOPE_RERANK_BASE_URL"):
        return ("url", "rerank")
    if n in ("ARK_BASE_URL", "VOLCANO_BASE_URL"):
        return ("url", "generation")
    if n in ("SILICONFLOW_EMBEDDING_MODEL", "JINA_EMBEDDING_MODEL", "EMBEDDING_MODEL"):
        return ("model", "embedding")
    if n in (
        "SILICONFLOW_MODEL",
        "DASHSCOPE_MODEL",
        "OPENAI_MODEL",
    ):
        return ("model", None)
    if n == "RERANK_MODEL":
        return ("model", "rerank")
    if n in ("SILICONFLOW_RERANK_MODEL", "DASHSCOPE_RERANK_MODEL"):
        return ("model", "rerank")
    if n in ("ARK_MODEL", "VOLCANO_MODEL"):
        return ("model", "generation")
    if n == "MODEL":
        return ("model", None)
    return ("ignore", None)


def parse_env_pools(path: str | Path | None = None) -> dict[Category, list[Credential]]:
    """Parse a multi-credential env catalog into category → ordered credentials.

    Args:
        path: Explicit env file path. When omitted, the shared runtime env
            catalog under ``workspace_artifacts/runtime_state/local_env`` is
            used unless dotenv loading is disabled.
    """

    resolved_path = Path(path) if path is not None else _default_env_catalog_path()
    if resolved_path is None:
        return _empty_pools()
    p = resolved_path
    if not p.exists():
        logger.warning("key_pool: env catalog not found at %s", p)
        return _empty_pools()

    text = p.read_text(encoding="utf-8", errors="replace")
    pools: dict[Category, list[Credential]] = _empty_pools()

    active_category: Category | None = None
    active_provider: str = "unknown"
    pending: dict[str, object] = {}  # {key, url, models: list[(model, line_no, forced_cat)]}

    def emit_pending(reset_key: bool) -> None:
        """Emit credentials from pending; optionally clear the key as well.

        Called when the *url* or *key* changes. URL changes keep the key
        so the legacy single-credential layout (one key, multiple URL
        sub-sections) still works.
        """
        nonlocal pending
        if not pending:
            return
        key = pending.get("key")
        url = pending.get("url")
        models: list[tuple[str, int, Category | None]] = pending.get("models", [])  # type: ignore[assignment]
        if key and url and models:
            url_cat = _normalise_category(str(url))
            for model_name, line_no, forced in models:
                cat = infer_credential_category(
                    str(url),
                    model_name,
                    preferred=forced or url_cat or active_category,
                )
                pools[cat].append(
                    Credential(
                        category=cat,
                        provider=active_provider,
                        api_key=str(key),
                        base_url=str(url),
                        model=model_name,
                        line_no=line_no,
                        key_var_name=str(pending.get("key_var_name") or ""),
                    )
                )
        if reset_key:
            pending = {}
        else:
            # Keep key + key_var_name across URL changes (single key reused
            # for multiple URLs in the legacy layout).
            pending = {
                "key": pending.get("key"),
                "key_var_name": pending.get("key_var_name", ""),
            }

    # GPT review rule 3(a) — DISABLED_ARCHIVE block skip.
    # A header like ``## [STATUS:DISABLED_ARCHIVE_2026-04-30] ...`` puts the
    # parser into "archive mode" until the next non-archive top-level header
    # (``## …`` without DISABLED_ARCHIVE in it, OR a category header like
    # ``##embedding##``). All ``KEY=value`` lines inside an archive block are
    # ignored, even if someone unwraps a ``# RERANK_API_KEY=`` by removing the
    # ``#`` comment marker. Belt-and-suspenders against accidental revival.
    archive_mode = False

    for idx, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        # GPT rule 3(a) — detect archive header
        if "DISABLED_ARCHIVE" in line and line.startswith("#"):
            archive_mode = True
            logger.debug("key_pool: entering DISABLED_ARCHIVE block at line %d", idx)
            continue

        # Category header (single or multiple #'s, e.g., "##embeding##")
        m_cat = _CATEGORY_HEADER_RE.match(line)
        if m_cat and "=" not in line:
            # any top-level category header ends archive mode
            if archive_mode:
                logger.debug("key_pool: exiting DISABLED_ARCHIVE block at line %d "
                             "(category header)", idx)
                archive_mode = False
            # don't emit here — wait until URL/key actually changes
            active_category = _normalise_category(m_cat.group(1))
            continue

        # Provider header (e.g., "##阿里云官方##")
        if line.startswith("#") and "=" not in line:
            m_prov = _PROVIDER_HEADER_RE.match(line)
            if m_prov:
                # a fresh provider header (not archive) also exits archive mode
                if archive_mode:
                    logger.debug("key_pool: exiting DISABLED_ARCHIVE block at line %d "
                                 "(provider header)", idx)
                    archive_mode = False
                active_provider = m_prov.group(1).strip()
            continue

        if "=" not in line:
            continue

        # GPT rule 3(a) — inside DISABLED_ARCHIVE block: skip all KEY=value
        # lines, even if someone unwraps "# RERANK_API_KEY=..." by removing #.
        if archive_mode:
            continue

        name, _, value_part = line.partition("=")
        name = name.strip()
        # strip inline trailing comment like   "value   ##免费"
        value = re.split(r"\s+#", value_part, maxsplit=1)[0].strip()
        if not value:
            continue

        var_kind, forced = _classify_var(name)
        if var_kind == "ignore":
            continue

        if var_kind == "key":
            # New credential boundary: emit prior fully (reset key too)
            if pending.get("key"):
                emit_pending(reset_key=True)
            if forced:
                active_category = forced
            pending["key"] = value
            pending["key_var_name"] = name  # GPT rule 3(b)
        elif var_kind == "url":
            # URL change → emit any models accumulated under the previous URL,
            # but keep the key (legacy section reuses one key for emb+rerank).
            if pending.get("url") and pending.get("models"):
                emit_pending(reset_key=False)
            if forced:
                active_category = forced
            else:
                active_category = _normalise_category(_normalize_url_value(value))
            pending["url"] = _normalize_url_value(value)
        elif var_kind == "model":
            pending.setdefault("models", []).append((value, idx, forced))  # type: ignore[union-attr]

    emit_pending(reset_key=True)
    # GPT rule 3(b) — stable sort: provider-specific keys before generic.
    # Within each group (specific vs generic), preserve .env file order
    # (line_no), so legacy ordering is unchanged for fully-generic pools.
    for cat in pools:
        pools[cat].sort(key=lambda c: (
            0 if c.is_provider_specific_key else 1,
            c.line_no,
        ))
    return pools


class KeyPool:
    """Try multiple credentials per category until one succeeds."""

    def __init__(self, pools: dict[Category, list[Credential]], cooldown_seconds: float = 30.0):
        self._pools = pools
        self._cooldown_seconds = cooldown_seconds
        self._cooldown: dict[tuple[str, str, str], float] = {}
        self._lock = threading.Lock()
        # Health-stat tracking.
        # _exhausted_count: total times try_call/try_call_async raised because
        #   it ran out of usable credentials. Any value >0 in a single eval
        #   run is a release-gate warning signal.
        # _last_failure_class: per-category, the type name of the most recent
        #   exception that surfaced from try_call. Cleared on success.
        self._exhausted_count: dict[Category, int] = {}
        self._last_failure_class: dict[Category, str | None] = {}

    def list(self, category: Category) -> list[Credential]:
        return list(self._pools.get(category, []))

    def first(self, category: Category) -> Credential | None:
        items = self._pools.get(category) or []
        return items[0] if items else None

    def _is_cooled_down(self, cred: Credential) -> bool:
        with self._lock:
            until = self._cooldown.get(cred.cred_id, 0.0)
            return until > time.time()

    def _mark_cooldown(self, cred: Credential) -> None:
        with self._lock:
            self._cooldown[cred.cred_id] = time.time() + self._cooldown_seconds

    def _should_mark_cooldown(
        self,
        exc: BaseException,
        cooldown_on: Callable[[BaseException], bool] | None = None,
    ) -> bool:
        if cooldown_on is not None:
            return bool(cooldown_on(exc))
        msg = str(exc).lower()
        return any(h in msg for h in _AUTH_FAIL_HINTS)

    # --- Public cooldown API (used by generation_dispatch_adapter bridge) ---
    # These are thin wrappers around the private cooldown internals so that
    # external code (e.g. model_dispatcher via the adapter) can reuse the
    # exact same cooldown semantics as try_call. See
    # docs/plans/active/2026-05-08-runtime-credentials-parallel-discussion-plan.md
    # §13.1f.1 (C+1 reusable adapter sketch).

    def is_cooled_down(self, cred: Credential) -> bool:
        """Return True if ``cred`` is currently in cooldown (skip it)."""
        return self._is_cooled_down(cred)

    def mark_failure(
        self,
        cred: Credential,
        exc: BaseException | None = None,
        *,
        cooldown_on: Callable[[BaseException], bool] | None = None,
    ) -> bool:
        """Record a failure for ``cred`` and apply cooldown if warranted.

        If ``exc`` is None, force cooldown unconditionally. Otherwise apply
        the same heuristic that ``try_call`` uses (auth/rate-limit-shaped
        errors only). Returns True if cooldown was applied.
        """
        if exc is not None and not self._should_mark_cooldown(exc, cooldown_on):
            return False
        self._mark_cooldown(cred)
        return True

    def mark_success(self, cred: Credential) -> None:  # noqa: ARG002 — reserved
        """Record a successful call for ``cred``.

        Currently a no-op (KeyPool has no positive health metric); reserved
        so callers can pair every ``mark_failure`` with a symmetric success
        signal without behavioural drift later.
        """
        return None

    # --- Health stats ---

    def stats(self, category: Category | None = None) -> dict[str, Any]:
        """Return a structured health snapshot for one category or all.

        Shape per category:

            {
                "category": "generation",
                "total_credentials": 3,
                "primary_key_active": True,
                "credentials_in_cooldown": 1,
                "exhausted_count": 0,
                "last_failure_class": None,
                "credentials": [
                    {"provider": "ark", "model": "doubao-pro", "cooled_down": False},
                    ...
                ],
            }

        ``primary_key_active`` is True iff the first (highest priority)
        credential is NOT currently cooled down.

        When ``category`` is None, returns ``{"pools": [<per-cat snapshot>, ...]}``.

        No credential material in the output — provider/model only.
        """
        if category is not None:
            return self._stats_for_category(category)
        return {"pools": [self._stats_for_category(c) for c in sorted(self._pools.keys())]}

    def _stats_for_category(self, category: Category) -> dict[str, Any]:
        creds = self._pools.get(category) or []
        cred_snapshots: list[dict[str, Any]] = []
        cooled = 0
        for cred in creds:
            is_cd = self._is_cooled_down(cred)
            if is_cd:
                cooled += 1
            cred_snapshots.append(
                {
                    "provider": cred.provider,
                    "model": cred.model,
                    "cooled_down": is_cd,
                }
            )
        primary_active = bool(creds) and not self._is_cooled_down(creds[0])
        with self._lock:
            exhausted = self._exhausted_count.get(category, 0)
            last_fail = self._last_failure_class.get(category)
        return {
            "category": category,
            "total_credentials": len(creds),
            "primary_key_active": primary_active,
            "credentials_in_cooldown": cooled,
            "exhausted_count": exhausted,
            "last_failure_class": last_fail,
            "credentials": cred_snapshots,
        }

    def reset_stats(self, category: Category | None = None) -> None:
        """Clear ``exhausted_count`` and ``last_failure_class`` counters.

        Used by tests and by the per-eval-run reset hook. Cooldown state
        is NOT cleared (use a fresh ``KeyPool`` if you need that).
        """
        with self._lock:
            if category is None:
                self._exhausted_count.clear()
                self._last_failure_class.clear()
            else:
                self._exhausted_count.pop(category, None)
                self._last_failure_class.pop(category, None)

    def try_call(
        self,
        category: Category,
        fn: Callable[[Credential], T],
        *,
        on_attempt: Callable[[Credential, BaseException | None], None] | None = None,
        cooldown_on: Callable[[BaseException], bool] | None = None,
    ) -> T:
        """Iterate credentials and call ``fn(cred)`` until one succeeds.

        Cooldown is applied to credentials whose error message looks like
        an auth/rate failure (401/403/429/etc.). Other exceptions still
        fall through to the next credential but do not cooldown.
        """
        creds: Iterable[Credential] = self._pools.get(category) or []
        last_exc: BaseException | None = None
        attempted_any = False
        for cred in creds:
            if self._is_cooled_down(cred):
                continue
            attempted_any = True
            try:
                result = fn(cred)
                if on_attempt is not None:
                    on_attempt(cred, None)
                # Success: clear last_failure_class for this category
                with self._lock:
                    self._last_failure_class[category] = None
                return result
            except Exception as exc:  # noqa: BLE001 — we re-raise at end
                last_exc = exc
                if self._should_mark_cooldown(exc, cooldown_on):
                    self._mark_cooldown(cred)
                if on_attempt is not None:
                    on_attempt(cred, exc)
                logger.warning(
                    "key_pool[%s] cred %s/%s failed: %s",
                    category, cred.provider, cred.model, exc,
                )
                continue
        # Reached the end without success — track diagnostic state.
        with self._lock:
            self._exhausted_count[category] = self._exhausted_count.get(category, 0) + 1
            if last_exc is not None:
                self._last_failure_class[category] = type(last_exc).__name__
            else:
                self._last_failure_class[category] = "NoCandidatesAvailable"
        if last_exc is not None:
            raise last_exc
        if not attempted_any:
            raise RuntimeError(
                f"key_pool[{category}]: no credentials available "
                "(all in cooldown or pool empty)"
            )
        raise RuntimeError(f"key_pool[{category}]: exhausted all credentials")

    async def try_call_async(
        self,
        category: Category,
        fn: Callable[[Credential], Awaitable[T]],
        *,
        on_attempt: Callable[[Credential, BaseException | None], None] | None = None,
        cooldown_on: Callable[[BaseException], bool] | None = None,
    ) -> T:
        """Async counterpart to ``try_call`` with the same cooldown semantics."""
        creds: Iterable[Credential] = self._pools.get(category) or []
        last_exc: BaseException | None = None
        attempted_any = False
        for cred in creds:
            if self._is_cooled_down(cred):
                continue
            attempted_any = True
            try:
                result = await fn(cred)
                if on_attempt is not None:
                    on_attempt(cred, None)
                with self._lock:
                    self._last_failure_class[category] = None
                return result
            except Exception as exc:  # noqa: BLE001 — we re-raise at end
                last_exc = exc
                if self._should_mark_cooldown(exc, cooldown_on):
                    self._mark_cooldown(cred)
                if on_attempt is not None:
                    on_attempt(cred, exc)
                logger.warning(
                    "key_pool[%s] cred %s/%s failed: %s",
                    category, cred.provider, cred.model, exc,
                )
                continue
        with self._lock:
            self._exhausted_count[category] = self._exhausted_count.get(category, 0) + 1
            if last_exc is not None:
                self._last_failure_class[category] = type(last_exc).__name__
            else:
                self._last_failure_class[category] = "NoCandidatesAvailable"
        if last_exc is not None:
            raise last_exc
        if not attempted_any:
            raise RuntimeError(
                f"key_pool[{category}]: no credentials available "
                "(all in cooldown or pool empty)"
            )
        raise RuntimeError(f"key_pool[{category}]: exhausted all credentials")


_singleton_lock = threading.Lock()
_singleton: KeyPool | None = None
_singleton_path: Path | None = None


# Mapping: category -> (key_var, url_var, model_var). Used by ``apply_to_env``
# to back-fill standard variable names from the first pool entry. The names
# match what the legacy code paths in this repo already read.
_ENV_VARS_BY_CATEGORY: dict[Category, tuple[str, str, str]] = {
    "embedding": ("SILICONFLOW_EMBEDDING_API_KEY", "SILICONFLOW_EMBEDDING_BASE_URL", "SILICONFLOW_EMBEDDING_MODEL"),
    "rerank": ("RERANK_API_KEY", "RERANK_BASE_URL", "RERANK_MODEL"),
    "generation": ("ARK_API_KEY", "ARK_BASE_URL", "ARK_MODEL"),
}


def apply_to_env(
    category: Category,
    *,
    pool: KeyPool | None = None,
    overwrite: bool = False,
    idx: int = 0,
) -> Credential | None:
    """Back-fill standard env var names from the pool's first credential.

    Existing values are preserved unless ``overwrite=True``.
    """
    import os

    pool = pool or get_pool()
    creds = pool.list(category)
    if not creds or idx >= len(creds):
        return None
    cred = creds[idx]
    key_var, url_var, model_var = _ENV_VARS_BY_CATEGORY[category]
    for var, value in ((key_var, cred.api_key), (url_var, cred.base_url), (model_var, cred.model)):
        if overwrite or not os.environ.get(var):
            os.environ[var] = value
    return cred


def get_pool(path: str | Path | None = None, *, refresh: bool = False) -> KeyPool:
    """Return a process-wide ``KeyPool`` parsed from ``path``."""
    global _singleton, _singleton_path
    resolved_path = Path(path) if path is not None else _default_env_catalog_path()
    target = resolved_path.resolve() if resolved_path is not None else None
    with _singleton_lock:
        if _singleton is None or refresh or _singleton_path != target:
            _singleton = KeyPool(parse_env_pools(target))
            _singleton_path = target
        return _singleton

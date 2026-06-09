from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_NESTED_ENV_URL_VALUE_RE = re.compile(r"^(?:[A-Z][A-Z0-9_]*=)+(https?://.+)$")
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on", "enabled"}
_LOCAL_ENV_FILE_ENV = "LITASSIST_LOCAL_ENV_FILE"
_ENABLE_REPO_DOTENV_ENV = "LITASSIST_ENABLE_REPO_DOTENV"
_LEGACY_ENABLE_REPO_DOTENV_ENV = "RUNTIME_ENV_ENABLE_DOTENV"


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_urlish(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    match = _NESTED_ENV_URL_VALUE_RE.match(text)
    if match:
        return match.group(1).strip() or None
    return text


def _dotenv_disabled() -> bool:
    return _clean(os.getenv("RUNTIME_ENV_DISABLE_DOTENV")) in _TRUTHY_ENV_VALUES


def _repo_dotenv_enabled() -> bool:
    return (
        _clean(os.getenv(_ENABLE_REPO_DOTENV_ENV)) in _TRUTHY_ENV_VALUES
        or _clean(os.getenv(_LEGACY_ENABLE_REPO_DOTENV_ENV)) in _TRUTHY_ENV_VALUES
    )


def _runtime_env_path() -> Path:
    """Return the ignored local env catalog path used outside source files.

    Why:
        Runtime API catalogs can contain credentials. Keeping the default env
        catalog under runtime state avoids treating source directories as a
        secret store while preserving a local-first workflow.
    """

    try:
        from project_paths import runtime_state_path

        return runtime_state_path("local_env", "literature_assistant.env")
    except Exception:
        return (
            Path(__file__).resolve().parents[2]
            / "workspace_artifacts"
            / "runtime_state"
            / "local_env"
            / "literature_assistant.env"
        )


def _cwd_dotenv_path() -> Path | None:
    """Return a temporary cwd dotenv only when it is outside source roots."""

    cwd_dotenv = (Path.cwd() / ".env").resolve()
    if not cwd_dotenv.exists():
        return None
    repo_root = Path(__file__).resolve().parents[2]
    try:
        cwd_dotenv.relative_to(repo_root)
        return None
    except ValueError:
        pass
    if cwd_dotenv == Path(__file__).resolve().with_name(".env"):
        return None
    return cwd_dotenv


def _dotenv_paths() -> tuple[Path, ...]:
    """Return local env files in increasing override order."""

    if _dotenv_disabled():
        return ()

    paths: list[Path] = [_runtime_env_path()]
    cwd_dotenv = _cwd_dotenv_path()
    if cwd_dotenv is not None:
        paths.append(cwd_dotenv)
    if _repo_dotenv_enabled():
        paths.append(Path(__file__).resolve().with_name(".env"))

    explicit_path = _clean(os.getenv(_LOCAL_ENV_FILE_ENV))
    if explicit_path is not None:
        paths.append(Path(explicit_path).expanduser())
    return tuple(paths)


def _read_dotenv_file(env_path: Path) -> dict[str, str]:
    """Parse one dotenv file into raw string values.

    Args:
        env_path: Path to a local dotenv-style file. Missing files return an
            empty mapping.

    Returns:
        A mapping of variable names to unexpanded values from that file.
    """

    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


@lru_cache(maxsize=1)
def _repo_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_path in _dotenv_paths():
        values.update(_read_dotenv_file(env_path))
    return values


def env_value(*names: str, default: str | None = None) -> str | None:
    for name in names:
        cleaner = _clean_urlish if "URL" in str(name).upper() else _clean
        value = cleaner(os.getenv(name))
        if value is not None:
            return value
        if _dotenv_disabled():
            continue
        value = cleaner(_repo_env().get(name))
        if value is not None:
            return value
    if default is None:
        return None
    if any("URL" in str(name).upper() for name in names):
        return _clean_urlish(default)
    return default


def env_bool(*names: str, default: bool = False) -> bool:
    """Resolve a boolean feature flag from env or repo-local dotenv values."""

    value = env_value(*names)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def wiki_enabled() -> bool:
    """Return whether the LLM-Wiki integration is globally enabled."""

    try:
        from feature_flags import is_enabled

        return is_enabled("wiki")
    except Exception:
        pass
    return env_bool("LITERATURE_ASSISTANT_WIKI_ENABLED", default=False)


def wiki_first_retrieval_enabled() -> bool:
    """Return whether wiki-first retrieval may run before raw RAG."""

    return wiki_enabled() and env_bool(
        "LITERATURE_ASSISTANT_WIKI_FIRST_RETRIEVAL",
        default=False,
    )


def resolve_llm_config(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    default_base_url: str,
    default_model: str,
) -> tuple[str | None, str, str]:
    return (
        _clean(api_key) or env_value("ARK_API_KEY", "VOLCANO_API_KEY", "OPENAI_API_KEY", "API_KEY"),
        _clean_urlish(base_url) or env_value("ARK_BASE_URL", "OPENAI_BASE_URL", "BASE_URL", default=default_base_url) or default_base_url,
        _clean(model) or env_value("ARK_MODEL", "OPENAI_MODEL", "MODEL", default=default_model) or default_model,
    )


DEFAULT_JINA_EMBEDDING_BASE_URL = "https://api.jina.ai/v1/embeddings"
DEFAULT_DASHSCOPE_MULTIMODAL_EMBEDDING_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
DEFAULT_JINA_EMBEDDING_MODEL = "jina-embeddings-v3"
DEFAULT_EMBEDDING_FAILOVER_COOLDOWN_SECONDS = 900.0


def is_dashscope_multimodal_embedding_url(url: str | None) -> bool:
    haystack = str(url or "").strip().lower()
    return "dashscope.aliyuncs.com" in haystack and "multimodal-embedding" in haystack


def _looks_like_dashscope_multimodal_embedding_model(model: str | None) -> bool:
    haystack = str(model or "").strip().lower()
    return any(
        token in haystack
        for token in (
            "multimodal-embedding",
            "qwen3-vl-embedding",
            "qwen2.5-vl-embedding",
            "tongyi-embedding-vision",
        )
    )


def is_dashscope_multimodal_embedding_config(base_url: str | None, model: str | None) -> bool:
    return is_dashscope_multimodal_embedding_url(base_url) or _looks_like_dashscope_multimodal_embedding_model(model)


def _resolve_dashscope_multimodal_embedding_url(base_url: str) -> str:
    trimmed = str(base_url or "").rstrip("/")
    lowered = trimmed.lower()
    if "compatible-mode" not in lowered:
        return trimmed or DEFAULT_DASHSCOPE_MULTIMODAL_EMBEDDING_URL
    parsed = urlsplit(trimmed)
    if parsed.scheme and parsed.netloc:
        return (
            f"{parsed.scheme}://{parsed.netloc}/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding"
        )
    return DEFAULT_DASHSCOPE_MULTIMODAL_EMBEDDING_URL


def resolve_embedding_request_url(base_url: str, model: str | None = None) -> str:
    trimmed = str(base_url or "").rstrip("/")
    if is_dashscope_multimodal_embedding_config(trimmed, model):
        return _resolve_dashscope_multimodal_embedding_url(trimmed)
    if trimmed.lower().endswith("/embeddings"):
        return trimmed
    return f"{trimmed}/embeddings"


def build_embedding_request_payload(
    texts: list[str],
    *,
    base_url: str | None,
    model: str | None,
    dimensions: int | None = None,
) -> dict[str, object]:
    clean_model = str(model or "").strip()
    if is_dashscope_multimodal_embedding_config(base_url, model):
        return {
            "model": clean_model,
            "input": {"contents": [{"text": text} for text in texts]},
        }

    payload: dict[str, object] = {
        "model": clean_model,
        "input": texts,
        "encoding_format": "float",
    }
    if dimensions is not None:
        payload["dimensions"] = dimensions
    return payload


def extract_embedding_vectors(payload: object) -> list[list[float]]:
    if not isinstance(payload, dict):
        return []

    output = payload.get("output")
    if isinstance(output, dict):
        embeddings = output.get("embeddings")
        if isinstance(embeddings, list):
            parsed = [
                embedding
                for item in embeddings
                if isinstance(item, dict)
                for embedding in [item.get("embedding")]
                if isinstance(embedding, list)
            ]
            if parsed:
                return parsed

    data = payload.get("data")
    if not isinstance(data, list):
        return []

    indexed: list[tuple[int, list[float]]] = []
    ordered: list[list[float]] = []
    for fallback_index, item in enumerate(data):
        if not isinstance(item, dict):
            return []
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            return []
        index = item.get("index")
        if isinstance(index, int):
            indexed.append((index, embedding))
        else:
            indexed.append((fallback_index, embedding))
            ordered = []
    if indexed:
        return [embedding for _index, embedding in sorted(indexed, key=lambda pair: pair[0])]
    return ordered

# --- Embedding key probe (validity-first selection) ---------------------------
# Mirrors reranker_client._probe_rerank_key per
# notes/2026-04-25-morpheus-key-resolution-audit.md §5. Per-process cache,
# no disk I/O, never raises, never logs the raw key.
_KEY_PROBE_CACHE_EMBED: dict[tuple[str, str, str], bool] = {}
_EMBED_PROBE_TIMEOUT_S = 5.0


def _is_embedding_probe_payload_valid(response: object) -> bool:
    json_loader = getattr(response, "json", None)
    if not callable(json_loader):
        return True
    try:
        payload = json_loader()
    except Exception:
        logger.debug("Embedding probe response JSON parse failed", exc_info=True)
        return False
    return bool(extract_embedding_vectors(payload))


def _probe_embedding_key(
    api_key: str,
    base_url: str,
    model: str,
    *,
    timeout: float = _EMBED_PROBE_TIMEOUT_S,
) -> bool:
    """Send a minimal embedding request to verify the key is accepted.

    Returns True only when the endpoint accepts the key *and* the response
    looks like an embedding payload. Cached per process. Never raises.
    """
    if not api_key or not base_url or not model:
        return False

    cache_key = (base_url, model, api_key)
    cached = _KEY_PROBE_CACHE_EMBED.get(cache_key)
    if cached is not None:
        return cached

    try:
        import httpx  # local import so runtime_env stays importable offline
    except Exception:  # httpx unavailable — treat probe as fail-closed
        _KEY_PROBE_CACHE_EMBED[cache_key] = False
        return False

    payload = build_embedding_request_payload(["probe"], base_url=base_url, model=model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                resolve_embedding_request_url(base_url, model),
                headers=headers,
                json=payload,
            )
        ok = 200 <= response.status_code < 300 and _is_embedding_probe_payload_valid(response)
    except Exception:
        logger.debug("Embedding key probe request failed", exc_info=True)
        ok = False

    _KEY_PROBE_CACHE_EMBED[cache_key] = ok
    if not ok:
        suffix = api_key[-4:] if len(api_key) >= 4 else "****"
        logger.warning(
            "Embedding key probe failed: base_url=%s model=%s key_len=%d key_suffix=***%s",
            base_url,
            model,
            len(api_key),
            suffix,
        )
    return ok


def _select_embedding_provider() -> str:
    """Resolve the active embedding provider name.

    Priority:
      1. `EMBEDDING_PROVIDER` env var (explicit override).
      2. If a SiliconFlow-family *embedding* key is present → "siliconflow".
      3. Else if `JINA_API_KEY` is present → "jina".
      4. Else → "siliconflow" (legacy default; callers guard on None api_key).

    Note: we intentionally do NOT include `RERANK_API_KEY` in step 2 — that
    would reintroduce Gap B from the 2026-04-25 audit (rerank key bleeding
    into the embedding candidate list).
    """
    explicit = _clean(env_value("EMBEDDING_PROVIDER"))
    if explicit:
        return explicit.lower()
    if env_value("SILICONFLOW_EMBEDDING_API_KEY", "SILICONFLOW_API_KEY"):
        return "siliconflow"
    if env_value("JINA_API_KEY"):
        return "jina"
    return "siliconflow"


def _siliconflow_embedding_candidates() -> list[tuple[int, str, str]]:
    """Collect SiliconFlow-side embedding key candidates in priority order.

    Each item is (priority, key, source). `RERANK_API_KEY` is deliberately
    excluded (audit Gap B).
    """
    candidates: list[tuple[int, str, str]] = []
    for priority, (env_name, source) in enumerate(
        [
            ("SILICONFLOW_EMBEDDING_API_KEY", "siliconflow-embedding-specific"),
            ("EMBEDDING_API_KEY", "legacy-embedding"),
            ("SILICONFLOW_API_KEY", "siliconflow-generic"),
        ]
    ):
        raw = env_value(env_name)
        if raw:
            candidates.append((priority, raw, source))
    generic_catalog_key = _catalog_embedding_api_key()
    if generic_catalog_key:
        candidates.append((len(candidates), generic_catalog_key, "generic-api-key-catalog"))
    return candidates


def _jina_embedding_candidates() -> list[tuple[int, str, str]]:
    candidates: list[tuple[int, str, str]] = []
    for priority, (env_name, source) in enumerate(
        [
            ("JINA_API_KEY", "jina-specific"),
            ("EMBEDDING_API_KEY", "legacy-embedding"),
        ]
    ):
        raw = env_value(env_name)
        if raw:
            candidates.append((priority, raw, source))
    generic_catalog_key = _catalog_embedding_api_key()
    if generic_catalog_key:
        candidates.append((len(candidates), generic_catalog_key, "generic-api-key-catalog"))
    return candidates


def _catalog_embedding_api_key() -> str | None:
    api_key = env_value("API_KEY")
    if not api_key:
        return None
    explicit_base_url = env_value("SILICONFLOW_EMBEDDING_BASE_URL", "EMBEDDING_BASE_URL", "BASE_URL")
    if explicit_base_url and "embed" in explicit_base_url.lower():
        return api_key
    return None


def _is_multimodal_embedding_catalog(base_url: str | None, model: str | None) -> bool:
    haystack = f"{base_url or ''} {model or ''}".lower()
    return any(token in haystack for token in ("multimodal", "vision", "-vl", "/vl"))


def _looks_like_embedding_catalog(base_url: str | None, model: str | None) -> bool:
    haystack = f"{base_url or ''} {model or ''}".lower()
    return "embed" in haystack


def _candidate_signature(api_key: str | None, base_url: str | None, model: str | None) -> tuple[str, str, str]:
    return (
        str(_clean(api_key) or ""),
        str(_clean_urlish(base_url) or ""),
        str(_clean(model) or ""),
    )


def _embedding_candidates_from_key_pool(
    default_model: str,
    *,
    target_base_url: str | None = None,
    target_model: str | None = None,
) -> list[tuple[str, str, str, str]]:
    if _dotenv_disabled():
        return []
    try:
        from key_pool import get_pool
    except Exception:
        logger.debug("Key pool unavailable while resolving embedding candidates", exc_info=True)
        return []

    try:
        pool = get_pool()
        credentials = [
            cred
            for category in ("embedding", "rerank", "generation")
            for cred in pool.list(category)
            if _looks_like_embedding_catalog(
                getattr(cred, "base_url", None),
                getattr(cred, "model", None),
            )
        ]
    except Exception:
        logger.debug("Key pool listing failed while resolving embedding candidates", exc_info=True)
        return []

    if not credentials:
        return []

    wants_multimodal = _is_multimodal_embedding_catalog(target_base_url, target_model or default_model)
    ordered = sorted(
        credentials,
        key=lambda cred: (
            _is_multimodal_embedding_catalog(
                getattr(cred, "base_url", None),
                getattr(cred, "model", None),
            ) != wants_multimodal,
            int(getattr(cred, "line_no", 0) or 0),
        ),
    )

    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for cred in ordered:
        api_key = _clean(getattr(cred, "api_key", None))
        base_url = _clean_urlish(getattr(cred, "base_url", None))
        model = _clean(getattr(cred, "model", None))
        if not api_key or not base_url or not model:
            continue
        sig = _candidate_signature(api_key, base_url, model)
        if sig in seen:
            continue
        seen.add(sig)
        out.append((api_key, base_url, model, f"key-pool:{getattr(cred, 'provider', 'unknown')}"))
    return out


def _first_embedding_credential_from_key_pool(default_model: str) -> tuple[str, str, str] | None:
    candidates = _embedding_candidates_from_key_pool(default_model)
    if not candidates:
        return None
    api_key, base_url, model, _source = candidates[0]
    return api_key, base_url, model


def resolve_embedding_candidates(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    default_base_url: str,
    default_model: str,
) -> list[tuple[str, str, str, str]]:
    """Return ordered embedding candidates as (api_key, base_url, model, source)."""
    provider = _select_embedding_provider()

    if provider == "jina":
        resolved_base_url = (
            _clean_urlish(base_url)
            or env_value(
                "JINA_EMBEDDING_BASE_URL",
                "EMBEDDING_BASE_URL",
                "BASE_URL",
                default=DEFAULT_JINA_EMBEDDING_BASE_URL,
            )
            or DEFAULT_JINA_EMBEDDING_BASE_URL
        )
        resolved_model = (
            _clean(model)
            or env_value(
                "JINA_EMBEDDING_MODEL",
                "EMBEDDING_MODEL",
                "MODEL",
                default=DEFAULT_JINA_EMBEDDING_MODEL,
            )
            or DEFAULT_JINA_EMBEDDING_MODEL
        )
        env_candidates = _jina_embedding_candidates()
    else:
        resolved_base_url = (
            _clean_urlish(base_url)
            or env_value(
                "SILICONFLOW_EMBEDDING_BASE_URL",
                "EMBEDDING_BASE_URL",
                "BASE_URL",
                default=default_base_url,
            )
            or default_base_url
        )
        resolved_model = (
            _clean(model)
            or env_value(
                "SILICONFLOW_EMBEDDING_MODEL",
                "EMBEDDING_MODEL",
                "MODEL",
                default=default_model,
            )
            or default_model
        )
        env_candidates = _siliconflow_embedding_candidates()

    explicit_api_key = _clean(api_key)
    if explicit_api_key is not None:
        return [(explicit_api_key, resolved_base_url, resolved_model, "explicit")]

    candidates: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for candidate in _embedding_candidates_from_key_pool(
        default_model,
        target_base_url=resolved_base_url,
        target_model=resolved_model,
    ):
        api_key_value, base_url_value, model_value, source = candidate
        sig = _candidate_signature(api_key_value, base_url_value, model_value)
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append((api_key_value, base_url_value, model_value, source))

    for _priority, candidate_key, source in env_candidates:
        sig = _candidate_signature(candidate_key, resolved_base_url, resolved_model)
        if sig in seen:
            continue
        seen.add(sig)
        candidates.append((candidate_key, resolved_base_url, resolved_model, source))

    return candidates


def build_embedding_failover_pool(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    default_base_url: str,
    default_model: str,
    cooldown_seconds: float = DEFAULT_EMBEDDING_FAILOVER_COOLDOWN_SECONDS,
):
    """Build a KeyPool for embedding consumers using resolved candidates."""
    try:
        from key_pool import Credential, KeyPool
    except Exception:
        return None

    candidates = resolve_embedding_candidates(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=default_base_url,
        default_model=default_model,
    )
    if not candidates:
        return None

    creds = [
        Credential(
            category="embedding",
            provider=source,
            api_key=candidate_key,
            base_url=candidate_base_url,
            model=candidate_model,
        )
        for candidate_key, candidate_base_url, candidate_model, source in candidates
    ]
    return KeyPool(
        {"embedding": creds, "rerank": [], "generation": []},
        cooldown_seconds=cooldown_seconds,
    )


def resolve_embedding_config(
    api_key: str | None = None,
    *,
    base_url: str | None = None,
    model: str | None = None,
    default_base_url: str,
    default_model: str,
    probe_candidates: bool = True,
) -> tuple[str | None, str, str]:
    """Validity-first embedding credential resolution.

    Per `notes/2026-04-25-morpheus-key-resolution-audit.md`:
      - Explicit caller-passed `api_key` is trusted without probing.
      - `EMBEDDING_KEY_PROBE_DISABLE=1` restores the legacy static-order path.
      - Otherwise each candidate is probed; first 2xx wins; all-fail falls
        back to the first candidate with a loud WARN log.
      - `RERANK_API_KEY` is no longer accepted as an embedding credential
        (Gap B closed).
      - The `/v1/rerank → /v1/embeddings` string-replace heuristic is removed
        (Gap C closed). A misconfigured base URL will now fail its probe
        loudly instead of silently rewriting.
    """
    explicit_api_key = _clean(api_key)
    explicit_base_url = _clean_urlish(base_url)
    explicit_model = _clean(model)

    # Runtime override layer (Settings UI writes to embedding_override.json)
    try:
        from model_config_store import embedding_store
        override_api_key = embedding_store.get_resolved_field("api_key")
        override_base_url = embedding_store.get_resolved_field("base_url")
        override_model = embedding_store.get_resolved_field("model")
    except ImportError:
        override_api_key = override_base_url = override_model = None

    provider = _select_embedding_provider()
    if provider == "jina":
        resolved_base_url = (
            explicit_base_url
            or override_base_url
            or env_value(
                "JINA_EMBEDDING_BASE_URL",
                "EMBEDDING_BASE_URL",
                "BASE_URL",
                default=DEFAULT_JINA_EMBEDDING_BASE_URL,
            )
            or DEFAULT_JINA_EMBEDDING_BASE_URL
        )
        resolved_model = (
            explicit_model
            or override_model
            or env_value(
                "JINA_EMBEDDING_MODEL",
                "EMBEDDING_MODEL",
                "MODEL",
                default=DEFAULT_JINA_EMBEDDING_MODEL,
            )
            or DEFAULT_JINA_EMBEDDING_MODEL
        )
    else:
        resolved_base_url = (
            explicit_base_url
            or override_base_url
            or env_value(
                "SILICONFLOW_EMBEDDING_BASE_URL",
                "EMBEDDING_BASE_URL",
                "BASE_URL",
                default=default_base_url,
            )
            or default_base_url
        )
        resolved_model = (
            explicit_model
            or override_model
            or env_value(
                "SILICONFLOW_EMBEDDING_MODEL",
                "EMBEDDING_MODEL",
                "MODEL",
                default=default_model,
            )
            or default_model
        )

    if explicit_api_key is not None:
        return explicit_api_key, resolved_base_url, resolved_model

    if override_api_key:
        return override_api_key, resolved_base_url, resolved_model

    def _finalize_candidate(
        candidate_key: str,
        candidate_base_url: str,
        candidate_model: str,
    ) -> tuple[str, str, str]:
        return (
            candidate_key,
            explicit_base_url or candidate_base_url or resolved_base_url,
            explicit_model or candidate_model or resolved_model,
        )

    candidates = resolve_embedding_candidates(
        api_key,
        base_url=base_url,
        model=model,
        default_base_url=default_base_url,
        default_model=default_model,
    )

    if not probe_candidates:
        if candidates:
            candidate_key, candidate_base_url, candidate_model, _source = candidates[0]
            return _finalize_candidate(candidate_key, candidate_base_url, candidate_model)
        return None, resolved_base_url, resolved_model

    # Kill switch: restore legacy static-order behaviour (first candidate wins,
    # no probe). Matches reranker_client's RERANK_KEY_PROBE_DISABLE.
    if env_value("EMBEDDING_KEY_PROBE_DISABLE") == "1":
        if candidates:
            candidate_key, candidate_base_url, candidate_model, _source = candidates[0]
            return _finalize_candidate(candidate_key, candidate_base_url, candidate_model)
        return None, resolved_base_url, resolved_model

    # Validity-first: try each candidate, first 2xx wins.
    for candidate_key, candidate_base_url, candidate_model, source in candidates:
        if _probe_embedding_key(candidate_key, candidate_base_url, candidate_model):
            logger.info(
                "Embedding key selected: source=%s key_len=%d",
                source,
                len(candidate_key),
            )
            return _finalize_candidate(candidate_key, candidate_base_url, candidate_model)

    # All probes failed — fall back to first candidate with loud WARN.
    if candidates:
        fallback_key, fallback_base_url, fallback_model, fallback_source = candidates[0]
        logger.warning(
            "All embedding key probes failed; falling back to static order "
            "(source=%s). Expect 401/403 downstream.",
            fallback_source,
        )
        return _finalize_candidate(fallback_key, fallback_base_url, fallback_model)

    logger.error("No embedding credential found in configured environment variables.")
    return None, resolved_base_url, resolved_model


__all__ = [
    "build_embedding_request_payload",
    "build_embedding_failover_pool",
    "env_value",
    "extract_embedding_vectors",
    "is_dashscope_multimodal_embedding_config",
    "resolve_embedding_request_url",
    "resolve_embedding_candidates",
    "resolve_embedding_config",
    "resolve_llm_config",
    "_probe_embedding_key",
]

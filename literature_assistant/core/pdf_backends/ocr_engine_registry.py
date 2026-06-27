# -*- coding: utf-8 -*-
"""OCR engine registry and runtime selection policy."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .ocr_engine import (
    OcrEngine,
    OcrEngineInfo,
    OcrPolicy,
    OcrReadinessStatus,
    OcrRuntimeConfig,
)


OCR_POLICY_ENV_VAR = "LITASSIST_OCR_POLICY"
OCR_ENGINE_ENV_VAR = "LITASSIST_OCR_ENGINE"
OCR_LANGUAGE_ENV_VAR = "LITASSIST_OCR_LANG"
OCR_CONFIG_PATH_ENV_VAR = "LITASSIST_OCR_CONFIG_PATH"

_ALLOWED_POLICIES: set[str] = {"auto", "none", "engine"}
_ENGINE_FACTORIES: dict[str, Callable[[Mapping[str, Any]], OcrEngine]] = {}
_BUILTINS_LOADED = False
_AUTO_PRIORITY = ("paddleocr_gpu", "rapidocr", "windows", "remote_api")
_SECRET_KEYS = {"api_key", "token", "secret", "password", "authorization"}
_READINESS_STATUSES: set[str] = {
    "ready",
    "dependency_missing",
    "configuration_required",
    "adapter_not_wired",
    "platform_unsupported",
    "unavailable",
}


def _default_config_path() -> Path:
    """Return the runtime config path, honoring test/runtime overrides."""

    raw = os.environ.get(OCR_CONFIG_PATH_ENV_VAR, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()

    try:
        from project_paths import runtime_state_path

        return runtime_state_path("ocr_config.json")
    except Exception:  # pragma: no cover - only for broken bootstrap paths
        return (Path.cwd() / "workspace_artifacts" / "runtime_state" / "ocr_config.json").resolve()


def _normalize_policy(value: Any) -> OcrPolicy:
    text = str(value or "auto").strip().lower()
    if text not in _ALLOWED_POLICIES:
        raise ValueError("OCR policy must be one of: auto, none, engine")
    return text  # type: ignore[return-value]


def _normalize_engine_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _normalize_language(value: Any) -> str:
    text = str(value or "en").strip()
    if not text:
        raise ValueError("OCR language must be non-empty")
    if len(text) > 32:
        raise ValueError("OCR language must be 32 characters or fewer")
    return text


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("OCR config file must contain a JSON object")
    return data


def _redact_config(config: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in config.items():
        key_text = str(key)
        if key_text.lower() in _SECRET_KEYS:
            redacted[key_text] = "***"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            redacted[key_text] = value
        else:
            redacted[key_text] = str(type(value).__name__)
    return redacted


def _coerce_readiness_status(value: Any) -> OcrReadinessStatus:
    text = str(value or "unavailable").strip().lower()
    if text in _READINESS_STATUSES:
        return text  # type: ignore[return-value]
    return "unavailable"


def _derive_readiness_status(reason: str | None) -> OcrReadinessStatus:
    text = str(reason or "").lower()
    if "not installed" in text:
        return "dependency_missing"
    if "requires explicit" in text or "configuration" in text:
        return "configuration_required"
    if "not wired" in text:
        return "adapter_not_wired"
    if "only on windows" in text or "platform" in text:
        return "platform_unsupported"
    return "unavailable"


def _engine_readiness_status(
    engine: OcrEngine,
    *,
    available: bool,
    unavailable_reason: str | None,
) -> OcrReadinessStatus:
    if available:
        return "ready"
    readiness_attr = getattr(engine, "readiness_status", None)
    if callable(readiness_attr):
        return _coerce_readiness_status(readiness_attr())
    return _derive_readiness_status(unavailable_reason)


def _engine_readiness_blockers(
    engine: OcrEngine,
    *,
    available: bool,
    unavailable_reason: str | None,
) -> tuple[str, ...]:
    if available:
        return ()
    blockers_attr = getattr(engine, "readiness_blockers", None)
    if callable(blockers_attr):
        raw_blockers = blockers_attr()
        if isinstance(raw_blockers, (list, tuple)):
            blockers = tuple(str(item).strip() for item in raw_blockers if str(item).strip())
            if blockers:
                return blockers[:5]
    return () if unavailable_reason is None else (unavailable_reason,)


def _ocr_engine_next_safe_local_actions(
    *,
    engine_name: str,
    engine_type: str,
    requires_network: bool,
    readiness_status: OcrReadinessStatus,
    readiness_blockers: tuple[str, ...],
) -> tuple[str, ...]:
    """Return bounded recovery/proof actions for one OCR readiness state."""

    if not isinstance(engine_name, str) or not engine_name.strip():
        raise ValueError("engine_name must be non-empty")

    name = engine_name.strip().lower()
    if readiness_status == "ready":
        if requires_network or engine_type == "remote":
            return (
                "Run literature.ocr_execution_probe only with confirm_execution=true, "
                "a bounded image, and explicit remote upload consent.",
            )
        return (
            "Run literature.ocr_execution_probe with confirm_execution=true on a "
            "small local image to prove OCR execution.",
        )

    if readiness_status == "dependency_missing":
        if name == "paddleocr_gpu":
            return (
                "Install or point to a local PaddleOCR Python runtime, then set "
                "python_executable or LITASSIST_PADDLEOCR_PYTHON and rerun literature.ocr_health.",
            )
        if name == "rapidocr":
            return (
                "Install or point to a local RapidOCR Python runtime, then set "
                "python_executable or LITASSIST_RAPIDOCR_PYTHON and rerun literature.ocr_health.",
            )
        if name == "windows":
            return (
                "Verify Windows PowerShell and Windows.Media.Ocr are available, "
                "then rerun literature.ocr_health for the windows engine.",
            )
        return ("Install the missing local OCR dependency and rerun literature.ocr_health.",)

    if readiness_status == "configuration_required":
        if name == "remote_api":
            return (
                "Configure remote_api with local api_key and base_url references; "
                "set allow_remote_upload=true only after explicit upload consent.",
                "Rerun literature.ocr_health before any literature.ocr_execution_probe call.",
            )
        return (
            "Update the local OCR runtime config for this engine and rerun literature.ocr_health.",
        )

    if readiness_status == "adapter_not_wired":
        return (
            "Keep OCR policy on auto/none or choose another ready engine until "
            "this adapter has a wired execution path and tests.",
        )

    if readiness_status == "platform_unsupported":
        return (
            "Choose a supported local OCR engine for this platform, or rerun this engine on a supported host.",
        )

    blocker = readiness_blockers[0] if readiness_blockers else "the readiness blocker"
    return (f"Resolve {blocker} and rerun literature.ocr_health.",)


def _ocr_runtime_next_safe_local_actions(
    *,
    config: OcrRuntimeConfig,
    selected_engine_name: str | None,
    warning: str | None,
) -> tuple[str, ...]:
    """Return bounded runtime-level OCR recovery/proof actions."""

    if selected_engine_name:
        return (
            "Run literature.ocr_health for the selected engine before OCR execution.",
            "Run literature.ocr_execution_probe with confirm_execution=true on a "
            "small bounded image to prove execution.",
        )
    if config.policy == "none":
        return (
            "Set LITASSIST_OCR_POLICY=auto or select a configured engine before ingesting scanned PDFs.",
        )
    if config.policy == "engine" and config.engine:
        return (
            f"Inspect literature.ocr_engines for {config.engine} readiness_blockers "
            "and rerun literature.ocr_health after local config changes.",
        )
    if warning:
        return (
            "Inspect literature.ocr_engines for readiness_blockers and choose a "
            "ready local engine or configure one explicitly.",
            "Do not run literature.ocr_execution_probe until an engine is selected "
            "and confirm_execution=true is intentional.",
        )
    return ("Inspect literature.ocr_engines before running OCR execution probes.",)


def ocr_engine_next_safe_local_actions(
    *,
    engine_name: str,
    engine_type: str,
    requires_network: bool,
    readiness_status: OcrReadinessStatus,
    readiness_blockers: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return bounded recovery/proof actions for OCR API payloads."""

    return _ocr_engine_next_safe_local_actions(
        engine_name=engine_name,
        engine_type=engine_type,
        requires_network=requires_network,
        readiness_status=readiness_status,
        readiness_blockers=tuple(readiness_blockers),
    )


def register_ocr_engine(
    name: str,
    factory: Callable[[Mapping[str, Any]], OcrEngine],
) -> None:
    """Register an OCR engine factory.

    Args:
        name: Stable lowercase engine id.
        factory: Callable receiving engine-specific config and returning an
            ``OcrEngine``.
    """

    normalized = _normalize_engine_name(name)
    if normalized is None:
        raise ValueError("OCR engine name must be non-empty")
    if not callable(factory):
        raise TypeError("OCR engine factory must be callable")
    _ENGINE_FACTORIES[normalized] = factory


def clear_ocr_engines_for_tests() -> None:
    """Clear registered engines for isolated unit tests."""

    global _BUILTINS_LOADED
    _ENGINE_FACTORIES.clear()
    _BUILTINS_LOADED = False


def load_builtin_ocr_engines() -> None:
    """Register built-in optional OCR engine adapters idempotently."""

    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return

    from .ocr_builtin_engines import (
        PaddleOcrGpuEngine,
        RapidOcrEngine,
        RemoteApiOcrEngine,
        WindowsOcrEngine,
    )

    register_ocr_engine("paddleocr_gpu", lambda config: PaddleOcrGpuEngine(config))
    register_ocr_engine("rapidocr", lambda config: RapidOcrEngine(config))
    register_ocr_engine("windows", lambda config: WindowsOcrEngine(config))
    register_ocr_engine("remote_api", lambda config: RemoteApiOcrEngine(config))
    _BUILTINS_LOADED = True


def list_ocr_engine_names(*, include_builtins: bool = True) -> list[str]:
    """Return registered engine ids."""

    if include_builtins:
        load_builtin_ocr_engines()
    return sorted(_ENGINE_FACTORIES)


def build_ocr_engine(
    name: str,
    config: Mapping[str, Any] | None = None,
    *,
    include_builtins: bool = True,
) -> OcrEngine:
    """Build a registered OCR engine by id."""

    if include_builtins:
        load_builtin_ocr_engines()
    normalized = _normalize_engine_name(name)
    if normalized is None:
        raise ValueError("OCR engine name must be non-empty")
    factory = _ENGINE_FACTORIES.get(normalized)
    if factory is None:
        raise ValueError(f"Unknown OCR engine: {normalized}")
    return factory(dict(config or {}))


def resolve_ocr_runtime_config(
    *,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> OcrRuntimeConfig:
    """Resolve OCR policy from config file and environment variables.

    Environment variables override the runtime config file. The default policy
    is ``auto`` so OCR can be triggered only when ingestion detects scanned
    pages; no pages detected means zero OCR calls.
    """

    env_map = env if env is not None else os.environ
    path = config_path or _default_config_path()
    file_data = _read_config_file(path)
    engine_config = file_data.get("engine_config", {})
    if engine_config is None:
        engine_config = {}
    if not isinstance(engine_config, dict):
        raise ValueError("OCR engine_config must be a JSON object")

    policy_value: Any = file_data.get("policy", "auto")
    engine_value: Any = file_data.get("engine")
    language_value: Any = file_data.get("language", "en")
    source = "config" if file_data else "default"

    if str(env_map.get(OCR_POLICY_ENV_VAR, "")).strip():
        policy_value = env_map[OCR_POLICY_ENV_VAR]
        source = "env"
    if str(env_map.get(OCR_ENGINE_ENV_VAR, "")).strip():
        engine_value = env_map[OCR_ENGINE_ENV_VAR]
        source = "env"
    if str(env_map.get(OCR_LANGUAGE_ENV_VAR, "")).strip():
        language_value = env_map[OCR_LANGUAGE_ENV_VAR]
        source = "env"

    policy = _normalize_policy(policy_value)
    engine = _normalize_engine_name(engine_value)
    language = _normalize_language(language_value)

    if policy == "engine" and engine is None:
        raise ValueError("OCR policy 'engine' requires an engine id")
    if policy == "none":
        engine = None

    return OcrRuntimeConfig(
        policy=policy,
        engine=engine,
        language=language,
        source=source,  # type: ignore[arg-type]
        engine_config=engine_config,
    )


def write_ocr_runtime_config(
    config: OcrRuntimeConfig,
    *,
    config_path: Path | None = None,
) -> Path:
    """Atomically write the local OCR runtime config."""

    path = config_path or _default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "policy": config.policy,
        "engine": config.engine,
        "language": config.language,
        "engine_config": dict(config.engine_config),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def list_ocr_engine_info(
    *,
    engine_config: Mapping[str, Any] | None = None,
) -> list[OcrEngineInfo]:
    """Return public metadata for all registered OCR engines."""

    load_builtin_ocr_engines()
    config = dict(engine_config or {})
    items: list[OcrEngineInfo] = []
    for name in list_ocr_engine_names(include_builtins=False):
        engine = build_ocr_engine(name, config, include_builtins=False)
        available = engine.is_available()
        unavailable_reason = None if available else engine.unavailable_reason()
        readiness_status = _engine_readiness_status(
            engine,
            available=available,
            unavailable_reason=unavailable_reason,
        )
        readiness_blockers = _engine_readiness_blockers(
            engine,
            available=available,
            unavailable_reason=unavailable_reason,
        )
        next_safe_local_actions = _ocr_engine_next_safe_local_actions(
            engine_name=engine.name,
            engine_type=engine.engine_type,
            requires_network=engine.requires_network,
            readiness_status=readiness_status,
            readiness_blockers=readiness_blockers,
        )
        items.append(
            OcrEngineInfo(
                name=engine.name,
                display_name=engine.display_name,
                engine_type=engine.engine_type,
                available=available,
                requires_network=engine.requires_network,
                unavailable_reason=unavailable_reason,
                readiness_status=readiness_status,
                readiness_blockers=readiness_blockers,
                next_safe_local_actions=next_safe_local_actions,
            )
        )
    return items


def select_ocr_engine(
    runtime_config: OcrRuntimeConfig | None = None,
) -> tuple[OcrEngine | None, str | None]:
    """Select an OCR engine for a scanned-page workload.

    Returns:
        ``(engine, warning)`` where ``engine`` is None when OCR is disabled or
        no registered engine is available.
    """

    config = runtime_config or resolve_ocr_runtime_config()
    if config.policy == "none":
        return None, "OCR policy is none"

    if config.engine:
        engine = build_ocr_engine(config.engine, config.engine_config)
        if engine.is_available():
            return engine, None
        return None, engine.unavailable_reason() or f"OCR engine {config.engine} is unavailable"

    if config.policy == "engine":
        return None, "OCR policy is engine but no engine id was configured"

    available_by_name: dict[str, OcrEngine] = {}
    for name in list_ocr_engine_names():
        engine = build_ocr_engine(name, config.engine_config, include_builtins=False)
        if engine.is_available():
            available_by_name[name] = engine
    for preferred in _AUTO_PRIORITY:
        engine = available_by_name.get(preferred)
        if engine is not None:
            return engine, None
    return None, "OCR policy is auto but no available OCR engine was found"


def public_ocr_status(
    runtime_config: OcrRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Return redacted OCR runtime status for API responses."""

    config = runtime_config or resolve_ocr_runtime_config()
    selected, warning = select_ocr_engine(config)
    selected_engine_name = selected.name if selected is not None else None
    return {
        "policy": config.policy,
        "configured_engine": config.engine,
        "selected_engine": selected_engine_name,
        "language": config.language,
        "source": config.source,
        "engine_config": _redact_config(config.engine_config),
        "available_engines": [
            item.as_dict() for item in list_ocr_engine_info(engine_config=config.engine_config)
        ],
        "warning": warning,
        "next_safe_local_actions": list(
            _ocr_runtime_next_safe_local_actions(
                config=config,
                selected_engine_name=selected_engine_name,
                warning=warning,
            )
        ),
    }

"""Manifest config-schema normalization for MCP packages and user Skills."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


CONFIG_SCHEMA_KEYS = (
    "config_schema",
    "settings_schema",
    "configuration_schema",
    "runtime_config_schema",
)
"""Supported manifest keys for schema-driven runtime settings."""


_SECRET_FIELD_PATTERN = re.compile(
    r"(?:api[_\-\s]?key|apikey|token|secret|password|authorization|bearer|"
    r"access[_\-\s]?key|密钥|令牌|密码|访问凭证)",
    re.IGNORECASE,
)
_CAMEL_BOUNDARY_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")
_IDENTIFIER_CLEANUP_PATTERN = re.compile(r"[^a-zA-Z0-9]+")
_ENV_CLEANUP_PATTERN = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True)
class DynamicConfigOptionSpec:
    """One preset option from a schema enum.

    Shape: string value plus visible label. Values are persisted as strings at
    the runtime boundary so existing env injection remains compatible.
    """

    value: str
    label: str


@dataclass(frozen=True)
class DynamicConfigFieldSpec:
    """Non-secret runtime config field derived from a manifest schema."""

    id: str
    label: str
    env: str
    type: str
    default: str | None = None
    required: bool = False
    description: str = ""
    options: list[DynamicConfigOptionSpec] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None


@dataclass(frozen=True)
class DynamicCredentialSpec:
    """Credential-binding slot derived from a secret-like schema property."""

    id: str
    label: str
    env: str
    kind: str = "api_key"
    provider_hints: list[str] = field(default_factory=list)
    required: bool = True
    description: str = ""


@dataclass(frozen=True)
class DynamicConfigSchemaParseResult:
    """Normalized dynamic settings extracted from a manifest schema."""

    config_fields: list[DynamicConfigFieldSpec] = field(default_factory=list)
    required_credentials: list[DynamicCredentialSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def extract_dynamic_config_schema(manifest_data: Mapping[str, Any]) -> Any | None:
    """Return the first supported config schema block from manifest data.

    Input must be a mapping-like manifest. Output is the raw schema object or
    ``None``. The function is read-only and does not validate the whole
    manifest.
    """

    if not isinstance(manifest_data, Mapping):
        raise TypeError("manifest_data must be a mapping")
    for key in CONFIG_SCHEMA_KEYS:
        if key in manifest_data:
            return manifest_data[key]
    return None


def parse_dynamic_config_schema(
    raw_schema: Any,
    *,
    existing_config_keys: set[str] | None = None,
    existing_credential_keys: set[str] | None = None,
) -> DynamicConfigSchemaParseResult:
    """Convert a JSON-Schema-like object into runtime config fields.

    Supported input shape: object schema with ``properties`` and optional
    ``required``. Unsupported property types are skipped with warnings. Secret
    properties become credential bindings instead of plain config values.
    """

    if raw_schema is None:
        return DynamicConfigSchemaParseResult()
    if not isinstance(raw_schema, Mapping):
        return DynamicConfigSchemaParseResult(
            warnings=["config schema must be an object; ignored"]
        )

    properties = raw_schema.get("properties")
    if not isinstance(properties, Mapping):
        return DynamicConfigSchemaParseResult(
            warnings=["config schema properties must be an object; ignored"]
        )

    required_names = _read_required_names(raw_schema.get("required"))
    config_keys = set(existing_config_keys or set())
    credential_keys = set(existing_credential_keys or set())
    fields: list[DynamicConfigFieldSpec] = []
    credentials: list[DynamicCredentialSpec] = []
    warnings: list[str] = []

    for property_name, property_schema in list(properties.items())[:64]:
        if not isinstance(property_name, str) or not property_name.strip():
            warnings.append("config schema property name must be a non-empty string; skipped")
            continue
        if not isinstance(property_schema, Mapping):
            warnings.append(f"config schema property {property_name!r} must be an object; skipped")
            continue

        spec_base = _read_property_base(property_name, property_schema)
        dedupe_keys = {spec_base["id"], spec_base["env"]}
        is_required = property_name in required_names
        if _is_secret_property(property_name, property_schema):
            if dedupe_keys & credential_keys:
                continue
            credential_keys.update(dedupe_keys)
            credentials.append(
                DynamicCredentialSpec(
                    id=spec_base["id"],
                    label=spec_base["label"],
                    env=spec_base["env"],
                    provider_hints=_read_string_list(
                        property_schema.get("provider_hints")
                        or property_schema.get("x-provider-hints")
                        or property_schema.get("x_provider_hints"),
                        max_items=16,
                    ),
                    required=is_required or bool(property_schema.get("required", False)),
                    description=_bounded_text(
                        _read_string(property_schema.get("description")), 512
                    ),
                )
            )
            continue

        if dedupe_keys & config_keys:
            continue
        parsed_field = _parse_field_spec(property_name, property_schema, spec_base, is_required)
        if parsed_field is None:
            warnings.append(
                f"config schema property {property_name!r} has unsupported type; skipped"
            )
            continue
        config_keys.update(dedupe_keys)
        fields.append(parsed_field)

    return DynamicConfigSchemaParseResult(
        config_fields=fields,
        required_credentials=credentials,
        warnings=warnings,
    )


def _parse_field_spec(
    property_name: str,
    property_schema: Mapping[str, Any],
    spec_base: Mapping[str, str],
    is_required: bool,
) -> DynamicConfigFieldSpec | None:
    options = _read_options(property_schema)
    field_type = _infer_field_type(property_schema, has_options=bool(options))
    if field_type is None:
        return None

    return DynamicConfigFieldSpec(
        id=spec_base["id"],
        label=spec_base["label"],
        env=spec_base["env"],
        type=field_type,
        default=_normalize_default(field_type, property_schema.get("default")),
        required=is_required or bool(property_schema.get("required", False)),
        description=_bounded_text(_read_string(property_schema.get("description")), 512),
        options=options if field_type == "select" else None,
        min=_parse_optional_number(
            property_schema.get("minimum")
            if "minimum" in property_schema
            else property_schema.get("min")
        ),
        max=_parse_optional_number(
            property_schema.get("maximum")
            if "maximum" in property_schema
            else property_schema.get("max")
        ),
        step=_parse_optional_number(
            property_schema.get("multipleOf")
            if "multipleOf" in property_schema
            else property_schema.get("step")
        ) or (1.0 if _read_schema_type(property_schema) == "integer" else None),
    )


def _read_property_base(property_name: str, property_schema: Mapping[str, Any]) -> dict[str, str]:
    raw_id = (
        property_schema.get("x-lit-id")
        or property_schema.get("x_lit_id")
        or property_schema.get("id")
        or property_name
    )
    raw_env = (
        property_schema.get("x-lit-env")
        or property_schema.get("x_env")
        or property_schema.get("env")
        or _default_env_from_property(property_name)
    )
    raw_label = property_schema.get("title") or property_schema.get("label")
    label = _bounded_text(_read_string(raw_label) or _humanize_key(property_name), 128)
    return {
        "id": _normalize_id(_read_string(raw_id) or property_name),
        "label": label,
        "env": _read_string(raw_env) or _default_env_from_property(property_name),
    }


def _read_required_names(raw_required: Any) -> set[str]:
    if not isinstance(raw_required, Sequence) or isinstance(raw_required, (str, bytes)):
        return set()
    return {item.strip() for item in raw_required if isinstance(item, str) and item.strip()}


def _is_secret_property(property_name: str, property_schema: Mapping[str, Any]) -> bool:
    classifier = " ".join(
        part
        for part in (
            property_name,
            _read_string(property_schema.get("title")),
            _read_string(property_schema.get("label")),
            _read_string(property_schema.get("description")),
            _read_string(property_schema.get("env")),
            _read_string(property_schema.get("x-lit-env")),
        )
        if part
    )
    return bool(_SECRET_FIELD_PATTERN.search(classifier))


def _infer_field_type(property_schema: Mapping[str, Any], *, has_options: bool) -> str | None:
    if has_options:
        return "select"
    schema_type = _read_schema_type(property_schema)
    if schema_type in {"string", None}:
        return "text"
    if schema_type in {"number", "integer"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    return None


def _read_schema_type(property_schema: Mapping[str, Any]) -> str | None:
    raw_type = property_schema.get("type")
    if isinstance(raw_type, str):
        return raw_type.strip().lower() or None
    if isinstance(raw_type, Sequence) and not isinstance(raw_type, (str, bytes)):
        for item in raw_type:
            if isinstance(item, str) and item.strip().lower() != "null":
                return item.strip().lower()
    return None


def _read_options(property_schema: Mapping[str, Any]) -> list[DynamicConfigOptionSpec] | None:
    enum_values = property_schema.get("enum")
    if isinstance(enum_values, Sequence) and not isinstance(enum_values, (str, bytes)):
        labels = _read_enum_labels(property_schema, enum_values)
        options: list[DynamicConfigOptionSpec] = []
        for index, raw_value in enumerate(list(enum_values)[:64]):
            value = _scalar_to_string(raw_value)
            if value is None:
                continue
            label = _bounded_text(labels.get(value) or labels.get(str(index)) or value, 128)
            options.append(DynamicConfigOptionSpec(value=value, label=label))
        return options or None

    for compound_key in ("oneOf", "anyOf"):
        compound = property_schema.get(compound_key)
        if not isinstance(compound, Sequence) or isinstance(compound, (str, bytes)):
            continue
        options = []
        for item in list(compound)[:64]:
            if not isinstance(item, Mapping) or "const" not in item:
                continue
            value = _scalar_to_string(item.get("const"))
            if value is None:
                continue
            label = _bounded_text(
                _read_string(item.get("title") or item.get("label")) or value,
                128,
            )
            options.append(DynamicConfigOptionSpec(value=value, label=label))
        if options:
            return options
    return None


def _read_enum_labels(
    property_schema: Mapping[str, Any],
    enum_values: Sequence[Any],
) -> dict[str, str]:
    labels_raw = (
        property_schema.get("enumNames")
        or property_schema.get("x-enum-labels")
        or property_schema.get("x_enum_labels")
    )
    if isinstance(labels_raw, Mapping):
        return {
            str(key): str(value).strip()
            for key, value in labels_raw.items()
            if str(key).strip() and str(value).strip()
        }
    if isinstance(labels_raw, Sequence) and not isinstance(labels_raw, (str, bytes)):
        labels: dict[str, str] = {}
        for index, raw_label in enumerate(labels_raw[: len(enum_values)]):
            if not isinstance(raw_label, str) or not raw_label.strip():
                continue
            raw_value = enum_values[index]
            value = _scalar_to_string(raw_value)
            if value is not None:
                labels[value] = raw_label.strip()
                labels[str(index)] = raw_label.strip()
        return labels
    return {}


def _normalize_id(raw: str) -> str:
    snake = _CAMEL_BOUNDARY_PATTERN.sub("_", raw.strip())
    cleaned = _IDENTIFIER_CLEANUP_PATTERN.sub("_", snake.lower()).strip("_")
    return cleaned[:64] or "config"


def _default_env_from_property(property_name: str) -> str:
    snake = _CAMEL_BOUNDARY_PATTERN.sub("_", property_name.strip())
    cleaned = _ENV_CLEANUP_PATTERN.sub("_", snake.upper()).strip("_")
    return cleaned[:128] or "CONFIG"


def _humanize_key(property_name: str) -> str:
    spaced = _IDENTIFIER_CLEANUP_PATTERN.sub(" ", property_name.strip()).strip()
    if not spaced:
        return "Config"
    return " ".join(word[:1].upper() + word[1:] for word in spaced.split())


def _read_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bounded_text(value: str, max_length: int) -> str:
    stripped = value.strip()
    return stripped[:max_length]


def _read_string_list(raw: Any, *, max_items: int) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    return [item.strip() for item in raw[:max_items] if isinstance(item, str) and item.strip()]


def _scalar_to_string(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return str(value)
    if isinstance(value, str):
        return value
    return None


def _normalize_default(field_type: str, raw: Any) -> str | None:
    if raw is None:
        return None
    if field_type == "boolean":
        if isinstance(raw, bool):
            return "true" if raw else "false"
        normalized = str(raw).strip().lower()
        return "true" if normalized in {"1", "true", "yes", "on"} else "false"
    return _scalar_to_string(raw) if _scalar_to_string(raw) is not None else str(raw)


def _parse_optional_number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        parsed = float(raw)
        return parsed if math.isfinite(parsed) else None
    if isinstance(raw, str):
        try:
            parsed = float(raw.strip())
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


__all__ = [
    "CONFIG_SCHEMA_KEYS",
    "DynamicConfigFieldSpec",
    "DynamicConfigOptionSpec",
    "DynamicConfigSchemaParseResult",
    "DynamicCredentialSpec",
    "extract_dynamic_config_schema",
    "parse_dynamic_config_schema",
]

# -*- coding: utf-8 -*-
"""User Skill manifest parser and validator.

Parses SKILL.md frontmatter into a typed UserSkillManifest dataclass and
validates all fields according to the security rules defined in the
user-skill-extension-design.md.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from dynamic_config_schema import (
    extract_dynamic_config_schema,
    parse_dynamic_config_schema,
)
from extension_secret_policy import is_plaintext_secret_config_field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

ALLOWED_KINDS = {"transform", "validator", "workflow", "domain", "style"}
ALLOWED_ENTRY_MODES = {"manual", "assistant", "hidden"}
ALLOWED_UI_VISIBILITY = {"simple_prompt", "skill_assisted", "both", "hidden"}
ALLOWED_SCOPES = {"selection", "section", "full_draft", "paragraph"}

PERMISSION_KEYS = frozenset({
    "model.llm",
    "model.embedding",
    "retrieval.read",
    "draft.read",
    "draft.write",
    "references.read",
    "files.read",
    "files.write",
    "network",
    "script.execute",
    "storage",
})

MAX_PACKAGE_FILES = 200
MAX_SINGLE_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_PACKAGE_BYTES = 20 * 1024 * 1024  # 20 MB

HIGH_RISK_PERMISSIONS = frozenset({"script.execute", "network", "files.write"})


# Skill credential / config-field allowlists. Mirror the allowlists used by
# McpInstallConfigField / McpRequiredCredential so MCP and Skill share the
# same install-time UX.
SKILL_CREDENTIAL_KINDS = frozenset({"api_key"})
SKILL_CONFIG_FIELD_TYPES = frozenset({"text", "select", "number", "boolean"})


# ---------------------------------------------------------------------------
# Manifest dataclass
# ---------------------------------------------------------------------------


@dataclass
class SkillRequiredCredential:
    """A credential reference slot the SkillManager binds via CredentialPicker.

    After import, the binding is recorded in ``CredentialBindingIndex``
    (owner_kind="skill") so the credentials center can show "used by" and
    the skill runtime can resolve env at execution time.
    """

    id: str
    label: str
    env: str
    kind: str = "api_key"
    provider_hints: list[str] = field(default_factory=list)
    required: bool = True
    description: str = ""


@dataclass
class SkillConfigField:
    """A non-sensitive config field the install wizard prompts for and the skill
    runtime injects into the execution env as a plain string.
    """

    id: str
    label: str
    env: str
    type: str = "text"
    default: str | None = None
    required: bool = False
    description: str = ""
    options: list[dict[str, str]] | None = None  # for type=select
    min: float | None = None
    max: float | None = None
    step: float | None = None


@dataclass
class UserSkillManifest:
    """Parsed and validated user skill manifest."""

    id: str
    name: str
    version: str
    kind: str
    description: str
    entry_mode: str = "manual"
    ui_visibility: str = "skill_assisted"
    supported_scopes: list[str] = field(default_factory=lambda: ["selection"])
    input_schema: str | None = None
    output_schema: str | None = None
    permissions: dict[str, bool] = field(default_factory=dict)
    root_policy: dict[str, Any] = field(default_factory=dict)
    script_policy: dict[str, Any] = field(default_factory=lambda: {
        "has_scripts": False,
        "safe_to_execute": False,
    })
    model_policy: dict[str, Any] = field(default_factory=lambda: {
        "allow_llm": False,
        "allow_embedding": False,
    })
    privacy_notes: str = ""
    rollback_hint: str = ""
    tags: list[str] = field(default_factory=list)
    display_group: str = "user"
    experimental: bool = False

    # Required credential bindings and non-sensitive config fields. Empty
    # lists by default so existing manifests parse without changes.
    required_credentials: list[SkillRequiredCredential] = field(default_factory=list)
    config_fields: list[SkillConfigField] = field(default_factory=list)

    # Computed at validation time
    high_risk_flags: list[str] = field(default_factory=list)

    def has_high_risk(self) -> bool:
        """Check if manifest declares any high-risk permissions."""
        return len(self.high_risk_flags) > 0

    def effective_permission(self, key: str) -> bool:
        """Return effective permission value (default deny)."""
        return self.permissions.get(key, False)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ManifestValidationError(ValueError):
    """Raised when a manifest fails validation with machine-readable errors."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Manifest validation failed: {'; '.join(errors)}")


def validate_manifest(data: dict[str, Any]) -> UserSkillManifest:
    """Validate raw frontmatter dict and return a typed UserSkillManifest.

    Raises ManifestValidationError with a list of all errors found.
    """
    errors: list[str] = []

    # --- Required fields ---
    skill_id = data.get("id", "")
    if not skill_id:
        errors.append("Missing required field: id")
    elif not VALID_ID_PATTERN.match(skill_id):
        errors.append(
            f"Invalid id '{skill_id}': must be ASCII lowercase, digits, dots, "
            f"hyphens, underscores; 2-128 chars; start with alphanumeric"
        )

    name = data.get("name", "")
    if not name:
        errors.append("Missing required field: name")

    version = data.get("version", "")
    if not version:
        errors.append("Missing required field: version")
    elif not SEMVER_PATTERN.match(version):
        errors.append(f"Invalid version '{version}': must be SemVer")

    kind = data.get("kind", "")
    if not kind:
        errors.append("Missing required field: kind")
    elif kind not in ALLOWED_KINDS:
        errors.append(f"Invalid kind '{kind}': must be one of {sorted(ALLOWED_KINDS)}")

    description = data.get("description", "")
    if not description:
        errors.append("Missing required field: description")

    # --- Optional fields with validation ---
    entry_mode = data.get("entry_mode", "manual")
    if entry_mode not in ALLOWED_ENTRY_MODES:
        errors.append(f"Invalid entry_mode '{entry_mode}': must be one of {sorted(ALLOWED_ENTRY_MODES)}")

    ui_visibility = data.get("ui_visibility", "skill_assisted")
    if ui_visibility not in ALLOWED_UI_VISIBILITY:
        errors.append(f"Invalid ui_visibility '{ui_visibility}': must be one of {sorted(ALLOWED_UI_VISIBILITY)}")

    supported_scopes = data.get("supported_scopes", ["selection"])
    if isinstance(supported_scopes, str):
        supported_scopes = [supported_scopes]
    for scope in supported_scopes:
        if scope not in ALLOWED_SCOPES:
            errors.append(f"Invalid scope '{scope}': must be one of {sorted(ALLOWED_SCOPES)}")

    # --- Path safety ---
    for path_key in ("input_schema", "output_schema"):
        path_val = data.get(path_key)
        if path_val:
            _validate_relative_path(path_val, path_key, errors)

    # --- Permissions (default deny) ---
    raw_permissions = data.get("permissions", {})
    permissions: dict[str, bool] = {}
    high_risk_flags: list[str] = []
    if isinstance(raw_permissions, dict):
        for key, val in raw_permissions.items():
            canonical = key.replace("-", ".").replace("_", ".")
            if canonical not in PERMISSION_KEYS:
                errors.append(f"Unknown permission key: '{key}'")
            else:
                permissions[canonical] = bool(val)
                if bool(val) and canonical in HIGH_RISK_PERMISSIONS:
                    high_risk_flags.append(canonical)

    # --- Script policy ---
    script_policy = data.get("script_policy", {"has_scripts": False, "safe_to_execute": False})
    if not isinstance(script_policy, dict):
        script_policy = {"has_scripts": False, "safe_to_execute": False}
    if script_policy.get("has_scripts") and script_policy.get("safe_to_execute"):
        # MVP: scripts cannot be marked safe by manifest alone
        errors.append("script_policy.safe_to_execute cannot be true in user manifests; scripts require explicit approval")

    # --- Model policy ---
    model_policy = data.get("model_policy", {"allow_llm": False, "allow_embedding": False})
    if not isinstance(model_policy, dict):
        model_policy = {"allow_llm": False, "allow_embedding": False}

    # --- Root policy ---
    root_policy = data.get("root_policy", {})
    if isinstance(root_policy, dict):
        allowed_roots = root_policy.get("allowed_roots", [])
        if isinstance(allowed_roots, list):
            for root in allowed_roots:
                if root not in ("skill_root", "project_root"):
                    errors.append(f"Invalid root '{root}' in root_policy.allowed_roots")

    # --- S5: required_credentials + config_fields ---
    required_credentials = _parse_required_credentials(
        data.get("required_credentials", []), errors
    )
    config_fields = _parse_config_fields(
        data.get("config_fields", []), errors
    )
    schema_result = parse_dynamic_config_schema(
        extract_dynamic_config_schema(data),
        existing_config_keys={
            key for config_field in config_fields for key in (config_field.id, config_field.env)
        },
        existing_credential_keys={
            key
            for credential in required_credentials
            for key in (credential.id, credential.env)
        },
    )
    required_credentials.extend(
        SkillRequiredCredential(
            id=credential.id,
            label=credential.label,
            env=credential.env,
            kind=credential.kind,
            provider_hints=list(credential.provider_hints),
            required=credential.required,
            description=credential.description,
        )
        for credential in schema_result.required_credentials
    )
    config_fields.extend(
        SkillConfigField(
            id=config_field.id,
            label=config_field.label,
            env=config_field.env,
            type=config_field.type,
            default=config_field.default,
            required=config_field.required,
            description=config_field.description,
            options=[
                {"value": option.value, "label": option.label}
                for option in config_field.options
            ]
            if config_field.options is not None
            else None,
            min=config_field.min,
            max=config_field.max,
            step=config_field.step,
        )
        for config_field in schema_result.config_fields
    )

    if errors:
        raise ManifestValidationError(errors)

    return UserSkillManifest(
        id=skill_id,
        name=name,
        version=version,
        kind=kind,
        description=description,
        entry_mode=entry_mode,
        ui_visibility=ui_visibility,
        supported_scopes=supported_scopes,
        input_schema=data.get("input_schema"),
        output_schema=data.get("output_schema"),
        permissions=permissions,
        root_policy=root_policy if isinstance(root_policy, dict) else {},
        script_policy=script_policy,
        model_policy=model_policy,
        privacy_notes=data.get("privacy_notes", ""),
        rollback_hint=data.get("rollback_hint", ""),
        tags=data.get("tags", []) if isinstance(data.get("tags"), list) else [],
        display_group=data.get("display_group", "user"),
        experimental=bool(data.get("experimental", False)),
        required_credentials=required_credentials,
        config_fields=config_fields,
        high_risk_flags=high_risk_flags,
    )


def _validate_relative_path(path_str: str, field_name: str, errors: list[str]) -> None:
    """Ensure a path is relative and stays within the skill root."""
    p = PurePosixPath(path_str)
    if p.is_absolute():
        errors.append(f"{field_name} must be a relative path, got '{path_str}'")
        return
    # Resolve '..' components
    try:
        parts = list(p.parts)
        resolved: list[str] = []
        for part in parts:
            if part == "..":
                if not resolved:
                    errors.append(f"{field_name} path traversal detected: '{path_str}'")
                    return
                resolved.pop()
            elif part != ".":
                resolved.append(part)
    except Exception:
        errors.append(f"{field_name} invalid path: '{path_str}'")


def _parse_required_credentials(
    raw: Any, errors: list[str]
) -> list[SkillRequiredCredential]:
    """Validate the manifest's ``required_credentials`` block.

    Each entry must declare ``id``/``label``/``env`` and the optional ``kind``
    falls in the v1 allowlist. Malformed entries append errors and are
    skipped so the rest of the manifest can still load; the overall
    ``validate_manifest`` decision (raise vs return) is unchanged.
    """
    out: list[SkillRequiredCredential] = []
    if raw is None or raw == []:
        return out
    if not isinstance(raw, list):
        errors.append(
            f"required_credentials must be a list, got {type(raw).__name__}"
        )
        return out
    seen_ids: set[str] = set()
    seen_envs: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(
                f"required_credentials[{i}] must be an object, got {type(entry).__name__}"
            )
            continue
        cid = str(entry.get("id", "")).strip()
        label = str(entry.get("label", "")).strip()
        env = str(entry.get("env", "")).strip()
        kind = str(entry.get("kind", "api_key")).strip() or "api_key"
        required = bool(entry.get("required", True))
        description = str(entry.get("description", "") or "")

        local: list[str] = []
        if not cid:
            local.append(f"required_credentials[{i}].id is required")
        elif cid in seen_ids:
            local.append(f"required_credentials[{i}].id={cid!r} is duplicate")
        if not label:
            local.append(f"required_credentials[{i}].label is required")
        if not env:
            local.append(f"required_credentials[{i}].env is required")
        elif env in seen_envs:
            local.append(
                f"required_credentials[{i}].env={env!r} is duplicate within manifest"
            )
        if kind not in SKILL_CREDENTIAL_KINDS:
            local.append(
                f"required_credentials[{i}].kind={kind!r} not in v1 allowlist "
                f"{sorted(SKILL_CREDENTIAL_KINDS)}"
            )
        raw_hints = entry.get("provider_hints", [])
        provider_hints: list[str] = []
        if raw_hints is None:
            pass
        elif not isinstance(raw_hints, list):
            local.append(
                f"required_credentials[{i}].provider_hints must be a list"
            )
        else:
            for hint in raw_hints:
                if isinstance(hint, str) and hint.strip():
                    provider_hints.append(hint.strip())

        if local:
            errors.extend(local)
            continue

        seen_ids.add(cid)
        seen_envs.add(env)
        out.append(
            SkillRequiredCredential(
                id=cid,
                label=label,
                env=env,
                kind=kind,
                provider_hints=provider_hints,
                required=required,
                description=description,
            )
        )
    return out


def _parse_config_fields(raw: Any, errors: list[str]) -> list[SkillConfigField]:
    """Validate the manifest's ``config_fields`` block."""
    out: list[SkillConfigField] = []
    if raw is None or raw == []:
        return out
    if not isinstance(raw, list):
        errors.append(f"config_fields must be a list, got {type(raw).__name__}")
        return out
    seen_ids: set[str] = set()
    seen_envs: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(
                f"config_fields[{i}] must be an object, got {type(entry).__name__}"
            )
            continue
        fid = str(entry.get("id", "")).strip()
        label = str(entry.get("label", "")).strip()
        env = str(entry.get("env", "")).strip()
        ftype = str(entry.get("type", "text")).strip() or "text"
        required = bool(entry.get("required", False))
        description = str(entry.get("description", "") or "")
        default = _normalize_config_default(ftype, entry.get("default"))
        options_raw = entry.get("options")
        minimum = _parse_optional_number(entry.get("min"))
        maximum = _parse_optional_number(entry.get("max"))
        step = _parse_optional_number(entry.get("step"))

        local: list[str] = []
        if not fid:
            local.append(f"config_fields[{i}].id is required")
        elif fid in seen_ids:
            local.append(f"config_fields[{i}].id={fid!r} is duplicate")
        if not label:
            local.append(f"config_fields[{i}].label is required")
        if not env:
            local.append(f"config_fields[{i}].env is required")
        elif env in seen_envs:
            local.append(
                f"config_fields[{i}].env={env!r} is duplicate within manifest"
            )
        if ftype not in SKILL_CONFIG_FIELD_TYPES:
            local.append(
                f"config_fields[{i}].type={ftype!r} not in v1 allowlist "
                f"{sorted(SKILL_CONFIG_FIELD_TYPES)}"
            )
        if is_plaintext_secret_config_field(
            field_id=fid,
            label=label,
            env=env,
            description=description,
            default=default,
        ):
            local.append(
                f"config_fields[{i}] appears to describe credential material; "
                "use required_credentials instead"
            )

        options: list[dict[str, str]] | None = None
        if options_raw is not None:
            if not isinstance(options_raw, list):
                local.append(f"config_fields[{i}].options must be a list")
            else:
                clean_options: list[dict[str, str]] = []
                for j, opt in enumerate(options_raw):
                    if not isinstance(opt, dict):
                        local.append(
                            f"config_fields[{i}].options[{j}] must be an object"
                        )
                        continue
                    v = str(opt.get("value", "")).strip()
                    lbl = str(opt.get("label", "")).strip()
                    if not v or not lbl:
                        local.append(
                            f"config_fields[{i}].options[{j}] requires value and label"
                        )
                        continue
                    clean_options.append({"value": v, "label": lbl})
                options = clean_options or None

        if ftype == "select" and not options:
            local.append(
                f"config_fields[{i}].type=select requires non-empty options"
            )

        if local:
            errors.extend(local)
            continue

        seen_ids.add(fid)
        seen_envs.add(env)
        out.append(
            SkillConfigField(
                id=fid,
                label=label,
                env=env,
                type=ftype,
                default=default,
                required=required,
                description=description,
                options=options,
                min=minimum,
                max=maximum,
                step=step,
            )
        )
    return out


def _parse_optional_number(raw: Any) -> float | None:
    """Return a finite numeric UI constraint or None when omitted/malformed."""
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
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            return None
    return None


def _normalize_config_default(field_type: str, raw: Any) -> str | None:
    """Return the string value persisted by runtime settings for one field."""
    if raw is None:
        return None
    if field_type == "boolean":
        if isinstance(raw, bool):
            return "true" if raw else "false"
        normalized = str(raw).strip().lower()
        return "true" if normalized in {"1", "true", "yes", "on"} else "false"
    return str(raw)


def parse_skill_md_frontmatter(content: str) -> dict[str, Any]:
    """Extract YAML frontmatter from a SKILL.md file content string.

    Returns a dict of parsed frontmatter fields. Uses a lightweight
    fallback when PyYAML is unavailable.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}

    frontmatter_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        frontmatter_lines.append(line)
    else:
        return {}  # No closing ---

    frontmatter_text = "\n".join(frontmatter_lines)
    try:
        import yaml

        parsed = yaml.safe_load(frontmatter_text)
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return dict(parsed)
    except Exception:
        pass

    result: dict[str, Any] = {}
    current_key: str | None = None

    for line in frontmatter_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Detect indentation: if line starts with spaces/tabs, it's a child
        is_indented = line != line.lstrip()

        if is_indented and current_key is not None and isinstance(result.get(current_key), dict):
            # Indented key:value under a parent dict
            if ":" in stripped and not stripped.startswith("-"):
                sub_key, _, sub_val = stripped.partition(":")
                sub_val = sub_val.strip()
                if sub_val.lower() in ("true", "false"):
                    result[current_key][sub_key.strip()] = sub_val.lower() == "true"
                elif sub_val.isdigit():
                    result[current_key][sub_key.strip()] = int(sub_val)
                else:
                    result[current_key][sub_key.strip()] = sub_val.strip("'\"")
            elif stripped.startswith("-"):
                item = stripped.lstrip("- ").strip()
                # Convert dict parent to list or add to existing list
                if "allowed_roots" not in result.get(current_key, {}):
                    # This is a list item for the parent key
                    existing = result.get(current_key)
                    if isinstance(existing, dict) and not existing:
                        result[current_key] = [item]
                    elif isinstance(existing, list):
                        existing.append(item)
            continue

        if ":" in stripped and not stripped.startswith("-"):
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value == "":
                result[key] = {}
                current_key = key
            elif value.startswith("[") and value.endswith("]"):
                # Inline list
                inner = value[1:-1]
                result[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
                current_key = None
            elif value.lower() in ("true", "false"):
                result[key] = value.lower() == "true"
                current_key = None
            elif value.isdigit():
                result[key] = int(value)
                current_key = None
            else:
                result[key] = value.strip("'\"")
                current_key = None
        elif stripped.startswith("-") and current_key is not None:
            # List item under current key
            item = stripped.lstrip("- ").strip()
            if isinstance(result.get(current_key), list):
                result[current_key].append(item)
            elif isinstance(result.get(current_key), dict):
                # Nested key-value under a parent
                if ":" in item:
                    sub_key, _, sub_val = item.partition(":")
                    sub_val = sub_val.strip()
                    if sub_val.lower() in ("true", "false"):
                        result[current_key][sub_key.strip()] = sub_val.lower() == "true"
                    else:
                        result[current_key][sub_key.strip()] = sub_val
                else:
                    result[current_key] = [item]
            else:
                result[current_key] = [item]

    return result

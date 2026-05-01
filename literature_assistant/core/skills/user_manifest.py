# -*- coding: utf-8 -*-
"""User Skill manifest parser and validator (TASK-184).

Parses SKILL.md frontmatter into a typed UserSkillManifest dataclass and
validates all fields according to the security rules defined in the
user-skill-extension-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any


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


# ---------------------------------------------------------------------------
# Manifest dataclass
# ---------------------------------------------------------------------------

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

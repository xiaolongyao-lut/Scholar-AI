"""Tests for SKILL.md manifest `required_credentials` + `config_fields`
(S5 / plan 2026-05-20 §C1 + reinforcement B)."""

from __future__ import annotations

import pytest

from skills.user_manifest import (
    SKILL_CONFIG_FIELD_TYPES,
    SKILL_CREDENTIAL_KINDS,
    ManifestValidationError,
    SkillConfigField,
    SkillRequiredCredential,
    UserSkillManifest,
    validate_manifest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_manifest(**overrides) -> dict:
    base = {
        "id": "test.skill",
        "name": "Test Skill",
        "version": "0.1.0",
        "kind": "transform",
        "description": "test",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Defaults: missing blocks parse as empty lists
# ---------------------------------------------------------------------------


def test_manifest_without_required_credentials_parses_empty():
    manifest = validate_manifest(_base_manifest())
    assert manifest.required_credentials == []
    assert manifest.config_fields == []


def test_empty_lists_are_accepted():
    manifest = validate_manifest(
        _base_manifest(required_credentials=[], config_fields=[])
    )
    assert manifest.required_credentials == []
    assert manifest.config_fields == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_required_credential_full_field_set():
    manifest = validate_manifest(_base_manifest(
        required_credentials=[
            {
                "id": "vision_key",
                "label": "Vision API Key",
                "env": "VISION_API_KEY",
                "kind": "api_key",
                "provider_hints": ["siliconflow", "openai"],
                "required": True,
                "description": "Used for image analysis",
            }
        ]
    ))
    assert len(manifest.required_credentials) == 1
    cred = manifest.required_credentials[0]
    assert isinstance(cred, SkillRequiredCredential)
    assert cred.id == "vision_key"
    assert cred.env == "VISION_API_KEY"
    assert cred.provider_hints == ["siliconflow", "openai"]


def test_required_credential_minimal_field_set():
    manifest = validate_manifest(_base_manifest(
        required_credentials=[
            {"id": "k", "label": "K", "env": "K_API_KEY"}
        ]
    ))
    cred = manifest.required_credentials[0]
    assert cred.kind == "api_key"  # default
    assert cred.required is True   # default
    assert cred.provider_hints == []


def test_config_field_text_type():
    manifest = validate_manifest(_base_manifest(
        config_fields=[
            {
                "id": "endpoint",
                "label": "API endpoint",
                "env": "API_ENDPOINT",
                "type": "text",
                "default": "https://api.example.com",
            }
        ]
    ))
    assert len(manifest.config_fields) == 1
    cf = manifest.config_fields[0]
    assert isinstance(cf, SkillConfigField)
    assert cf.type == "text"
    assert cf.default == "https://api.example.com"
    assert cf.required is False


def test_config_field_select_with_options():
    manifest = validate_manifest(_base_manifest(
        config_fields=[
            {
                "id": "model",
                "label": "Model",
                "env": "MODEL_NAME",
                "type": "select",
                "default": "gpt-4o",
                "options": [
                    {"value": "gpt-4o", "label": "GPT-4o"},
                    {"value": "claude", "label": "Claude"},
                ],
            }
        ]
    ))
    cf = manifest.config_fields[0]
    assert cf.type == "select"
    assert cf.options == [
        {"value": "gpt-4o", "label": "GPT-4o"},
        {"value": "claude", "label": "Claude"},
    ]


# ---------------------------------------------------------------------------
# Validation: type / shape errors
# ---------------------------------------------------------------------------


def test_required_credentials_not_a_list_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(required_credentials="oops"))
    assert any("required_credentials must be a list" in e for e in exc_info.value.errors)


def test_required_credentials_entry_not_a_dict_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(required_credentials=["not a dict"]))
    assert any("must be an object" in e for e in exc_info.value.errors)


def test_required_credentials_missing_id_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[{"label": "X", "env": "X_KEY"}]
        ))
    assert any("id is required" in e for e in exc_info.value.errors)


def test_required_credentials_missing_label_and_env_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[{"id": "x"}]
        ))
    msgs = exc_info.value.errors
    assert any("label is required" in e for e in msgs)
    assert any("env is required" in e for e in msgs)


def test_required_credentials_duplicate_id_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[
                {"id": "k", "label": "K1", "env": "K_KEY"},
                {"id": "k", "label": "K2", "env": "K_KEY2"},
            ]
        ))
    assert any("duplicate" in e for e in exc_info.value.errors)


def test_required_credentials_duplicate_env_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[
                {"id": "a", "label": "A", "env": "API_KEY"},
                {"id": "b", "label": "B", "env": "API_KEY"},
            ]
        ))
    assert any("env=" in e and "duplicate" in e for e in exc_info.value.errors)


def test_required_credentials_unknown_kind_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[
                {"id": "k", "label": "K", "env": "T_TOKEN", "kind": "oauth_token"}
            ]
        ))
    msgs = exc_info.value.errors
    assert any("not in v1 allowlist" in e for e in msgs)
    assert any("api_key" in e for e in msgs)


def test_required_credentials_provider_hints_must_be_list():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[
                {"id": "k", "label": "K", "env": "K", "provider_hints": "openai"}
            ]
        ))
    assert any("provider_hints must be a list" in e for e in exc_info.value.errors)


def test_config_fields_unknown_type_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            config_fields=[{"id": "x", "label": "X", "env": "X", "type": "color_picker"}]
        ))
    assert any("not in v1 allowlist" in e for e in exc_info.value.errors)


def test_config_fields_select_without_options_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            config_fields=[{"id": "x", "label": "X", "env": "X", "type": "select"}]
        ))
    assert any("select requires non-empty options" in e for e in exc_info.value.errors)


def test_config_fields_select_options_missing_value_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            config_fields=[{
                "id": "x", "label": "X", "env": "X", "type": "select",
                "options": [{"label": "only label"}],
            }]
        ))
    assert any("value and label" in e for e in exc_info.value.errors)


def test_config_fields_duplicate_id_raises():
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            config_fields=[
                {"id": "x", "label": "A", "env": "A_ENV", "type": "text"},
                {"id": "x", "label": "B", "env": "B_ENV", "type": "text"},
            ]
        ))
    assert any("duplicate" in e for e in exc_info.value.errors)


# ---------------------------------------------------------------------------
# Error collection (project pattern)
# ---------------------------------------------------------------------------


def test_validate_manifest_collects_multiple_errors_before_raising():
    """validate_manifest's error-collection pattern should report ALL bad
    entries in one ManifestValidationError, not bail on the first."""
    with pytest.raises(ManifestValidationError) as exc_info:
        validate_manifest(_base_manifest(
            required_credentials=[
                {},  # missing id+label+env
                {"id": "x", "label": "X", "env": "X", "kind": "weird"},  # bad kind
            ],
            config_fields=[
                {"id": "f", "label": "F", "env": "F", "type": "unknown_type"},  # bad type
            ],
        ))
    errors = exc_info.value.errors
    # At least the 3 categories above should each show up.
    assert sum("id is required" in e for e in errors) >= 1
    assert any("kind=" in e and "weird" in e for e in errors)
    assert any("type=" in e and "unknown_type" in e for e in errors)


# ---------------------------------------------------------------------------
# Allowlist constants exported
# ---------------------------------------------------------------------------


def test_v1_credential_kind_allowlist_is_api_key_only():
    assert SKILL_CREDENTIAL_KINDS == frozenset({"api_key"})


def test_v1_config_field_type_allowlist_is_text_and_select():
    assert SKILL_CONFIG_FIELD_TYPES == frozenset({"text", "select"})


# ---------------------------------------------------------------------------
# Compatibility: existing manifests without new fields still load
# ---------------------------------------------------------------------------


def test_existing_manifest_without_new_blocks_loads_unchanged():
    """A pre-S5 manifest must continue to load identically."""
    manifest = validate_manifest({
        "id": "legacy.skill",
        "name": "Legacy",
        "version": "1.0.0",
        "kind": "transform",
        "description": "loaded before S5",
        "permissions": {"draft.read": True, "draft.write": True},
    })
    assert isinstance(manifest, UserSkillManifest)
    assert manifest.required_credentials == []
    assert manifest.config_fields == []
    assert manifest.permissions == {"draft.read": True, "draft.write": True}

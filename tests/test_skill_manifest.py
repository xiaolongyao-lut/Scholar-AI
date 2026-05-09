# -*- coding: utf-8 -*-
"""Tests for user skill manifest validation (TASK-184)."""

import pytest
from skills.user_manifest import (
    validate_manifest,
    ManifestValidationError,
    parse_skill_md_frontmatter,
    UserSkillManifest,
)


VALID_BASE = {
    "id": "user.academic.polish",
    "name": "Academic Polish",
    "version": "1.0.0",
    "kind": "transform",
    "description": "Rewrite selected text into academic Chinese.",
    "entry_mode": "manual",
    "ui_visibility": "skill_assisted",
    "supported_scopes": ["selection", "section"],
    "permissions": {"draft.read": True, "draft.write": False},
    "script_policy": {"has_scripts": False, "safe_to_execute": False},
    "model_policy": {"allow_llm": True, "allow_embedding": False},
    "privacy_notes": "Does not access external files or network.",
    "rollback_hint": "Disable this skill from Skill Manager.",
}


class TestValidManifest:
    def test_valid_manifest_returns_dataclass(self):
        manifest = validate_manifest(VALID_BASE)
        assert isinstance(manifest, UserSkillManifest)
        assert manifest.id == "user.academic.polish"
        assert manifest.version == "1.0.0"
        assert manifest.kind == "transform"

    def test_permissions_default_deny(self):
        manifest = validate_manifest(VALID_BASE)
        assert manifest.effective_permission("draft.read") is True
        assert manifest.effective_permission("network") is False
        assert manifest.effective_permission("script.execute") is False

    def test_no_high_risk_by_default(self):
        manifest = validate_manifest(VALID_BASE)
        assert manifest.has_high_risk() is False

    def test_high_risk_detected(self):
        data = {**VALID_BASE, "permissions": {"network": True}}
        manifest = validate_manifest(data)
        assert manifest.has_high_risk() is True
        assert "network" in manifest.high_risk_flags


class TestInvalidId:
    def test_missing_id(self):
        data = {**VALID_BASE}
        del data["id"]
        with pytest.raises(ManifestValidationError) as exc_info:
            validate_manifest(data)
        assert "id" in exc_info.value.errors[0].lower()

    def test_invalid_id_uppercase(self):
        data = {**VALID_BASE, "id": "User.INVALID"}
        with pytest.raises(ManifestValidationError):
            validate_manifest(data)

    def test_invalid_id_spaces(self):
        data = {**VALID_BASE, "id": "my skill"}
        with pytest.raises(ManifestValidationError):
            validate_manifest(data)


class TestInvalidVersion:
    def test_missing_version(self):
        data = {**VALID_BASE}
        del data["version"]
        with pytest.raises(ManifestValidationError):
            validate_manifest(data)

    def test_non_semver(self):
        data = {**VALID_BASE, "version": "v1"}
        with pytest.raises(ManifestValidationError):
            validate_manifest(data)


class TestPathTraversal:
    def test_absolute_path_rejected(self):
        data = {**VALID_BASE, "input_schema": "/etc/passwd"}
        with pytest.raises(ManifestValidationError) as exc_info:
            validate_manifest(data)
        assert "relative" in exc_info.value.errors[0].lower()

    def test_traversal_rejected(self):
        data = {**VALID_BASE, "input_schema": "../../secrets/key.json"}
        with pytest.raises(ManifestValidationError) as exc_info:
            validate_manifest(data)
        assert "traversal" in exc_info.value.errors[0].lower()

    def test_valid_relative_path(self):
        data = {**VALID_BASE, "input_schema": "schemas/input.schema.json"}
        manifest = validate_manifest(data)
        assert manifest.input_schema == "schemas/input.schema.json"


class TestScriptPolicy:
    def test_safe_scripts_blocked_in_user_manifest(self):
        data = {**VALID_BASE, "script_policy": {"has_scripts": True, "safe_to_execute": True}}
        with pytest.raises(ManifestValidationError) as exc_info:
            validate_manifest(data)
        assert "safe_to_execute" in exc_info.value.errors[0]


class TestPermissions:
    def test_unknown_permission_rejected(self):
        data = {**VALID_BASE, "permissions": {"admin.root": True}}
        with pytest.raises(ManifestValidationError):
            validate_manifest(data)

    def test_all_standard_permissions_accepted(self):
        perms = {k: False for k in [
            "model.llm", "model.embedding", "retrieval.read",
            "draft.read", "draft.write", "references.read",
            "files.read", "files.write", "network",
            "script.execute", "storage",
        ]}
        data = {**VALID_BASE, "permissions": perms}
        manifest = validate_manifest(data)
        assert len(manifest.permissions) == len(perms)


class TestFrontmatterParsing:
    def test_parse_minimal(self):
        content = """---
id: test.skill
name: Test Skill
version: 1.0.0
kind: transform
description: A test skill
---

# Test Skill
"""
        result = parse_skill_md_frontmatter(content)
        assert result["id"] == "test.skill"
        assert result["name"] == "Test Skill"
        assert result["version"] == "1.0.0"

    def test_parse_with_lists(self):
        content = """---
id: test.skill
name: Test
version: 1.0.0
kind: transform
description: test
supported_scopes: [selection, section]
---
"""
        result = parse_skill_md_frontmatter(content)
        assert result["supported_scopes"] == ["selection", "section"]

    def test_parse_booleans(self):
        content = """---
id: test.skill
name: Test
version: 1.0.0
kind: transform
description: test
experimental: true
---
"""
        result = parse_skill_md_frontmatter(content)
        assert result["experimental"] is True

    def test_parse_nested_yaml_objects(self):
        content = """---
id: user.nested.test
name: Nested Test
version: 1.0.0
kind: workflow
description: Nested object parsing.
permissions:
  draft.read: true
  network: false
root_policy:
  allowed_roots:
    - skill_root
script_policy:
  has_scripts: false
  safe_to_execute: false
---
"""
        result = parse_skill_md_frontmatter(content)
        assert result["permissions"]["draft.read"] is True
        assert result["permissions"]["network"] is False
        assert result["root_policy"]["allowed_roots"] == ["skill_root"]
        assert result["script_policy"]["safe_to_execute"] is False

    def test_no_frontmatter_returns_empty(self):
        content = "# Just a heading\nNo frontmatter here."
        result = parse_skill_md_frontmatter(content)
        assert result == {}

    def test_roundtrip_parse_and_validate(self):
        content = """---
id: user.roundtrip.test
name: Roundtrip Test
version: 2.1.0
kind: validator
description: End-to-end parse+validate
entry_mode: manual
ui_visibility: both
supported_scopes: [selection, paragraph]
---

# Roundtrip Test
"""
        data = parse_skill_md_frontmatter(content)
        manifest = validate_manifest(data)
        assert manifest.id == "user.roundtrip.test"
        assert manifest.kind == "validator"
        assert manifest.version == "2.1.0"
        assert "paragraph" in manifest.supported_scopes

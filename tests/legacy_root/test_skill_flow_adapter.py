# -*- coding: utf-8 -*-
"""Unit tests for the skill-flow export adapter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from skills.skill_flow_adapter import SkillFlowAdapter

from skills.models import (
    SkillCompatibility,
    SkillDescriptor,
    SkillKind,
    SkillSource,
    SkillTrustLevel,
    UIVisibility,
)


def build_descriptor(skill_id: str, name: str, description: str) -> SkillDescriptor:
    """Create a deterministic descriptor fixture for adapter tests."""
    return SkillDescriptor(
        id=skill_id,
        name=name,
        description=description,
        kind=SkillKind.TRANSFORM,
        source=SkillSource.BUILTIN,
        entry_mode="assistant",
        supported_scopes=["selection", "section"],
        ui_visibility=UIVisibility.BOTH,
        requires_assets=False,
        tags=["adapter", "test"],
        version="1.3.3",
        display_group="testing",
        summary_hint="Used by adapter tests.",
        trust_level=SkillTrustLevel.TRUSTED,
        compatibility=SkillCompatibility(fallback_action_id="test.action"),
    )


class SkillFlowAdapterTests(unittest.TestCase):
    """Validate descriptor export and manual document mirroring."""

    def test_sync_exports_descriptor_into_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = Path(temp_dir, "skills")
            skills_root.mkdir(parents=True, exist_ok=True)
            template_path = skills_root / "SKILL.md.template"
            template_path.write_text(
                "\n".join(
                    [
                        "---",
                        "name: {{frontmatter_name}}",
                        "description: {{frontmatter_description}}",
                        "kind: {{frontmatter_kind}}",
                        "---",
                        "",
                        "# {{title}}",
                        "",
                        "{{summary_block}}{{description}}",
                        "",
                        "## Metadata",
                        "{{metadata_block}}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            adapter = SkillFlowAdapter(
                source_root=skills_root,
                output_root=skills_root / "catalog",
                template_path=template_path,
            )

            report = adapter.sync(
                [build_descriptor("academic:test-analyzer", "Test Analyzer", "Descriptor export body.")],
                mirror_existing=False,
                summary_path=skills_root / "catalog" / ".skill-flow-export.json",
            )

            self.assertEqual(1, len(report.exported))
            self.assertEqual("descriptor", report.exported[0].origin)
            self.assertEqual("test-analyzer", report.exported[0].slug)
            exported_path = skills_root / "catalog" / "test-analyzer" / "SKILL.md"
            self.assertTrue(exported_path.exists())
            exported_text = exported_path.read_text(encoding="utf-8")
            self.assertIn('name: "test-analyzer"', exported_text)
            self.assertIn('description: "Descriptor export body."', exported_text)
            self.assertIn("# Test Analyzer", exported_text)
            self.assertIn("Used by adapter tests.", exported_text)

    def test_sync_mirrors_existing_skill_documents_when_no_descriptors_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = Path(temp_dir, "skills")
            skills_root.mkdir(parents=True, exist_ok=True)
            template_path = skills_root / "SKILL.md.template"
            template_path.write_text(
                "# {{title}}\n{{description}}\n",
                encoding="utf-8",
            )

            legacy_skill_dir = skills_root / "legacy-review"
            legacy_skill_dir.mkdir(parents=True, exist_ok=True)
            legacy_skill_path = legacy_skill_dir / "SKILL.md"
            legacy_skill_path.write_text(
                "\n".join(
                    [
                        "---",
                        'name: "legacy-review"',
                        'description: "Existing manual skill."',
                        "---",
                        "",
                        "# Legacy Review",
                        "",
                        "Existing manual skill.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            adapter = SkillFlowAdapter(
                source_root=skills_root,
                output_root=skills_root / "catalog",
                template_path=template_path,
            )

            report = adapter.sync([], mirror_existing=True)

            self.assertEqual(1, len(report.exported))
            self.assertEqual("existing", report.exported[0].origin)
            mirrored_path = skills_root / "catalog" / "legacy-review" / "SKILL.md"
            self.assertTrue(mirrored_path.exists())
            self.assertEqual(
                legacy_skill_path.read_text(encoding="utf-8"),
                mirrored_path.read_text(encoding="utf-8"),
            )

    def test_sync_rejects_duplicate_normalized_slugs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = Path(temp_dir, "skills")
            skills_root.mkdir(parents=True, exist_ok=True)
            template_path = skills_root / "SKILL.md.template"
            template_path.write_text("# {{title}}\n", encoding="utf-8")
            adapter = SkillFlowAdapter(
                source_root=skills_root,
                output_root=skills_root / "catalog",
                template_path=template_path,
            )

            with self.assertRaisesRegex(ValueError, "Duplicate skill slug"):
                adapter.sync(
                    [
                        build_descriptor("alpha:foo_bar", "Foo Bar", "First descriptor."),
                        build_descriptor("beta:foo-bar", "Foo Bar 2", "Second descriptor."),
                    ],
                    mirror_existing=False,
                )

    def test_sync_strict_rejects_existing_skill_without_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir, ".github", "skills")
            source_root.mkdir(parents=True, exist_ok=True)
            template_path = Path(temp_dir, "SKILL.md.template")
            template_path.write_text("# {{title}}\n", encoding="utf-8")

            broken_skill_dir = source_root / "broken-skill"
            broken_skill_dir.mkdir(parents=True, exist_ok=True)
            (broken_skill_dir / "SKILL.md").write_text(
                "# Broken Skill\n\nNo frontmatter here.\n",
                encoding="utf-8",
            )

            adapter = SkillFlowAdapter(
                source_root=source_root,
                output_root=Path(temp_dir, "skills", "catalog"),
                template_path=template_path,
            )

            with self.assertRaisesRegex(ValueError, "frontmatter"):
                adapter.sync([], mirror_existing=True, strict=True)

    def test_sync_summary_records_mirrored_skill_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir, ".github", "skills")
            source_root.mkdir(parents=True, exist_ok=True)
            template_path = Path(temp_dir, "SKILL.md.template")
            template_path.write_text("# {{title}}\n", encoding="utf-8")

            env_skill_dir = source_root / "env-test-discipline"
            env_skill_dir.mkdir(parents=True, exist_ok=True)
            (env_skill_dir / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        'name: "env-test-discipline"',
                        'description: "Canonical env + test safety rules."',
                        "---",
                        "",
                        "# Env Test Discipline",
                        "",
                        "Canonical env + test safety rules.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            output_root = Path(temp_dir, "skills", "catalog")
            summary_path = output_root / ".skill-flow-export.json"
            adapter = SkillFlowAdapter(
                source_root=source_root,
                output_root=output_root,
                template_path=template_path,
            )

            report = adapter.sync([], mirror_existing=True, strict=True, summary_path=summary_path)

            self.assertEqual(1, len(report.exported))
            self.assertTrue(summary_path.exists())
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(1, payload["exported_count"])
            exported = payload["exported"][0]
            self.assertEqual("env-test-discipline", exported["slug"])
            self.assertEqual("existing", exported["origin"])
            self.assertEqual("env-test-discipline", exported["name"])
            self.assertIn("generated_at", payload)
            self.assertTrue(
                exported["source_locator"].replace("\\", "/").endswith(
                    "/.github/skills/env-test-discipline/SKILL.md"
                )
            )
            self.assertTrue(
                exported["output_path"].replace("\\", "/").endswith(
                    "/skills/catalog/env-test-discipline/SKILL.md"
                )
            )


if __name__ == "__main__":
    unittest.main()

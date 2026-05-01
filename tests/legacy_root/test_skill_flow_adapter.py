# -*- coding: utf-8 -*-
"""Unit tests for the skill-flow export adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

# Conditional import: SkillFlowAdapter is not part of Phase G recovery scope
# If skills.skill_flow_adapter is implemented in the future, remove the skip decorator
try:
    from skills.skill_flow_adapter import SkillFlowAdapter
    SKILL_FLOW_ADAPTER_AVAILABLE = True
except ImportError:
    SKILL_FLOW_ADAPTER_AVAILABLE = False
    SkillFlowAdapter = None  # type: ignore

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


@unittest.skipIf(
    not SKILL_FLOW_ADAPTER_AVAILABLE,
    "SkillFlowAdapter module not available - skill catalog export not in Phase G recovery scope"
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


if __name__ == "__main__":
    unittest.main()

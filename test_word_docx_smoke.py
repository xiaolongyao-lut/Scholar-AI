# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
WORD_SCRIPT = REPO_ROOT / "word_generator.py"


class WordDocxSmokeTests(unittest.TestCase):
    """End-to-end smoke tests for semantic-themes to Word document generation."""

    def test_cli_generates_docx_with_theme_sections(self) -> None:
        material_pack = {
            "goal": "验证主题化 Word 主文生成",
            "source_pdf": "demo_source.pdf",
            "schema_version": "v2-standard",
            "semantic_themes": [
                {
                    "theme_id": "theme_001",
                    "theme_title": "激光功率与氮传输",
                    "summary": "主题摘要：激光功率变化会影响熔池对流与氮的迁移路径。",
                    "linked_writing_point_ids": ["wp_001"],
                    "linked_figure_ids": [],
                    "linked_table_ids": [],
                    "linked_reference_ids": ["ref_001"],
                    "linked_parameter_ids": ["param_001"],
                    "linked_result_ids": ["result_001"],
                    "order_score": 1.5,
                }
            ],
            "writing_point_cards": [
                {
                    "writing_point_id": "wp_001",
                    "claim": "较高激光功率会改变熔池流动模式，并影响氮元素向熔池内部传输。",
                    "representative_claim": "较高激光功率会改变熔池流动模式，并影响氮元素向熔池内部传输。",
                    "point_type": "结论",
                    "boundary_type": "相关",
                    "boundary_note": "来自实验结果与讨论段落。",
                    "evidence_summary": "0 图 / 0 表 / 1 参数 / 1 结果 / 1 引用",
                    "pages": [3, 4],
                    "page": 3,
                    "original_reference_markers": ["[1]"],
                    "source_text_preview": "实验结果表明，在功率提高时熔池对流增强，氮迁移轨迹发生变化。",
                }
            ],
            "single_figure_cards": [],
            "single_table_cards": [],
            "selected_parameter_cards": [],
            "selected_result_cards": [],
            "reference_directory_with_original_markers": [
                {
                    "ref_id": "ref_001",
                    "raw_marker": "[1]",
                    "entry_text": "Author. Laser power and nitrogen transfer.",
                }
            ],
        }

        with tempfile.TemporaryDirectory(prefix="word-docx-smoke-") as temp_dir:
            temp_path = Path(temp_dir)
            pack_path = temp_path / "material_pack.json"
            output_path = temp_path / "report.docx"
            pack_path.write_text(json.dumps(material_pack, ensure_ascii=False, indent=2), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(WORD_SCRIPT), str(pack_path), str(output_path)],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            result = json.loads(completed.stdout.strip())
            self.assertEqual(result["status"], "ok")
            self.assertTrue(output_path.exists())

            with zipfile.ZipFile(output_path) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")

            self.assertIn("激光功率与氮传输", document_xml)
            self.assertIn("Appendix: Original Evidence Trace", document_xml)
            self.assertIn("较高激光功率会改变熔池流动模式", document_xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)

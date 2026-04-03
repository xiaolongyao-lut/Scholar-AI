# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

material_pack_module = importlib.import_module("03_目标导向材料包脚本")


class SemanticThemesRegressionTests(unittest.TestCase):
    """Regression tests for semantic theme generation and pack hardening."""

    def test_build_material_pack_tolerates_nullable_reference_and_page_images(self) -> None:
        analysis = {
            "goal": "验证空值容忍",
            "selected_writing_points": [
                {
                    "writing_point_id": "wp_01",
                    "claim": "激光功率影响熔池行为。",
                    "section_title": "Results",
                    "goal_hits": ["goal_power"],
                    "causal_roles": ["condition"],
                    "linked_figures": [],
                    "linked_tables": [],
                    "linked_references": [],
                    "linked_parameters": [],
                    "linked_results": [],
                }
            ],
        }
        bound = {
            "references": None,
            "page_images": None,
            "source_pdf": "demo.pdf",
        }

        pack = material_pack_module.build_material_pack(analysis, bound)

        self.assertEqual(pack["status"], "ok")
        self.assertIn("semantic_themes", pack)
        self.assertEqual(pack["source_pdf"], "demo.pdf")

    def test_semantic_themes_do_not_force_minimum_count(self) -> None:
        writing_point_cards = [
            {
                "writing_point_id": "wp_01",
                "claim": "主题一结论 A",
                "section_title": "Results",
                "goal_hits": ["goal_1"],
                "causal_roles": ["cause"],
                "linked_figure_ids": ["fig_1"],
                "linked_table_ids": [],
                "linked_reference_ids": ["ref_1"],
                "linked_parameter_ids": [],
                "linked_result_ids": [],
                "relevance_score": 0.90,
                "evidence_strength": 0.80,
            },
            {
                "writing_point_id": "wp_02",
                "claim": "主题一结论 B",
                "section_title": "Results",
                "goal_hits": ["goal_1"],
                "causal_roles": ["cause"],
                "linked_figure_ids": ["fig_2"],
                "linked_table_ids": [],
                "linked_reference_ids": ["ref_2"],
                "linked_parameter_ids": [],
                "linked_result_ids": [],
                "relevance_score": 0.88,
                "evidence_strength": 0.70,
            },
            {
                "writing_point_id": "wp_03",
                "claim": "主题二结论 A",
                "section_title": "Discussion",
                "goal_hits": ["goal_2"],
                "causal_roles": ["effect"],
                "linked_figure_ids": [],
                "linked_table_ids": ["tab_1"],
                "linked_reference_ids": ["ref_3"],
                "linked_parameter_ids": ["param_1"],
                "linked_result_ids": ["result_1"],
                "relevance_score": 0.76,
                "evidence_strength": 0.82,
            },
        ]

        themes = material_pack_module.build_semantic_themes(writing_point_cards)

        self.assertEqual(len(themes), 2)
        self.assertEqual(
            [theme["theme_title"] for theme in themes],
            ["Results", "Discussion"],
        )

    def test_semantic_theme_linked_ids_are_stable_across_processes(self) -> None:
        script = """
import importlib
import json
module = importlib.import_module("03_目标导向材料包脚本")
writing_point_cards = [
    {
        "writing_point_id": "wp_01",
        "claim": "主题一",
        "section_title": "Results",
        "goal_hits": ["goal_1"],
        "causal_roles": ["cause"],
        "linked_figure_ids": ["fig_2", "fig_1", "fig_2"],
        "linked_table_ids": ["tab_2", "tab_1"],
        "linked_reference_ids": ["ref_2", "ref_1", "ref_2"],
        "linked_parameter_ids": ["param_2", "param_1"],
        "linked_result_ids": ["result_2", "result_1"],
        "relevance_score": 0.8,
        "evidence_strength": 0.7
    },
    {
        "writing_point_id": "wp_02",
        "claim": "主题一补充",
        "section_title": "Results",
        "goal_hits": ["goal_1"],
        "causal_roles": ["cause"],
        "linked_figure_ids": ["fig_1", "fig_3"],
        "linked_table_ids": ["tab_1", "tab_3"],
        "linked_reference_ids": ["ref_1", "ref_3"],
        "linked_parameter_ids": ["param_1", "param_3"],
        "linked_result_ids": ["result_1", "result_3"],
        "relevance_score": 0.6,
        "evidence_strength": 0.5
    }
]
theme = module.build_semantic_themes(writing_point_cards)[0]
print(json.dumps(theme, ensure_ascii=False, sort_keys=True))
"""
        outputs: list[str] = []
        for _ in range(4):
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", "-c", script],
                check=True,
                capture_output=True,
                cwd=REPO_ROOT,
                text=True,
                encoding="utf-8",
            )
            outputs.append(completed.stdout.strip())

        self.assertTrue(outputs)
        self.assertEqual(len(set(outputs)), 1)

        theme = json.loads(outputs[0])
        self.assertEqual(theme["linked_figure_ids"], ["fig_2", "fig_1", "fig_3"])
        self.assertEqual(theme["linked_table_ids"], ["tab_2", "tab_1", "tab_3"])
        self.assertEqual(theme["linked_reference_ids"], ["ref_2", "ref_1", "ref_3"])
        self.assertEqual(theme["linked_parameter_ids"], ["param_2", "param_1", "param_3"])
        self.assertEqual(theme["linked_result_ids"], ["result_2", "result_1", "result_3"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

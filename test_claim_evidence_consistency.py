# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

material_pack_module = importlib.import_module("03_目标导向材料包脚本")


class ClaimEvidenceConsistencyTests(unittest.TestCase):
    """Regression tests for claim-evidence consistency reporting."""

    def test_writing_point_without_evidence_fails_consistency_gate(self) -> None:
        analysis = {
            "goal": "检查无证据主张",
            "selected_writing_points": [
                {
                    "writing_point_id": "wp_001",
                    "claim": "这是一个没有证据的主张。",
                    "section_title": "Results",
                    "goal_hits": ["goal_1"],
                    "causal_roles": ["cause"],
                    "linked_figures": [],
                    "linked_tables": [],
                    "linked_references": [],
                    "linked_parameters": [],
                    "linked_results": [],
                    "source_chunk_ids": [],
                }
            ],
        }

        pack = material_pack_module.build_material_pack(analysis, {})

        self.assertIn("consistency_report", pack)
        self.assertFalse(pack["quality_gates"]["writing_points_have_supporting_evidence"])
        self.assertFalse(pack["quality_gates"]["consistency_pass"])
        self.assertEqual(pack["consistency_report"]["summary"]["error_count"], 1)
        self.assertEqual(pack["consistency_report"]["issues"][0]["scope"], "writing_point")

    def test_theme_with_missing_writing_point_reference_is_reported(self) -> None:
        writing_point_cards = [
            {
                "writing_point_id": "wp_001",
                "claim": "受控主题主张",
                "linked_figure_ids": ["fig_001"],
                "linked_table_ids": [],
                "linked_reference_ids": ["ref_001"],
                "linked_parameter_ids": [],
                "linked_result_ids": [],
                "source_chunk_ids": ["chunk_001"],
                "original_reference_markers": ["[1]"],
            }
        ]
        semantic_themes = [
            {
                "theme_id": "theme_001",
                "theme_title": "主题 A",
                "linked_writing_point_ids": ["wp_001", "wp_missing"],
                "linked_figure_ids": ["fig_001"],
                "linked_table_ids": [],
                "linked_reference_ids": ["ref_001"],
                "linked_parameter_ids": [],
                "linked_result_ids": [],
            }
        ]

        report = material_pack_module.build_consistency_report(writing_point_cards, semantic_themes)

        self.assertFalse(report["summary"]["overall_pass"])
        self.assertEqual(report["summary"]["error_count"], 1)
        self.assertEqual(report["theme_checks"][0]["missing_writing_point_ids"], ["wp_missing"])

    def test_consistent_pack_sets_pass_gates(self) -> None:
        analysis = {
            "goal": "检查一致性通过场景",
            "selected_writing_points": [
                {
                    "writing_point_id": "wp_001",
                    "claim": "激光功率增加会改变熔池流动。",
                    "section_title": "Results",
                    "goal_hits": ["goal_power"],
                    "causal_roles": ["cause"],
                    "linked_figures": ["fig_001"],
                    "linked_tables": [],
                    "linked_references": ["ref_001"],
                    "linked_parameters": ["param_001"],
                    "linked_results": ["result_001"],
                    "source_chunk_ids": ["chunk_001"],
                    "original_reference_markers": ["[1]"],
                    "boundary_note": "实验结果支撑",
                    "boundary_type": "因果",
                }
            ],
            "selected_figures": [{"figure_id": "fig_001", "supporting_writing_point_ids": ["wp_001"]}],
            "selected_references": [{"ref_id": "ref_001", "raw_marker": "[1]"}],
            "selected_parameters": [{"parameter_id": "param_001", "text": "功率 400W"}],
            "selected_results": [{"result_id": "result_001", "text": "熔池对流增强"}],
        }

        pack = material_pack_module.build_material_pack(analysis, {})

        self.assertTrue(pack["quality_gates"]["writing_points_have_supporting_evidence"])
        self.assertTrue(pack["quality_gates"]["themes_have_linked_writing_points"])
        self.assertTrue(pack["quality_gates"]["consistency_pass"])
        self.assertEqual(pack["consistency_report"]["summary"]["error_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""Regression tests for repository MemPalace bootstrap helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from bootstrap_mempalace_repo import (
    _build_identity_text,
    _create_rollback_snapshot,
    _write_identity,
    _write_project_config,
)


class MempalaceBootstrapTests(unittest.TestCase):
    """Cover the non-interactive bootstrap helper behavior."""

    def test_identity_text_mentions_harness_and_memory(self) -> None:
        project_dir = Path("C:/repo/example")
        rooms = [
            {"name": "backend", "description": "Backend files", "keywords": ["backend"]},
            {"name": "general", "description": "General", "keywords": []},
        ]

        identity = _build_identity_text(project_dir, "wing_modular_pipeline", rooms)

        self.assertIn("Modular Pipeline harness assistant", identity)
        self.assertIn("AI memory priority", identity)
        self.assertIn("backend, general", identity)

    def test_write_project_config_creates_expected_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "mempalace.yaml"
            rooms = [
                {"name": "backend", "description": "Backend files", "keywords": ["backend", "api"]},
                {"name": "general", "description": "General files", "keywords": []},
            ]

            written = _write_project_config(config_path, "wing_test", rooms, refresh=False)

            self.assertTrue(written)
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = yaml.safe_load(config_file)
            self.assertEqual(data["wing"], "wing_test")
            self.assertEqual(len(data["rooms"]), 2)
            self.assertEqual(data["rooms"][0]["name"], "backend")

    def test_write_identity_respects_refresh_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            identity_path = Path(tmp_dir) / "identity.txt"

            first_write = _write_identity(identity_path, "first", refresh=False)
            second_write = _write_identity(identity_path, "second", refresh=False)
            refreshed_write = _write_identity(identity_path, "third", refresh=True)

            self.assertTrue(first_write)
            self.assertFalse(second_write)
            self.assertTrue(refreshed_write)
            self.assertEqual(identity_path.read_text(encoding="utf-8").strip(), "third")

    def test_create_rollback_snapshot_copies_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_dir = Path(tmp_dir)
            file_a = source_dir / "a.txt"
            file_b = source_dir / "b.txt"
            file_a.write_text("alpha", encoding="utf-8")
            file_b.write_text("beta", encoding="utf-8")

            snapshot = _create_rollback_snapshot([file_a, file_b])

            self.assertIsNotNone(snapshot)
            snapshot_path = Path(snapshot)
            self.assertTrue((snapshot_path / "a.txt").exists())
            self.assertTrue((snapshot_path / "b.txt").exists())


if __name__ == "__main__":
    unittest.main()

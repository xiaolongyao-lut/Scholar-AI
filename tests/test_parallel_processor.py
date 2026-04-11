"""
Tests for Parallel Processor Module
Ensures ordering, error isolation, and mode switching work correctly.
"""

import unittest
import os
import json
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict

from modules.parallel_processor import ParallelPaperProcessor
from modules.paper_processor import PaperProcessReport
from modules.configuration_manager import get_configuration


class TestParallelProcessor(unittest.TestCase):
    """Test suite for ParallelPaperProcessor"""

    def setUp(self):
        """Setup temporary test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.config = get_configuration()
        self.processor = ParallelPaperProcessor(self.config)

        # Create some dummy extraction files
        self.tasks = []
        for i in range(5):
            paper_id = f"test_paper_{i}"
            paper_dir = Path(self.test_dir) / paper_id
            paper_dir.mkdir()
            
            file_path = paper_dir / "01_full_extract.json"
            data = {
                "source_pdf": f"dummy_{i}.pdf",
                "chunks": [
                    {"chunk_id": "c1", "text": "This is a dummy text for laser power and hardness properties."}
                ]
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            
            self.tasks.append({"file_path": str(file_path), "paper_id": paper_id})

    def tearDown(self):
        """Cleanup temporary directory"""
        shutil.rmtree(self.test_dir)

    def test_order_determinism(self):
        """Verify that results are returned in the same order as tasks"""
        # Run in thread mode for speed and stability in test environment
        result = self.processor.process_batch(self.tasks, mode="thread", num_workers=2)
        
        self.assertEqual(len(result.reports), 5)
        for i, report in enumerate(result.reports):
            self.assertEqual(report.paper_id, f"test_paper_{i}", f"Order mismatch at index {i}")

    def test_error_isolation(self):
        """Verify that a single file failure doesn't crash the whole batch"""
        # Corrupt one file
        bad_file = Path(self.tasks[2]["file_path"])
        with open(bad_file, 'w') as f:
            f.write("INVALID JSON")
            
        result = self.processor.process_batch(self.tasks, mode="thread", num_workers=2)
        
        self.assertEqual(len(result.reports), 4, "Should have 4 successful reports")
        self.assertEqual(len(result.failed_items), 1, "Should have 1 failed item")
        self.assertEqual(result.failed_items[0]["paper_id"], "test_paper_2")
        self.assertIn("error", result.failed_items[0])

    def test_mode_off(self):
        """Verify that 'off' mode works and is sequential"""
        result = self.processor.process_batch(self.tasks, mode="off")
        self.assertEqual(result.mode, "off")
        self.assertEqual(len(result.reports), 5)
        self.assertEqual(result.num_workers, 1)

    def test_auto_mode(self):
        """Verify auto mode selects a valid configuration"""
        result = self.processor.process_batch(self.tasks, mode="auto")
        self.assertIn(result.mode, ["process", "thread"])
        self.assertGreater(result.num_workers, 0)
        self.assertEqual(len(result.reports), 5)

if __name__ == "__main__":
    unittest.main()

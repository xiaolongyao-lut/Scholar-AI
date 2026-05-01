#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
system_verification.py
Literature Processor - System Verification Script
Checks if all essential files and modules are correctly deployed.
"""

import sys
import json
from pathlib import Path
from typing import Optional

class SystemVerifier:
    """System verifier for active runtime files and documentation."""

    def __init__(self, base_path: Optional[Path] = None):
        if base_path is None:
            base_path = Path(__file__).resolve().parents[2]
        self.base_path = base_path
        self.checks = []
        self.results = {
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "errors": []
        }

    def check_file_exists(self, rel_path: str, description: str = None) -> bool:
        """Check if file exists."""
        full_path = self.base_path / rel_path
        desc = description or rel_path

        if full_path.exists():
            self.results["passed"] += 1
            print(f"Success: {desc}")
            return True
        else:
            self.results["failed"] += 1
            print(f"FAILED: {desc} (NOT FOUND: {full_path})")
            self.results["errors"].append(f"Missing file: {rel_path}")
            return False

    def check_imports(self, module_name: str, description: str = None) -> bool:
        """Check if Python module is importable."""
        desc = description or f"Module: {module_name}"

        try:
            __import__(module_name)
            self.results["passed"] += 1
            print(f"Success: {desc}")
            return True
        except ImportError as e:
            self.results["failed"] += 1
            print(f"FAILED: {desc} ({e})")
            self.results["errors"].append(f"Import error: {module_name}")
            return False

    def check_syntax(self, rel_path: str, description: str = None) -> bool:
        """Check Python file syntax."""
        full_path = self.base_path / rel_path
        desc = description or rel_path

        if not full_path.exists():
            self.results["warnings"] += 1
            print(f"WARNING: {desc} (file not found, skipping syntax check)")
            return True

        try:
            compile(full_path.read_text(encoding='utf-8'), str(full_path), 'exec')
            self.results["passed"] += 1
            print(f"Success: {desc} (syntax OK)")
            return True
        except SyntaxError as e:
            self.results["failed"] += 1
            print(f"FAILED: {desc} (SYNTAX ERROR: {e})")
            self.results["errors"].append(f"Syntax error in {rel_path}: {e}")
            return False

    def verify_phase_1(self):
        """Verify Phase 1."""
        print("\n[PHASE 1] Intelligence Injection")
        print("-" * 60)

        print("Checking core files...")
        self.check_file_exists(
            "literature_assistant/core/layers/ai_adapter.py",
            "AIAdapter (LLM Adapter Layer)"
        )
        self.check_file_exists(
            "literature_assistant/core/layers/g_layer_academic_generator.py",
            "G-Layer (Academic Generator Layer)"
        )

        print("\nChecking Python syntax...")
        self.check_syntax("literature_assistant/core/layers/ai_adapter.py", "AIAdapter syntax")
        self.check_syntax("literature_assistant/core/layers/g_layer_academic_generator.py", "G-Layer syntax")

    def verify_phase_2(self):
        """Verify Phase 2."""
        print("\n[PHASE 2] Batch Automation")
        print("-" * 60)

        print("Checking core files...")
        self.check_file_exists("workspace_tests/evaluation_scripts/batch_controller.py", "Batch Process Controller")

        print("\nChecking Python syntax...")
        self.check_syntax("workspace_tests/evaluation_scripts/batch_controller.py", "Batch Controller syntax")

        print("\nChecking Key Classes...")
        try:
            evaluation_scripts = self.base_path / "workspace_tests" / "evaluation_scripts"
            if str(evaluation_scripts) not in sys.path:
                sys.path.insert(0, str(evaluation_scripts))
            from batch_controller import BatchProcessController
            
            if BatchProcessController:
                self.results["passed"] += 1
                print("Success: BatchProcessController class found")

                methods = [
                    'discover_pdfs',
                    'run_single_pipeline',
                    'create_volume_bundle',
                    'process_batch'
                ]
                for method in methods:
                    if hasattr(BatchProcessController, method):
                        self.results["passed"] += 1
                        print(f"Success: BatchProcessController.{method}()")
                    else:
                        self.results["failed"] += 1
                        print(f"FAILED: BatchProcessController.{method}() (NOT FOUND)")
            else:
                self.results["failed"] += 1
                print("FAILED: BatchProcessController class (NOT FOUND)")
        except Exception as e:
            self.results["warnings"] += 1
            print(f"WARNING: Unable to fully verify Batch Controller: {e}")

    def verify_phase_3(self):
        """Verify Phase 3."""
        print("\n[PHASE 3] Cross-Paper Indexing")
        print("-" * 60)

        print("Checking core files...")
        self.check_file_exists(
            "literature_assistant/core/layers/w_layer_cross_paper_analysis.py",
            "W-Layer (Cross-paper Analysis)"
        )
        self.check_file_exists(
            "literature_assistant/core/volume_indexer.py",
            "Volume Deep Analysis Script"
        )

        print("\nChecking Python syntax...")
        self.check_syntax("literature_assistant/core/layers/w_layer_cross_paper_analysis.py", "W-Layer syntax")
        self.check_syntax("literature_assistant/core/volume_indexer.py", "Volume Indexer syntax")

    def verify_documentation(self):
        """Verify documentation."""
        print("\n[DOCS]")
        print("-" * 60)

        docs = [
            ("README.md", "Project README"),
            ("DEVELOPER_GUIDE.md", "Developer Guide"),
            ("literature_assistant/00-index/path-hardening-record.md", "Path Hardening Record"),
        ]

        for doc_file, desc in docs:
            self.check_file_exists(doc_file, desc)

    def check_dependencies(self):
        """Check dependencies."""
        print("\n[DEPENDENCIES]")
        print("-" * 60)

        dependencies = [
            ("openai", "OpenAI Python SDK"),
            ("pathlib", "Path utilities"),
            ("json", "JSON processing"),
            ("subprocess", "Process execution"),
            ("logging", "Logging"),
        ]

        for module, desc in dependencies:
            try:
                __import__(module)
                self.results["passed"] += 1
                print(f"Success: {desc} ({module})")
            except ImportError:
                if module == "openai":
                    self.results["warnings"] += 1
                    print(f"WARNING: {desc} ({module}) - Optional for LLM features")
                else:
                    self.results["failed"] += 1
                    print(f"FAILED: {desc} ({module})")

    def run_all_checks(self):
        """Run all checks."""
        print("\n" + "="*60)
        print("Literature Processor - System Verification")
        print("="*60)

        self.verify_phase_1()
        self.verify_phase_2()
        self.verify_phase_3()
        self.verify_documentation()
        self.check_dependencies()

        # Summary
        print("\n" + "="*60)
        print("Verification Results Summary")
        print("="*60)
        print(f"Passed: {self.results['passed']}")
        print(f"Failed: {self.results['failed']}")
        print(f"Warnings: {self.results['warnings']}")

        if self.results['errors']:
            print("\nError Details:")
            for error in self.results['errors']:
                print(f"  - {error}")

        print("\n" + "="*60)
        if self.results['failed'] == 0:
            print("SUCCESS: All checks passed! System verification completed successfully.")
            return True
        else:
            print("FAILED: Some checks failed. Please review errors above.")
            return False


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(description='Literature Processor System Verification')
    parser.add_argument('--base-path', type=Path, default=None, help='Base path for scripts')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')

    args = parser.parse_args()

    verifier = SystemVerifier(base_path=args.base_path)
    success = verifier.run_all_checks()

    if args.json:
        print("\n" + json.dumps(verifier.results, ensure_ascii=False, indent=2))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

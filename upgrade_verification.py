#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
upgrade_verification.py
文献处理器 v40.0 升级验证脚本

检查所有必要的文件和模块是否正确部署。
"""

import sys
import json
from pathlib import Path
from typing import List, Tuple

class UpgradeVerifier:
    """升级验证器。"""

    def __init__(self, base_path: Path = None):
        if base_path is None:
            base_path = Path(__file__).parent
        self.base_path = base_path
        self.checks = []
        self.results = {
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "errors": []
        }

    def check_file_exists(self, rel_path: str, description: str = None) -> bool:
        """检查文件是否存在。"""
        full_path = self.base_path / rel_path
        desc = description or rel_path

        if full_path.exists():
            self.results["passed"] += 1
            print(f"✓ {desc}")
            return True
        else:
            self.results["failed"] += 1
            print(f"✗ {desc} (NOT FOUND: {full_path})")
            self.results["errors"].append(f"Missing file: {rel_path}")
            return False

    def check_imports(self, module_name: str, description: str = None) -> bool:
        """检查 Python 模块是否可导入。"""
        desc = description or f"Module: {module_name}"

        try:
            __import__(module_name)
            self.results["passed"] += 1
            print(f"✓ {desc}")
            return True
        except ImportError as e:
            self.results["failed"] += 1
            print(f"✗ {desc} ({e})")
            self.results["errors"].append(f"Import error: {module_name}")
            return False

    def check_syntax(self, rel_path: str, description: str = None) -> bool:
        """检查 Python 文件语法。"""
        full_path = self.base_path / rel_path
        desc = description or rel_path

        if not full_path.exists():
            self.results["warnings"] += 1
            print(f"⚠ {desc} (file not found, skipping syntax check)")
            return True

        try:
            compile(full_path.read_text(), str(full_path), 'exec')
            self.results["passed"] += 1
            print(f"✓ {desc} (syntax OK)")
            return True
        except SyntaxError as e:
            self.results["failed"] += 1
            print(f"✗ {desc} (SYNTAX ERROR: {e})")
            self.results["errors"].append(f"Syntax error in {rel_path}: {e}")
            return False

    def verify_phase_1(self):
        """验证第一阶段。"""
        print("\n【第一阶段】深度智能注入 (Intelligence Injection)")
        print("-" * 60)

        print("检查核心文件...")
        self.check_file_exists(
            "layers/ai_adapter.py",
            "AIAdapter (LLM 适配层)"
        )
        self.check_file_exists(
            "layers/g_layer_academic_generator.py",
            "G-Layer (学术生成层)"
        )

        print("\n检查 Python 语法...")
        self.check_syntax(
            "layers/ai_adapter.py",
            "AIAdapter syntax"
        )
        self.check_syntax(
            "layers/g_layer_academic_generator.py",
            "G-Layer syntax"
        )

        print("\n检查关键方法...")
        try:
            from layers.ai_adapter import AIAdapter
            methods = [
                'extract_claims',
                'verify_multimodal_support',
                'extract_mechanisms',
                'extract_innovation_points',
                'classify_claim_boundary',
                'verify_evidence_chain'
            ]
            for method in methods:
                if hasattr(AIAdapter, method):
                    self.results["passed"] += 1
                    print(f"✓ AIAdapter.{method}()")
                else:
                    self.results["failed"] += 1
                    print(f"✗ AIAdapter.{method}() (NOT FOUND)")
                    self.results["errors"].append(f"Missing method: AIAdapter.{method}")
        except Exception as e:
            self.results["failed"] += 1
            print(f"✗ 无法导入 AIAdapter: {e}")
            self.results["errors"].append(str(e))

    def verify_phase_2(self):
        """验证第二阶段。"""
        print("\n【第二阶段】规模化批处理 (Batch Automation)")
        print("-" * 60)

        print("检查核心文件...")
        self.check_file_exists(
            "00_Batch_Process_Controller.py",
            "Batch Process Controller"
        )

        print("\n检查 Python 语法...")
        self.check_syntax(
            "00_Batch_Process_Controller.py",
            "Batch Controller syntax"
        )

        print("\n检查关键类...")
        try:
            # 需要在正确的 Python 路径下
            sys.path.insert(0, str(self.base_path))
            from importlib.util import spec_from_file_location, module_from_spec

            spec = spec_from_file_location(
                "batch_controller",
                self.base_path / "00_Batch_Process_Controller.py"
            )
            module = module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, 'BatchProcessController'):
                self.results["passed"] += 1
                print("✓ BatchProcessController class")

                # 检查方法
                methods = [
                    'discover_pdfs',
                    'run_single_pipeline',
                    'collect_material_pack',
                    'create_volume_bundle',
                    'process_batch'
                ]
                for method in methods:
                    if hasattr(module.BatchProcessController, method):
                        self.results["passed"] += 1
                        print(f"✓ BatchProcessController.{method}()")
                    else:
                        self.results["failed"] += 1
                        print(f"✗ BatchProcessController.{method}()")
            else:
                self.results["failed"] += 1
                print("✗ BatchProcessController class (NOT FOUND)")
        except Exception as e:
            self.results["warnings"] += 1
            print(f"⚠ 无法完全验证 Batch Controller: {e}")

    def verify_phase_3(self):
        """验证第三阶段。"""
        print("\n【第三阶段】合卷级深度索引 (Cross-Paper Indexing)")
        print("-" * 60)

        print("检查核心文件...")
        self.check_file_exists(
            "layers/w_layer_cross_paper_analysis.py",
            "W-Layer (跨文分析层)"
        )
        self.check_file_exists(
            "12_卷级深度分析与索引脚本.py",
            "Volume Deep Analysis Script"
        )

        print("\n检查 Python 语法...")
        self.check_syntax(
            "layers/w_layer_cross_paper_analysis.py",
            "W-Layer syntax"
        )
        self.check_syntax(
            "12_卷级深度分析与索引脚本.py",
            "Volume Script syntax"
        )

        print("\n检查关键类...")
        try:
            from layers.w_layer_cross_paper_analysis import (
                ConflictDetector,
                GlobalIndexBuilder,
                CrossPaperAnalyzer
            )

            classes = [
                ('ConflictDetector', ConflictDetector),
                ('GlobalIndexBuilder', GlobalIndexBuilder),
                ('CrossPaperAnalyzer', CrossPaperAnalyzer)
            ]

            for class_name, class_obj in classes:
                self.results["passed"] += 1
                print(f"✓ {class_name} class")

            # 检查方法
            methods_map = {
                'ConflictDetector': ['detect_conflicts', 'generate_trend_table'],
                'GlobalIndexBuilder': ['index_volume_bundle', 'build_master_index'],
                'CrossPaperAnalyzer': ['analyze_volume_bundle', 'generate_final_report']
            }

            for class_name, methods in methods_map.items():
                for method in methods:
                    if hasattr(locals()[class_name], method):
                        self.results["passed"] += 1
                        print(f"✓ {class_name}.{method}()")
                    else:
                        self.results["failed"] += 1
                        print(f"✗ {class_name}.{method}()")
        except Exception as e:
            self.results["failed"] += 1
            print(f"✗ 无法导入 W-Layer: {e}")
            self.results["errors"].append(str(e))

    def verify_documentation(self):
        """验证文档。"""
        print("\n【文档】")
        print("-" * 60)

        docs = [
            ("IMPLEMENTATION_GUIDE_v3_Phase123.md", "详细实现指南"),
            ("QUICK_START_v3.md", "快速入门指南"),
        ]

        for doc_file, desc in docs:
            self.check_file_exists(doc_file, desc)

    def check_dependencies(self):
        """检查依赖。"""
        print("\n【依赖检查】")
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
                print(f"✓ {desc} ({module})")
            except ImportError:
                if module == "openai":
                    self.results["warnings"] += 1
                    print(f"⚠ {desc} ({module}) - Optional for LLM features")
                else:
                    self.results["failed"] += 1
                    print(f"✗ {desc} ({module})")

    def run_all_checks(self):
        """运行所有检查。"""
        print("\n" + "="*60)
        print("文献处理器 v40.0 升级验证")
        print("="*60)

        self.verify_phase_1()
        self.verify_phase_2()
        self.verify_phase_3()
        self.verify_documentation()
        self.check_dependencies()

        # 总结
        print("\n" + "="*60)
        print("验证结果总结")
        print("="*60)
        print(f"✓ 通过: {self.results['passed']}")
        print(f"✗ 失败: {self.results['failed']}")
        print(f"⚠ 警告: {self.results['warnings']}")

        if self.results['errors']:
            print("\n错误详情:")
            for error in self.results['errors']:
                print(f"  - {error}")

        print("\n" + "="*60)
        if self.results['failed'] == 0:
            print("✓ 所有检查通过！升级成功。")
            return True
        else:
            print("✗ 存在失败检查。请查看上述错误。")
            return False


def main():
    """主函数。"""
    import argparse

    parser = argparse.ArgumentParser(description='文献处理器 v40.0 升级验证')
    parser.add_argument('--base-path', type=Path, default=None, help='脚本基础路径')
    parser.add_argument('--json', action='store_true', help='以 JSON 格式输出')

    args = parser.parse_args()

    verifier = UpgradeVerifier(base_path=args.base_path)
    success = verifier.run_all_checks()

    if args.json:
        print("\n" + json.dumps(verifier.results, ensure_ascii=False, indent=2))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

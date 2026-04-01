# -*- coding: utf-8 -*-
"""
00_Batch_Process_Controller.py
文献处理器 v40.0 - 规模化批处理控制脚本 (第二阶段)

核心功能:
1. 自动遍历指定文件夹的所有 PDF 文件
2. 循环执行单篇文献流水线 (00_Integrated_Pipeline_v40.0.py)
3. 自动收集成功的 writing_material_pack.json
4. 当达到指定数量或全部完成时，自动触发卷级合卷
5. 生成批处理统计与质量报告
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import subprocess
import shutil

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BatchController_v40")


class BatchProcessController:
    """
    规模化批处理控制器。
    管理 PDF 文件夹的自动化流水线处理和卷级整合。
    """

    def __init__(self, pdf_folder: str, output_root: str, goal: str, 
                 pipeline_script: str = "00_Integrated_Pipeline_v40.0.py",
                 volume_script: str = "11_卷级合卷脚本.py",
                 batch_size: int = 13, enable_llm: bool = True):
        """
        Args:
            pdf_folder: 包含待处理 PDF 的文件夹路径
            output_root: 输出文件夹根路径
            goal: 统一的写作目标
            pipeline_script: 单篇流水线脚本名称
            volume_script: 卷级合卷脚本名称
            batch_size: 自动触发合卷的 PDF 数量
            enable_llm: 是否启用 LLM 增强分析
        """
        self.pdf_folder = Path(pdf_folder)
        self.output_root = Path(output_root)
        self.goal = goal
        self.pipeline_script = pipeline_script
        self.volume_script = volume_script
        self.batch_size = batch_size
        self.enable_llm = enable_llm

        # 确保输出目录存在
        self.output_root.mkdir(parents=True, exist_ok=True)

        # 日志路径
        self.batch_log_dir = self.output_root / "batch_logs"
        self.batch_log_dir.mkdir(parents=True, exist_ok=True)

        # 跟踪状态
        self.batch_stats = {
            "start_time": datetime.now().isoformat(),
            "pdf_folder": str(self.pdf_folder),
            "output_root": str(self.output_root),
            "goal": goal,
            "batch_size": batch_size,
            "total_pdfs": 0,
            "successful_pdfs": 0,
            "failed_pdfs": 0,
            "failed_details": [],
            "volumes_created": 0,
            "material_packs": [],
            "status": "initializing"
        }

    def discover_pdfs(self) -> List[Path]:
        """发现待处理的 PDF 文件。"""
        if not self.pdf_folder.exists():
            logger.error(f"PDF 文件夹不存在: {self.pdf_folder}")
            return []

        pdfs = sorted(self.pdf_folder.glob("*.pdf"))
        logger.info(f"发现 {len(pdfs)} 个 PDF 文件")
        return pdfs

    def run_single_pipeline(self, pdf_path: Path, batch_output_dir: Path) -> Tuple[bool, Path]:
        """
        执行单篇 PDF 的流水线处理。

        Returns:
            (成功标志, 输出目录路径)
        """
        logger.info(f"处理 PDF: {pdf_path.name}")

        try:
            # 构建命令
            cmd = [
                sys.executable,
                str(self.pipeline_script),
                str(pdf_path),
                "--goal", self.goal,
                "--out", str(batch_output_dir)
            ]

            # 执行流水线
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 分钟超时
            )

            if result.returncode != 0:
                logger.error(f"流水线执行失败: {pdf_path.name}")
                logger.error(f"stderr: {result.stderr}")
                return False, None

            # 验证输出
            expected_output_dir = batch_output_dir / pdf_path.stem
            if not expected_output_dir.exists():
                logger.error(f"输出目录不存在: {expected_output_dir}")
                return False, None

            # 验证关键文件
            material_pack_path = expected_output_dir / "02_writing_material_pack.json"
            if not material_pack_path.exists():
                logger.error(f"缺失 writing_material_pack.json: {pdf_path.name}")
                return False, None

            logger.info(f"✓ 处理成功: {pdf_path.name}")
            return True, expected_output_dir

        except subprocess.TimeoutExpired:
            logger.error(f"流水线超时: {pdf_path.name}")
            return False, None
        except Exception as e:
            logger.error(f"处理失败 ({pdf_path.name}): {e}")
            return False, None

    def collect_material_pack(self, output_dir: Path) -> Dict[str, Any]:
        """从输出目录收集 writing_material_pack.json。"""
        material_pack_path = output_dir / "02_writing_material_pack.json"

        if not material_pack_path.exists():
            logger.warning(f"缺失 material pack: {output_dir}")
            return None

        try:
            with open(material_pack_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取 material pack 失败: {e}")
            return None

    def create_volume_bundle(self, material_packs: List[Path], volume_id: str) -> bool:
        """
        触发卷级合卷脚本。

        Args:
            material_packs: writing_material_pack.json 文件列表
            volume_id: 卷 ID (如 V01, V02)

        Returns:
            是否成功
        """
        logger.info(f"触发卷级合卷 ({volume_id}): {len(material_packs)} 篇文献")

        try:
            volume_output_dir = self.output_root / f"volume_{volume_id}"
            volume_output_dir.mkdir(parents=True, exist_ok=True)

            volume_bundle_path = volume_output_dir / f"volume_bundle_{volume_id}.json"

            # 构建命令
            cmd = [
                sys.executable,
                str(self.volume_script),
                "--inputs", *[str(p) for p in material_packs],
                "--output-json", str(volume_bundle_path),
                "--volume-id", volume_id
            ]

            # 执行合卷脚本
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 分钟超时
            )

            if result.returncode != 0:
                logger.error(f"卷级合卷失败: {volume_id}")
                logger.error(f"stderr: {result.stderr}")
                return False

            if not volume_bundle_path.exists():
                logger.error(f"卷级输出文件不存在: {volume_bundle_path}")
                return False

            logger.info(f"✓ 卷级合卷成功: {volume_id} -> {volume_bundle_path}")
            self.batch_stats["volumes_created"] += 1

            # 生成卷级统计
            self._generate_volume_stats(volume_bundle_path)

            return True

        except subprocess.TimeoutExpired:
            logger.error(f"卷级合卷超时: {volume_id}")
            return False
        except Exception as e:
            logger.error(f"卷级合卷失败: {e}")
            return False

    def _generate_volume_stats(self, volume_bundle_path: Path):
        """生成卷级统计信息。"""
        try:
            with open(volume_bundle_path, 'r', encoding='utf-8') as f:
                bundle = json.load(f)

            stats = {
                "volume_id": bundle.get('volume_id'),
                "paper_count": bundle.get('paper_count', 0),
                "writing_point_count": bundle.get('stats', {}).get('writing_point_count', 0),
                "figure_count": bundle.get('stats', {}).get('figure_count', 0),
                "created_at": datetime.now().isoformat()
            }

            stats_path = volume_bundle_path.parent / f"volume_stats_{stats['volume_id']}.json"
            with open(stats_path, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)

            logger.info(f"卷级统计: {stats}")
        except Exception as e:
            logger.warning(f"生成卷级统计失败: {e}")

    def process_batch(self) -> Dict[str, Any]:
        """
        执行批处理主流程。

        Returns:
            批处理结果统计
        """
        logger.info("="*60)
        logger.info("开始批处理流程")
        logger.info("="*60)

        pdfs = self.discover_pdfs()
        if not pdfs:
            logger.error("未发现任何 PDF 文件")
            self.batch_stats["status"] = "failed"
            return self.batch_stats

        self.batch_stats["total_pdfs"] = len(pdfs)
        self.batch_stats["status"] = "processing"

        # 创建批处理输出目录
        batch_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_output_root = self.output_root / f"batch_{batch_time}"
        batch_output_root.mkdir(parents=True, exist_ok=True)

        # 处理每个 PDF
        volume_packs = []
        current_volume = 1

        for i, pdf_path in enumerate(pdfs, start=1):
            logger.info(f"\n[{i}/{len(pdfs)}] 处理文献...")

            success, output_dir = self.run_single_pipeline(pdf_path, batch_output_root)

            if success:
                self.batch_stats["successful_pdfs"] += 1

                # 收集 material pack
                material_pack_path = output_dir / "02_writing_material_pack.json"
                if material_pack_path.exists():
                    volume_packs.append(material_pack_path)
                    self.batch_stats["material_packs"].append({
                        "pdf": pdf_path.name,
                        "path": str(material_pack_path)
                    })

                # 检查是否需要触发卷级合卷
                if len(volume_packs) >= self.batch_size:
                    logger.info(f"\n达到卷大小限制 ({len(volume_packs)} >= {self.batch_size}), 触发卷级合卷...")
                    volume_id = f"V{current_volume:02d}"
                    volume_success = self.create_volume_bundle(volume_packs, volume_id)

                    if volume_success:
                        current_volume += 1

                    # 重置卷累计器
                    volume_packs = []
            else:
                self.batch_stats["failed_pdfs"] += 1
                self.batch_stats["failed_details"].append({
                    "pdf": pdf_path.name,
                    "error": "Pipeline execution failed"
                })

        # 处理剩余的 material packs
        if volume_packs:
            logger.info(f"\n处理剩余文献 ({len(volume_packs)} 篇), 触发最终卷级合卷...")
            volume_id = f"V{current_volume:02d}"
            self.create_volume_bundle(volume_packs, volume_id)

        # 完成统计
        self.batch_stats["end_time"] = datetime.now().isoformat()
        self.batch_stats["status"] = "completed"

        return self.batch_stats

    def save_batch_report(self):
        """保存批处理报告。"""
        report_path = self.batch_log_dir / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.batch_stats, f, ensure_ascii=False, indent=2)

        logger.info(f"\n批处理报告已保存: {report_path}")

        # 同时输出摘要
        summary = {
            "total_pdfs": self.batch_stats["total_pdfs"],
            "successful_pdfs": self.batch_stats["successful_pdfs"],
            "failed_pdfs": self.batch_stats["failed_pdfs"],
            "success_rate": f"{100 * self.batch_stats['successful_pdfs'] / max(1, self.batch_stats['total_pdfs']):.1f}%",
            "volumes_created": self.batch_stats["volumes_created"],
            "output_root": str(self.output_root)
        }

        logger.info("\n" + "="*60)
        logger.info("批处理摘要:")
        logger.info("="*60)
        for key, value in summary.items():
            logger.info(f"  {key}: {value}")
        logger.info("="*60)

        return report_path


def main():
    parser = argparse.ArgumentParser(
        description='文献处理器 v40.0 - 批处理控制脚本'
    )
    parser.add_argument('pdf_folder', help='包含 PDF 文件的文件夹路径')
    parser.add_argument('--goal', default='提取文献核心结论与实验数据', help='写作目标')
    parser.add_argument('--out', default='batch_output', help='输出根目录')
    parser.add_argument('--batch-size', type=int, default=13, help='自动触发合卷的 PDF 数量')
    parser.add_argument('--pipeline', default='00_Integrated_Pipeline_v40.0.py', help='流水线脚本名称')
    parser.add_argument('--volume-script', default='11_卷级合卷脚本.py', help='卷级合卷脚本名称')
    parser.add_argument('--disable-llm', action='store_true', help='禁用 LLM 增强分析')

    args = parser.parse_args()

    try:
        controller = BatchProcessController(
            pdf_folder=args.pdf_folder,
            output_root=args.out,
            goal=args.goal,
            pipeline_script=args.pipeline,
            volume_script=args.volume_script,
            batch_size=args.batch_size,
            enable_llm=not args.disable_llm
        )

        stats = controller.process_batch()
        controller.save_batch_report()

        print(json.dumps({
            "status": "success",
            "summary": {
                "total": stats["total_pdfs"],
                "success": stats["successful_pdfs"],
                "failed": stats["failed_pdfs"],
                "volumes": stats["volumes_created"]
            }
        }, ensure_ascii=False, indent=2))

    except Exception as e:
        logger.error(f"批处理失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

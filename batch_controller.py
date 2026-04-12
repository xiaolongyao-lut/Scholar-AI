# -*- coding: utf-8 -*-
"""
batch_controller.py
Literature Processor - Scaleable Batch Processing Controller
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("BatchController")

class BatchProcessController:
    """
    Controller for automated PDF processing and volume integration.
    """

    def __init__(self, pdf_folder: str, output_root: str, goal: str, 
                 pipeline_script: str = "pipeline_core.py",
                 volume_script: str = "volume_merger.py",
                 batch_size: int = 13, enable_llm: bool = True):
        self.pdf_folder = Path(pdf_folder)
        self.output_root = Path(output_root)
        self.goal = goal
        self.pipeline_script = pipeline_script
        self.volume_script = volume_script
        self.batch_size = batch_size
        self.enable_llm = enable_llm
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.batch_log_dir = self.output_root / "batch_logs"
        self.batch_log_dir.mkdir(parents=True, exist_ok=True)
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
        if not self.pdf_folder.exists():
            logger.error(f"PDF folder not found: {self.pdf_folder}")
            return []
        pdfs = sorted(self.pdf_folder.glob("*.pdf"))
        logger.info(f"Discovered {len(pdfs)} PDF files")
        return pdfs

    def run_single_pipeline(self, pdf_path: Path, batch_output_dir: Path) -> Tuple[bool, Path]:
        logger.info(f"Processing PDF: {pdf_path.name}")
        try:
            cmd = [
                sys.executable,
                str(self.pipeline_script),
                str(pdf_path),
                "--goal", self.goal,
                "--out", str(batch_output_dir)
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            if result.returncode != 0:
                logger.error(f"Pipeline failed: {pdf_path.name}")
                logger.error(f"stderr: {result.stderr}")
                return False, None
            expected_output_dir = batch_output_dir / pdf_path.stem
            if not expected_output_dir.exists():
                logger.error(f"Output directory not found: {expected_output_dir}")
                return False, None
            material_pack_path = expected_output_dir / "02_writing_material_pack.json"
            if not material_pack_path.exists():
                logger.error(f"Missing writing_material_pack.json: {pdf_path.name}")
                return False, None
            logger.info(f"Success: {pdf_path.name}")
            return True, expected_output_dir
        except Exception as e:
            logger.error(f"Processing failed ({pdf_path.name}): {e}")
            return False, None

    def create_volume_bundle(self, material_packs: List[Path], volume_id: str) -> bool:
        logger.info(f"Triggering Volume Merge ({volume_id}): {len(material_packs)} papers")
        try:
            volume_output_dir = self.output_root / f"volume_{volume_id}"
            volume_output_dir.mkdir(parents=True, exist_ok=True)
            volume_bundle_path = volume_output_dir / f"volume_bundle_{volume_id}.json"
            cmd = [
                sys.executable,
                str(self.volume_script),
                "--inputs", *[str(p) for p in material_packs],
                "--output-json", str(volume_bundle_path),
                "--volume-id", volume_id
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                logger.error(f"Volume Merge failed: {volume_id}")
                return False
            logger.info(f"Volume Merge Success: {volume_id} -> {volume_bundle_path}")
            self.batch_stats["volumes_created"] += 1
            return True
        except Exception as e:
            logger.error(f"Volume Merge failed: {e}")
            return False

    def process_batch(self) -> Dict[str, Any]:
        logger.info("Starting Batch Processing")
        pdfs = self.discover_pdfs()
        if not pdfs:
            self.batch_stats["status"] = "failed"
            return self.batch_stats
        self.batch_stats["total_pdfs"] = len(pdfs)
        self.batch_stats["status"] = "processing"
        batch_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_output_root = self.output_root / f"batch_{batch_time}"
        batch_output_root.mkdir(parents=True, exist_ok=True)
        volume_packs = []
        current_volume = 1
        for i, pdf_path in enumerate(pdfs, start=1):
            success, output_dir = self.run_single_pipeline(pdf_path, batch_output_root)
            if success:
                self.batch_stats["successful_pdfs"] += 1
                material_pack_path = output_dir / "02_writing_material_pack.json"
                if material_pack_path.exists():
                    volume_packs.append(material_pack_path)
                if len(volume_packs) >= self.batch_size:
                    volume_id = f"V{current_volume:02d}"
                    if self.create_volume_bundle(volume_packs, volume_id):
                        current_volume += 1
                    volume_packs = []
            else:
                self.batch_stats["failed_pdfs"] += 1
        if volume_packs:
            volume_id = f"V{current_volume:02d}"
            self.create_volume_bundle(volume_packs, volume_id)
        self.batch_stats["end_time"] = datetime.now().isoformat()
        self.batch_stats["status"] = "completed"
        return self.batch_stats

    def save_batch_report(self):
        report_path = self.batch_log_dir / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.batch_stats, f, ensure_ascii=False, indent=2)
        return report_path

def main():
    parser = argparse.ArgumentParser(description='Batch Processing Controller')
    parser.add_argument('pdf_folder', help='PDF folder path')
    parser.add_argument('--goal', default='Conclusion Extraction', help='Goal')
    parser.add_argument('--out', default='batch_output', help='Output root')
    parser.add_argument('--batch-size', type=int, default=13, help='Papers per volume')
    parser.add_argument('--pipeline', default='pipeline_core.py', help='Pipeline core script')
    parser.add_argument('--volume-script', default='volume_merger.py', help='Volume merger script')
    parser.add_argument('--disable-llm', action='store_true', help='Disable LLM enrichment')
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
        print(json.dumps({"status": "success", "summary": stats}, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"Batch processing failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

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
from typing import Dict, List, Any, Tuple, Callable
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
                 batch_size: int = 13, enable_llm: bool = True,
                 progress_callback: Callable[[float, str], None] | None = None):
        self.pdf_folder = Path(pdf_folder)
        self.output_root = Path(output_root)
        self.goal = goal
        self.pipeline_script = pipeline_script
        self.volume_script = volume_script
        self.batch_size = batch_size
        self.enable_llm = enable_llm
        self.progress_callback = progress_callback
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

    def _notify_progress(self, progress: float, stage: str) -> None:
        """Best-effort progress callback for external task trackers."""
        if self.progress_callback is None:
            return
        try:
            bounded = max(0.0, min(100.0, float(progress)))
            self.progress_callback(bounded, str(stage))
        except (TypeError, ValueError) as exc:
            logger.debug("Progress callback failed: %s", exc)

    def discover_pdfs(self) -> List[Path]:
        if not self.pdf_folder.exists():
            logger.error("PDF folder not found: %s", self.pdf_folder)
            return []
        pdfs = sorted(self.pdf_folder.glob("*.pdf"))
        logger.info("Discovered %s PDF files", len(pdfs))
        return pdfs

    def _use_direct_pipeline(self) -> bool:
        return Path(self.pipeline_script).name == "pipeline_core.py"

    def _use_direct_volume_merge(self) -> bool:
        return Path(self.volume_script).name == "volume_merger.py"

    def run_single_pipeline(self, pdf_path: Path, batch_output_dir: Path) -> Tuple[bool, Path]:
        logger.info("Processing PDF: %s", pdf_path.name)
        try:
            output_dir = None
            if self._use_direct_pipeline():
                logger.info("Running pipeline via direct function call")
                try:
                    from pipeline_core import run_pipeline
                except (ImportError, SystemExit) as e:
                    logger.error("Direct pipeline import failed: %s", e)
                    return False, None
                result = run_pipeline(str(pdf_path), self.goal, str(batch_output_dir))
                if isinstance(result, dict):
                    status = result.get("status")
                    if status and status != "success":
                        logger.error("Pipeline returned status: %s", status)
                        return False, None
                    output_dir = Path(result.get("output_dir") or (batch_output_dir / pdf_path.stem))
                else:
                    output_dir = batch_output_dir / pdf_path.stem
            else:
                logger.info("Running pipeline via subprocess")
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
                    timeout=600,
                    check=False
                )
                if result.returncode != 0:
                    logger.error("Pipeline failed: %s", pdf_path.name)
                    logger.error("stderr: %s", result.stderr)
                    return False, None
                output_dir = batch_output_dir / pdf_path.stem

            if output_dir is None:
                logger.error("Output directory not resolved: %s", pdf_path.name)
                return False, None
            if not output_dir.exists():
                logger.error("Output directory not found: %s", output_dir)
                return False, None
            material_pack_path = output_dir / "02_writing_material_pack.json"
            if not material_pack_path.exists():
                logger.error("Missing writing_material_pack.json: %s", pdf_path.name)
                return False, None
            logger.info("Success: %s", pdf_path.name)
            return True, output_dir
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Processing failed (%s): %s", pdf_path.name, e)
            return False, None

    def _generate_volume_stats(self, material_packs: List[Path], volume_id: str, volume_bundle_path: Path) -> Dict[str, Any]:
        """Generate volume statistics from material packs and bundle."""
        paper_count = len(material_packs)
        writing_point_count = 0
        total_parameters = 0
        
        # Count writing points from material packs
        for pack_path in material_packs:
            try:
                if pack_path.exists():
                    with open(pack_path, 'r', encoding='utf-8') as f:
                        pack_data = json.load(f)
                    # Count writing_points array
                    points = pack_data.get('writing_points', [])
                    writing_point_count += len(points)
            except Exception as e:
                logger.warning("Failed to read material pack %s: %s", pack_path, e)
        
        # Try to read volume bundle to extract metadata
        try:
            if volume_bundle_path.exists():
                with open(volume_bundle_path, 'r', encoding='utf-8') as f:
                    bundle = json.load(f)
                # Extract tracked parameters count if available
                total_parameters = len(bundle.get('all_parameters', set()))
        except Exception as e:
            logger.warning("Failed to read volume bundle: %s", e)
        
        stats = {
            "volume_id": volume_id,
            "created_at": datetime.now().isoformat(),
            "paper_count": paper_count,
            "writing_point_count": writing_point_count,
            "tracked_parameter_count": total_parameters,
            "material_packs": [str(p) for p in material_packs],
        }
        return stats

    def create_volume_bundle(self, material_packs: List[Path], volume_id: str) -> bool:
        logger.info("Triggering Volume Merge (%s): %s papers", volume_id, len(material_packs))
        try:
            volume_output_dir = self.output_root / f"volume_{volume_id}"
            volume_output_dir.mkdir(parents=True, exist_ok=True)
            volume_bundle_path = volume_output_dir / f"volume_bundle_{volume_id}.json"
            if self._use_direct_volume_merge():
                logger.info("Running volume merge via direct function call")
                try:
                    from layers.v_layer_volume_bundle import build_volume_bundle, dump_volume_bundle
                except (ImportError, SystemExit) as e:
                    logger.error("Direct volume merge import failed: %s", e)
                    return False
                bundle = build_volume_bundle(material_packs, volume_id=volume_id)
                dump_volume_bundle(bundle, volume_bundle_path)
            else:
                logger.info("Running volume merge via subprocess")
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
                    timeout=300,
                    check=False
                )
                if result.returncode != 0:
                    logger.error("Volume Merge failed: %s", volume_id)
                    logger.error("stderr: %s", result.stderr)
                    return False
            logger.info("Volume Merge Success: %s -> %s", volume_id, volume_bundle_path)
            
            # Generate volume statistics
            volume_stats = self._generate_volume_stats(material_packs, volume_id, volume_bundle_path)
            volume_stats_path = volume_output_dir / f"volume_stats_{volume_id}.json"
            with open(volume_stats_path, 'w', encoding='utf-8') as f:
                json.dump(volume_stats, f, ensure_ascii=False, indent=2)
            logger.info("Volume stats saved: %s", volume_stats_path)
            
            self.batch_stats["volumes_created"] += 1
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Volume Merge failed: %s", e)
            return False

    def process_batch(self) -> Dict[str, Any]:
        logger.info("Starting Batch Processing")
        pdfs = self.discover_pdfs()
        if not pdfs:
            self.batch_stats["status"] = "failed"
            self._notify_progress(100.0, "No PDFs found")
            return self.batch_stats
        self.batch_stats["total_pdfs"] = len(pdfs)
        self.batch_stats["status"] = "processing"
        self._notify_progress(2.0, "Discovered PDFs")
        batch_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_output_root = self.output_root / f"batch_{batch_time}"
        batch_output_root.mkdir(parents=True, exist_ok=True)
        volume_packs = []
        current_volume = 1
        total_pdfs = len(pdfs)
        for processed_count, pdf_path in enumerate(pdfs, start=1):
            self._notify_progress(
                min(95.0, 5.0 + ((processed_count - 1) / max(1, total_pdfs)) * 85.0),
                f"Processing PDF {processed_count}/{total_pdfs}: {pdf_path.name}",
            )
            success, output_dir = self.run_single_pipeline(pdf_path, batch_output_root)
            if success:
                self.batch_stats["successful_pdfs"] += 1
                material_pack_path = output_dir / "02_writing_material_pack.json"
                if material_pack_path.exists():
                    volume_packs.append(material_pack_path)
                if len(volume_packs) >= self.batch_size:
                    volume_id = f"V{current_volume:02d}"
                    self._notify_progress(
                        min(97.0, 5.0 + (processed_count / max(1, total_pdfs)) * 90.0),
                        f"Merging volume {volume_id}",
                    )
                    if self.create_volume_bundle(volume_packs, volume_id):
                        current_volume += 1
                    volume_packs = []
            else:
                self.batch_stats["failed_pdfs"] += 1
        if volume_packs:
            volume_id = f"V{current_volume:02d}"
            self._notify_progress(97.0, f"Merging volume {volume_id}")
            self.create_volume_bundle(volume_packs, volume_id)
        self.batch_stats["end_time"] = datetime.now().isoformat()
        self.batch_stats["status"] = "completed"
        self._notify_progress(100.0, "Completed")
        return self.batch_stats

    def save_batch_report(self):
        report_name = f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path = self.batch_log_dir / report_name
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(self.batch_stats, f, ensure_ascii=False, indent=2)
            
        # Update batch logs index
        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            start_time_iso = self.batch_stats.get("start_time")
            if start_time_iso:
                start_dt = datetime.fromisoformat(start_time_iso)
                batch_id = f"batch_{start_dt.strftime('%Y%m%d_%H%M%S')}"
        except Exception:
            pass

        total = self.batch_stats.get("total_pdfs", 0)
        success = self.batch_stats.get("successful_pdfs", 0)
        success_rate = (success / total) if total > 0 else 0.0

        try:
            rel_report_path = str(report_path.relative_to(self.output_root.parent))
        except ValueError:
            rel_report_path = str(report_path)

        index_entry = {
            "batch_id": batch_id,
            "timestamp": self.batch_stats.get("start_time", datetime.now().isoformat()),
            "pdf_folder": self.batch_stats.get("pdf_folder", ""),
            "output_root": self.batch_stats.get("output_root", ""),
            "goal": self.batch_stats.get("goal", ""),
            "batch_size": self.batch_stats.get("batch_size", 0),
            "total_pdfs": total,
            "successful_pdfs": success,
            "failed_pdfs": self.batch_stats.get("failed_pdfs", 0),
            "success_rate": round(success_rate, 4),
            "volumes_created": self.batch_stats.get("volumes_created", 0),
            "report_path": rel_report_path.replace('\\', '/'),
            "failed_samples": self.batch_stats.get("failed_details", [])
        }

        index_path = self.batch_log_dir / "index.json"
        index_data = {"batch_run_history": []}
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
            except Exception:
                pass
        
        index_data.setdefault("batch_run_history", []).append(index_entry)
        
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
            
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
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Batch processing failed: %s", e, exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

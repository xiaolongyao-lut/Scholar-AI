"""
Academic Paper Scoring System - Main Entry Point
Command-line interface for batch processing and scoring academic papers.
"""

import argparse
import logging
import sys
from pathlib import Path

from modules.batch_manager import BatchManager
from modules.result_exporter import ResultExporter
from modules.configuration_manager import get_configuration, set_configuration_path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ScoringSystem")


def main():
    parser = argparse.ArgumentParser(description="Academic Paper Scoring & Evidence Extraction System")
    
    parser.add_argument(
        "--input_dir", 
        type=str, 
        required=True,
        help="Root directory containing paper extraction folders (e.g. ./output)"
    )
    
    parser.add_argument(
        "--output_dir", 
        type=str, 
        default="./scoring_reports",
        help="Directory to save the scoring reports"
    )
    
    parser.add_argument(
        "--config", 
        type=str, 
        help="Path to custom scoring_rules.json"
    )
    
    parser.add_argument(
        "--pattern", 
        type=str, 
        default="**/01_full_extract.json",
        help="Glob pattern to find extraction JSON files"
    )
    
    parser.add_argument(
        "--name", 
        type=str, 
        default="paper_scoring_analysis",
        help="Base name for the output files"
    )
    
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable parallel processing for faster execution"
    )
    
    parser.add_argument(
        "--workers",
        type=int,
        help="Number of parallel workers (default: min(CPU count, 16))"
    )
    
    parser.add_argument(
        "--mode",
        type=str,
        choices=["auto", "thread", "process", "off"],
        default="auto",
        help="Parallel execution mode (default: auto)"
    )

    args = parser.parse_args()

    # 1. Initialize Configuration
    if args.config:
        set_configuration_path(args.config)
    
    config = get_configuration()
    logger.info(f"Using configuration: {config.config_path}")

    # 2. Process Batch
    def progress_callback(current, total, paper_id):
        print(f"进度: [{current}/{total}] 正在处理: {paper_id}...")

    batch_manager = BatchManager(config)
    try:
        reports = batch_manager.scan_and_process(
            args.input_dir, 
            pattern=args.pattern,
            on_progress=progress_callback,
            parallel=args.parallel,
            num_workers=args.workers,
            parallel_mode=args.mode
        )
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        sys.exit(1)

    if not reports:
        logger.warning("No papers were processed. Check your input_dir and pattern.")
        sys.exit(0)

    # 3. Export Results
    exporter = ResultExporter(config)
    export_paths = exporter.export_all(reports, args.output_dir, base_name=args.name)

    # 4. Final Summary
    summary = batch_manager.get_summary()
    print("\n" + "="*50)
    print("处理完成报告")
    print("="*50)
    print(f"成功处理文献数: {summary['total_processed']}")
    print(f"平局总体得分: {summary['average_score']}")
    print(f"质量分布: {summary['quality_distribution']}")
    print("\n导出文件:")
    for fmt, path in export_paths.items():
        print(f"  - [{fmt.upper()}]: {path}")
    print("="*50)


if __name__ == "__main__":
    main()

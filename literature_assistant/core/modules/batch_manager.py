"""
Batch Manager Module
Orchestrates processing across multiple academic papers
"""

import logging
from typing import TYPE_CHECKING, List, Dict, Any, Optional, Callable
from pathlib import Path
import os

if TYPE_CHECKING:
    from literature_assistant.core.modules.configuration_manager import (
        ConfigurationManager,
        get_configuration,
    )
    from literature_assistant.core.modules.paper_processor import (
        PaperProcessReport,
        PaperProcessor,
    )
else:
    from modules.configuration_manager import get_configuration
    from modules.paper_processor import PaperProcessReport, PaperProcessor

logger = logging.getLogger(__name__)


class BatchManager:
    """Manages the processing of a collection of academic papers"""

    def __init__(self, config: "ConfigurationManager | None" = None) -> None:
        """Initialize batch manager"""
        self.config = config or get_configuration()
        self.processor = PaperProcessor(self.config)
        self.reports: List[PaperProcessReport] = []

    def scan_and_process(
        self, 
        input_directory: str, 
        pattern: str = "**/01_full_extract.json",
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        parallel: bool = False,
        num_workers: Optional[int] = None,
        parallel_mode: str = "auto"
    ) -> List[PaperProcessReport]:
        """
        Scan directory for extraction files and process them
        
        Args:
            input_directory: Root directory to scan
            pattern: Glob pattern to find extraction files
            on_progress: Optional callback function (current, total, filename)
            parallel: Whether to enable parallel processing
            num_workers: Number of workers for parallel mode
            parallel_mode: 'auto', 'thread', or 'process'
            
        Returns:
            List of PaperProcessReport objects
        """
        root_path = Path(input_directory)
        if not root_path.exists():
            raise NotADirectoryError(f"Input directory not found: {input_directory}")

        # Find all extraction files
        extract_files = list(root_path.glob(pattern))
        total_files = len(extract_files)
        
        if total_files == 0:
            logger.warning(f"No files matching {pattern} found in {input_directory}")
            return []

        logger.info(f"Found {total_files} papers to process in {input_directory}")
        self.reports = []

        if not parallel:
            # Sequential execution (default)
            for i, file_path in enumerate(extract_files, 1):
                try:
                    paper_id = file_path.parent.name
                    if on_progress:
                        on_progress(i, total_files, paper_id)
                    
                    logger.info(f"[{i}/{total_files}] Processing {paper_id}...")
                    
                    report = self.processor.process_json_file(str(file_path), paper_id)
                    self.reports.append(report)
                    
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
        else:
            # Parallel execution
            if TYPE_CHECKING:
                from literature_assistant.core.modules.parallel_processor import (
                    ParallelPaperProcessor,
                )
            else:
                from modules.parallel_processor import ParallelPaperProcessor
            
            p_processor = ParallelPaperProcessor(self.config)
            tasks = [
                {"file_path": str(fp), "paper_id": fp.parent.name} 
                for fp in extract_files
            ]
            
            batch_result = p_processor.process_batch(
                tasks=tasks,
                mode=parallel_mode,
                num_workers=num_workers,
                on_progress=on_progress
            )
            
            self.reports = batch_result.reports
            # Any specific logging or error collection can be done here from batch_result.failed_items

        return self.reports

    def get_summary(self) -> Dict[str, Any]:
        """Generate a high-level summary of the processed batch"""
        if not self.reports:
            return {"total_processed": 0}

        avg_score = sum(r.overall_score for r in self.reports) / len(self.reports)
        
        # Count quality levels
        quality_counts = {"High": 0, "Medium": 0, "Low": 0}
        for r in self.reports:
            # Determine quality label based on overall score
            label = self.config.get_classification_quality(r.overall_score)
            quality_counts[label] += 1

        return {
            "total_processed": len(self.reports),
            "average_score": round(avg_score, 4),
            "quality_distribution": quality_counts,
            "papers": [
                {
                    "id": r.paper_id,
                    "score": round(r.overall_score, 4),
                    "confidence": round(r.overall_confidence, 4)
                }
                for r in self.reports
            ]
        }

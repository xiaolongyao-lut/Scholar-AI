"""
Parallel Processor Module
Provides deterministic parallel execution for paper scoring tasks.
Supports both ThreadPool and ProcessPool with per-file error isolation.
"""

import os
import time
import logging
import concurrent.futures
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path

from modules.paper_processor import PaperProcessor, PaperProcessReport
from modules.configuration_manager import get_configuration, set_configuration_path

logger = logging.getLogger("scoring_system.parallel")


@dataclass
class ParallelBatchResult:
    """Summary of a parallel batch execution"""
    reports: List[PaperProcessReport] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    failed_items: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_time: float = 0.0
    throughput: float = 0.0  # papers per second
    mode: str = "off"
    num_workers: int = 1


def _worker_process_paper(file_path: str, paper_id: str, config_path: Optional[str] = None) -> Any:
    """
    Module-level worker function for ProcessPoolExecutor compatibility.
    Re-initializes the environment in child processes.
    """
    try:
        # Re-set configuration path if provided (for child processes)
        if config_path:
            set_configuration_path(config_path)
        
        # Ensure classifiers are registered in new process context
        import modules.evidence_classifier # Non-top-level import to avoid circular dependencies
        
        config = get_configuration()
        processor = PaperProcessor(config)
        return processor.process_json_file(file_path, paper_id)
    except Exception as e:
        # Return error info instead of raising to avoid crashing the whole pool
        return {"error": str(e), "file_path": file_path, "paper_id": paper_id}


class ParallelPaperProcessor:
    """Orchestrates parallel paper processing with determinism and error isolation"""

    def __init__(self, config=None):
        """Initialize parallel processor"""
        self.config = config or get_configuration()
        self.config_path = self.config.config_path

    def process_batch(
        self, 
        tasks: List[Dict[str, str]], 
        mode: str = "auto", 
        num_workers: Optional[int] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None
    ) -> ParallelBatchResult:
        """
        Process a list of paper tasks in parallel.
        
        Args:
            tasks: List of dicts with 'file_path' and 'paper_id'
            mode: 'auto', 'process', 'thread', or 'off'
            num_workers: Number of workers (default: CPU count)
            on_progress: Progress callback
            
        Returns:
            ParallelBatchResult object
        """
        start_time = time.time()
        
        # 1. Determine mode and workers
        if mode == "auto":
            # For CPU-heavy RegEx tasks, process pool is generally better
            actual_mode = "process"
            actual_workers = num_workers or min(os.cpu_count() or 4, 16)
        else:
            actual_mode = mode
            actual_workers = num_workers or min(os.cpu_count() or 4, 16)

        if actual_mode == "off":
            actual_workers = 1

        logger.info(
            "Starting parallel batch: mode=%s, workers=%d, total_tasks=%d",
            actual_mode, actual_workers, len(tasks)
        )

        reports: List[PaperProcessReport] = []
        failed_items: List[Dict[str, Any]] = []
        
        # 2. Execute based on mode
        total_tasks = len(tasks)
        
        if actual_mode == "off" or actual_workers <= 1:
            # Single-threaded fallback
            for i, task in enumerate(tasks, 1):
                paper_id = task["paper_id"]
                if on_progress:
                    on_progress(i, total_tasks, paper_id)
                
                result = _worker_process_paper(task["file_path"], paper_id, self.config_path)
                self._handle_result(result, reports, failed_items)
        else:
            # Parallel execution
            executor_class = (
                concurrent.futures.ProcessPoolExecutor 
                if actual_mode == "process" 
                else concurrent.futures.ThreadPoolExecutor
            )
            
            with executor_class(max_workers=actual_workers) as executor:
                # Use map to maintain order, but we want async progress updates
                # So we use submit and track futures with original index
                future_to_task = {
                    executor.submit(
                        _worker_process_paper, 
                        t["file_path"], 
                        t["paper_id"], 
                        self.config_path
                    ): (i, t["paper_id"]) 
                    for i, t in enumerate(tasks)
                }
                
                # Pre-allocate results list for determinism
                results_indexed: List[Optional[Any]] = [None] * total_tasks
                completed_count = 0
                
                for future in concurrent.futures.as_completed(future_to_task):
                    index, paper_id = future_to_task[future]
                    completed_count += 1
                    
                    if on_progress:
                        on_progress(completed_count, total_tasks, paper_id)
                        
                    try:
                        results_indexed[index] = future.result()
                    except Exception as e:
                        results_indexed[index] = {
                            "error": f"Pool Error: {str(e)}", 
                            "paper_id": paper_id,
                            "file_path": tasks[index]["file_path"]
                        }

                # Aggregation
                for res in results_indexed:
                    if res:
                        self._handle_result(res, reports, failed_items)

        elapsed = time.time() - start_time
        throughput = len(tasks) / elapsed if elapsed > 0 else 0
        
        logger.info(
            "Batch complete: success=%d, failure=%d, elapsed=%.2fs, throughput=%.2f p/s",
            len(reports), len(failed_items), elapsed, throughput
        )

        return ParallelBatchResult(
            reports=reports,
            success_count=len(reports),
            failure_count=len(failed_items),
            failed_items=failed_items,
            elapsed_time=elapsed,
            throughput=throughput,
            mode=actual_mode,
            num_workers=actual_workers
        )

    def _handle_result(self, result: Any, reports: List[PaperProcessReport], failed_items: List[Dict[str, Any]]):
        """Helper to separate success from failure results"""
        if isinstance(result, dict) and "error" in result:
            failed_items.append(result)
            logger.error("Paper processing failed: %s (%s)", result.get("paper_id"), result.get("error"))
        elif isinstance(result, PaperProcessReport):
            reports.append(result)
        else:
            # Fallback for unexpected return types
            error_data = {"error": f"Unexpected result type: {type(result)}", "data": str(result)}
            failed_items.append(error_data)
            logger.error("Paper processing returned unexpected data type")

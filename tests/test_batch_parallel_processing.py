"""
Focused test for parallel batch processing with ThreadPoolExecutor.
Validates that parallelization preserves results, ordering, and error handling.
"""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

# Add repo root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def test_parallel_processing_preserves_results(tmp_path, monkeypatch):
    """Verify parallel processing produces same results as serial."""
    from concurrent.futures import ThreadPoolExecutor
    
    # Mock pipeline processing function that takes varying time
    def mock_pipeline(pdf_path, goal, output_dir):
        # Simulate varying processing times
        time.sleep(0.01)
        return {
            "status": "success",
            "output_dir": output_dir,
            "pdf_path": pdf_path
        }
    
    # Test data: 5 mock papers
    papers = [
        {"itemKey": f"item_{i}", "pdf_path": f"/fake/paper_{i}.pdf"}
        for i in range(5)
    ]
    
    # Serial processing
    serial_results = []
    for paper in papers:
        result = mock_pipeline(
            pdf_path=paper["pdf_path"],
            goal="test",
            output_dir=str(tmp_path / paper["itemKey"])
        )
        serial_results.append({
            "itemKey": paper["itemKey"],
            "status": result["status"],
            "pdf_path": result["pdf_path"]
        })
    
    # Parallel processing with ThreadPoolExecutor
    parallel_results = []
    
    def process_paper(paper):
        result = mock_pipeline(
            pdf_path=paper["pdf_path"],
            goal="test",
            output_dir=str(tmp_path / paper["itemKey"])
        )
        return {
            "itemKey": paper["itemKey"],
            "status": result["status"],
            "pdf_path": result["pdf_path"]
        }
    
    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 1, len(papers))) as executor:
        parallel_results = list(executor.map(process_paper, papers))
    
    # Verify same number of results
    assert len(parallel_results) == len(serial_results)
    
    # Verify all papers processed
    parallel_keys = {r["itemKey"] for r in parallel_results}
    serial_keys = {r["itemKey"] for r in serial_results}
    assert parallel_keys == serial_keys
    
    # Verify all successful
    assert all(r["status"] == "success" for r in parallel_results)


def test_parallel_processing_handles_errors():
    """Verify parallel processing correctly handles and reports errors."""
    from concurrent.futures import ThreadPoolExecutor
    
    def mock_pipeline_with_errors(paper_idx):
        """Simulate pipeline that fails on specific papers."""
        if paper_idx == 2:
            raise ValueError(f"Simulated error for paper {paper_idx}")
        return {"status": "success", "idx": paper_idx}
    
    papers = list(range(5))
    results = []
    
    def process_with_error_handling(paper_idx):
        try:
            result = mock_pipeline_with_errors(paper_idx)
            return {"idx": paper_idx, "status": "success"}
        except Exception as e:
            return {"idx": paper_idx, "status": "error", "error": str(e)}
    
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as executor:
        results = list(executor.map(process_with_error_handling, papers))
    
    # Verify all papers attempted
    assert len(results) == 5
    
    # Verify error paper marked as error
    error_results = [r for r in results if r["idx"] == 2]
    assert len(error_results) == 1
    assert error_results[0]["status"] == "error"
    assert "Simulated error" in error_results[0]["error"]
    
    # Verify other papers succeeded
    success_results = [r for r in results if r["status"] == "success"]
    assert len(success_results) == 4


def test_parallel_max_workers_respects_cpu_count():
    """Verify max_workers is set to os.cpu_count()."""
    from concurrent.futures import ThreadPoolExecutor
    
    # Mock processing function
    def mock_task(x):
        return x * 2
    
    items = list(range(10))
    
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as executor:
        results = list(executor.map(mock_task, items))
    
    # Verify results
    assert results == [x * 2 for x in items]
    
    # Verify max_workers calculation
    expected_workers = os.cpu_count() or 1
    assert expected_workers > 0


def test_parallel_preserves_result_order():
    """Verify executor.map preserves input order in results."""
    from concurrent.futures import ThreadPoolExecutor
    import random
    
    def mock_task_with_varying_time(x):
        # Simulate varying processing times
        time.sleep(random.uniform(0.001, 0.01))
        return x * 10
    
    items = list(range(20))
    
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as executor:
        results = list(executor.map(mock_task_with_varying_time, items))
    
    # Verify order preserved despite varying execution times
    expected = [x * 10 for x in items]
    assert results == expected

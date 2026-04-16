# -*- coding: utf-8 -*-
"""Regression tests for P2 optimization: cache dedupe + batch progress."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import volume_analysis_service as vas
from routers import pipeline_router
from models import TaskState, BatchProcessRequest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_volume_analysis_concurrent_refresh_deduplicates_rebuild(tmp_path, monkeypatch) -> None:
    """Concurrent refresh requests for same volume should rebuild analysis only once."""
    batch_root = tmp_path / "batch_output_demo"
    bundle_path = batch_root / "volume_V01" / "volume_bundle_V01.json"
    report_path = batch_root / "batch_logs" / "batch_report_20260415_000000.json"

    _write_json(
        bundle_path,
        {
            "status": "volume_bundle_ready",
            "volume_id": "V01",
            "created_at": "2026-04-15T10:30:00",
            "paper_count": 1,
            "writing_points": [
                {
                    "writing_point_id": "wp001",
                    "source_paper_id": "P0001",
                    "claim": "Laser power improved density.",
                    "relevance_score": 0.9,
                }
            ],
            "figures": [],
            "references": [],
            "stats": {
                "writing_point_count": 1,
                "figure_count": 0,
                "reference_count": 0,
            },
        },
    )
    _write_json(
        report_path,
        {
            "start_time": "2026-04-15T10:25:00",
            "pdf_folder": str(tmp_path / "papers"),
            "output_root": batch_root.name,
            "goal": "Conclusion Extraction",
            "batch_size": 13,
            "total_pdfs": 1,
            "successful_pdfs": 1,
            "failed_pdfs": 0,
            "status": "completed",
        },
    )

    monkeypatch.setattr(vas, "REPO_ROOT", tmp_path)

    call_counter = {"count": 0}

    class _DummyIndexBuilder:
        def export_to_file(self, path: Path) -> None:
            _write_json(path, {"statistics": {"global_entities": 1}})

    class _DummyAnalyzer:
        def __init__(self) -> None:
            self.index_builder = _DummyIndexBuilder()

        async def analyze_volume_bundle(self, _bundle: dict, _bundle_path: Path) -> dict:
            call_counter["count"] += 1
            await asyncio.sleep(0.02)
            return {
                "conflict_analysis": {
                    "parameter_consensus": {"power": "divergent"},
                    "high_conflict_parameters": [
                        {
                            "parameter": "power",
                            "conflict_level": "high",
                            "unique_claims": 2,
                            "paper_count": 1,
                            "papers": ["P0001"],
                            "claims": [
                                {
                                    "text": "power rises",
                                    "source_papers": ["P0001"],
                                }
                            ],
                        }
                    ],
                    "consensus_parameters": [],
                },
                "technology_trends": {
                    "parameter_trends": {
                        "power": {
                            "consensus": False,
                            "trend": "mixed",
                            "papers_count": 1,
                            "representative_claim": "power rises",
                            "claim_variants": 1,
                        }
                    }
                },
            }

    monkeypatch.setattr(vas, "CrossPaperAnalyzer", _DummyAnalyzer)

    volume_key = vas.list_volume_summaries()[0]["volume_key"]

    async def run_twice() -> None:
        await asyncio.gather(
            vas.get_volume_analysis(volume_key, refresh=True),
            vas.get_volume_analysis(volume_key, refresh=True),
        )

    asyncio.run(run_twice())
    assert call_counter["count"] == 1


def test_batch_processing_task_passes_progress_callback(monkeypatch) -> None:
    """Batch task should pass a progress callback into BatchProcessController."""
    async def run_test() -> dict[str, object]:
        captured: dict[str, object] = {}

        def fake_create_task(coro):
            captured["coro"] = coro
            return object()

        class DummyController:
            def __init__(
                self,
                pdf_folder: str,
                output_root: str,
                goal: str,
                batch_size: int,
                enable_llm: bool,
                progress_callback,
            ) -> None:
                _ = (pdf_folder, output_root, goal, batch_size, enable_llm)
                self.progress_callback = progress_callback

            def process_batch(self) -> dict:
                self.progress_callback(0.25, "Scanning PDFs")
                self.progress_callback(0.85, "Merging volumes")
                return {
                    "status": "completed",
                    "total_pdfs": 4,
                    "successful_pdfs": 4,
                    "failed_pdfs": 0,
                }

        monkeypatch.setattr("batch_controller.BatchProcessController", DummyController)
        monkeypatch.setattr(pipeline_router.asyncio, "create_task", fake_create_task)

        request = BatchProcessRequest(
            pdf_folder="C:/tmp/pdfs",
            output_root="C:/tmp/out",
            goal="demo",
            batch_size=13,
        )
        submit_response = await pipeline_router.submit_batch_processing(request)
        task_id = submit_response.task_id

        assert submit_response.status == TaskState.queued.value
        assert "coro" in captured

        await captured["coro"]

        # Ensure timestamp field looks sane after async task lifecycle.
        now = time.time()

        async with pipeline_router.TASKS_LOCK:
            payload = dict(pipeline_router.TASKS[task_id])
            assert float(payload.get("updated_at", 0.0)) <= now + 5
            return payload

    payload = asyncio.run(run_test())
    assert payload["status"] == TaskState.succeeded.value
    assert payload["progress"] == 100.0
    assert payload["stage"] == "Completed"

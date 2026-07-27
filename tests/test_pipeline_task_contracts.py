"""Behavior contracts for background pipeline task state transitions."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Generator
from typing import Any

import pytest

from models import BatchProcessRequest, PipelineRequest, TaskState
from routers import pipeline_router


@pytest.fixture(autouse=True)
def restore_pipeline_task_state() -> Generator[None, None, None]:
    """Keep module-level task registries isolated from neighboring tests."""

    previous_tasks = dict(pipeline_router.TASKS)
    previous_background_tasks = dict(pipeline_router.BACKGROUND_TASKS)
    try:
        yield
    finally:
        pipeline_router.TASKS.clear()
        pipeline_router.TASKS.update(previous_tasks)
        pipeline_router.BACKGROUND_TASKS.clear()
        pipeline_router.BACKGROUND_TASKS.update(previous_background_tasks)


def _seed_batch_task(task_id: str) -> None:
    pipeline_router.TASKS[task_id] = {
        "status": TaskState.queued.value,
        "progress": 0.0,
        "stage": "queued",
        "result": None,
        "error": None,
        "updated_at": pipeline_router._now_ts(),
    }
    pipeline_router.BACKGROUND_TASKS[task_id] = object()


@pytest.mark.parametrize(
    ("invalid_report", "expected_error"),
    [
        (["not", "a", "mapping"], "batch controller must return a mapping"),
        ({1: "non-string key"}, "batch controller returned a non-string key"),
    ],
)
def test_batch_task_rejects_invalid_report_shape(
    monkeypatch: pytest.MonkeyPatch,
    invalid_report: object,
    expected_error: str,
) -> None:
    class DummyController:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def process_batch(self) -> object:
            return invalid_report

    monkeypatch.setattr(
        "literature_assistant.core.batch_controller.BatchProcessController",
        DummyController,
    )

    task_id = f"batch-invalid-{type(invalid_report).__name__}"
    _seed_batch_task(task_id)
    asyncio.run(
        pipeline_router._run_batch_processing_task(
            task_id,
            "C:/tmp/pdfs",
            "C:/tmp/out",
            "demo",
        )
    )
    payload = dict(pipeline_router.TASKS[task_id])

    assert payload["status"] == TaskState.failed.value
    assert payload["progress"] == 0.0
    assert payload["stage"] == "Failed"
    assert payload["result"] is None
    assert payload["error"] == expected_error
    assert task_id not in pipeline_router.BACKGROUND_TASKS


def test_pipeline_task_cancel_marks_queued_task_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_test() -> tuple[str, dict[str, Any]]:
        captured_coroutine: Coroutine[Any, Any, None] | None = None

        class DummyBackgroundTask:
            def __init__(self) -> None:
                self.cancelled = False

            def cancel(self) -> None:
                self.cancelled = True

        dummy_task = DummyBackgroundTask()

        def fake_create_task(
            coroutine: Coroutine[Any, Any, None],
        ) -> DummyBackgroundTask:
            nonlocal captured_coroutine
            captured_coroutine = coroutine
            return dummy_task

        monkeypatch.setattr(pipeline_router.asyncio, "create_task", fake_create_task)

        request = BatchProcessRequest(
            pdf_folder="C:/tmp/pdfs",
            output_root="C:/tmp/out",
            goal="demo",
            batch_size=13,
        )
        submit_response = await pipeline_router.submit_batch_processing(request)
        cancel_response = await pipeline_router.cancel_pipeline_task(
            submit_response.task_id
        )

        assert captured_coroutine is not None
        captured_coroutine.close()
        assert dummy_task.cancelled is True
        assert cancel_response.status == TaskState.cancelled.value
        assert cancel_response.stage == "cancelled"
        return submit_response.task_id, dict(
            pipeline_router.TASKS[submit_response.task_id]
        )

    task_id, payload = asyncio.run(run_test())
    assert payload["status"] == TaskState.cancelled.value
    assert payload["stage"] == "cancelled"
    assert task_id not in pipeline_router.BACKGROUND_TASKS


@pytest.mark.parametrize("worker_raises", [False, True])
def test_running_pipeline_cancel_stays_nonterminal_until_worker_exits(
    monkeypatch: pytest.MonkeyPatch,
    worker_raises: bool,
) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    def blocking_pipeline(request: PipelineRequest) -> dict[str, Any]:
        del request
        worker_started.set()
        if not release_worker.wait(timeout=5):
            raise TimeoutError("test worker was not released")
        worker_finished.set()
        if worker_raises:
            raise RuntimeError("pipeline failed after cancellation was requested")
        return {"status": "completed"}

    monkeypatch.setattr(pipeline_router, "_run_pipeline_sync", blocking_pipeline)

    async def run_test() -> None:
        handle: asyncio.Task[None] | None = None
        try:
            submitted = await pipeline_router.run_pipeline_async_endpoint(
                PipelineRequest(input_path="paper.pdf", goal="demo")
            )
            handle = pipeline_router.BACKGROUND_TASKS[submitted.task_id]
            assert await asyncio.to_thread(worker_started.wait, 3)

            cancellation = await pipeline_router.cancel_pipeline_task(
                submitted.task_id
            )

            assert cancellation.status == TaskState.running.value
            assert cancellation.stage == "cancellation_requested"
            assert worker_finished.is_set() is False
            assert submitted.task_id in pipeline_router.BACKGROUND_TASKS

            release_worker.set()
            await handle

            final = await pipeline_router.get_pipeline_task_status(submitted.task_id)
            assert final.status == TaskState.cancelled.value
            assert final.stage == "cancelled"
            assert final.result is None
            assert worker_finished.is_set() is True
            assert submitted.task_id not in pipeline_router.BACKGROUND_TASKS
        finally:
            release_worker.set()
            if handle is not None and not handle.done():
                await asyncio.gather(handle, return_exceptions=True)

    asyncio.run(run_test())


@pytest.mark.parametrize("worker_raises", [False, True])
def test_running_batch_cancel_stays_nonterminal_until_worker_exits(
    monkeypatch: pytest.MonkeyPatch,
    worker_raises: bool,
) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    class BlockingBatchController:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def process_batch(self) -> dict[str, Any]:
            worker_started.set()
            if not release_worker.wait(timeout=5):
                raise TimeoutError("test worker was not released")
            worker_finished.set()
            if worker_raises:
                raise RuntimeError("batch failed after cancellation was requested")
            return {"processed": 1}

    monkeypatch.setattr(
        "literature_assistant.core.batch_controller.BatchProcessController",
        BlockingBatchController,
    )

    async def run_test() -> None:
        handle: asyncio.Task[None] | None = None
        try:
            submitted = await pipeline_router.submit_batch_processing(
                BatchProcessRequest(
                    pdf_folder="C:/tmp/pdfs",
                    output_root="C:/tmp/out",
                    goal="demo",
                )
            )
            handle = pipeline_router.BACKGROUND_TASKS[submitted.task_id]
            assert await asyncio.to_thread(worker_started.wait, 3)

            cancellation = await pipeline_router.cancel_pipeline_task(
                submitted.task_id
            )

            assert cancellation.status == TaskState.running.value
            assert cancellation.stage == "cancellation_requested"
            assert worker_finished.is_set() is False
            assert submitted.task_id in pipeline_router.BACKGROUND_TASKS

            release_worker.set()
            await handle

            final = await pipeline_router.get_pipeline_task_status(submitted.task_id)
            assert final.status == TaskState.cancelled.value
            assert final.stage == "cancelled"
            assert final.result is None
            assert worker_finished.is_set() is True
            assert submitted.task_id not in pipeline_router.BACKGROUND_TASKS
        finally:
            release_worker.set()
            if handle is not None and not handle.done():
                await asyncio.gather(handle, return_exceptions=True)

    asyncio.run(run_test())

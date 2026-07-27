from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import pytest

from harness_protocols import JobKind, SessionMode
from terminal_output import (
    ColorLogFormatter,
    TaskConsoleFormatter,
    install_color_console_formatter,
    progress_bar,
    project_task_metrics,
    sanitize_task_value,
)
from writing_runtime import WritingRuntime


def _record(*, message: str = "runtime message", scholar_task: object | None = None) -> logging.LogRecord:
    """Build a real log record with a stable local timestamp."""

    record = logging.LogRecord(
        name="WritingRuntime",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.created = datetime(2026, 7, 23, 18, 0, 0).timestamp()
    record.msecs = 0.0
    if scholar_task is not None:
        record.scholar_task = scholar_task
    return record


def test_task_console_formatter_emits_fixed_plain_text_block() -> None:
    """Structured task records render as one stable, human-readable block."""

    formatter = TaskConsoleFormatter("%(levelname)s %(name)s %(message)s", stream=io.StringIO())
    record = _record(
        scholar_task={
            "task_type": "resource_ingest",
            "status": "in_progress",
            "title": "paper.pdf",
            "batch_index": 2,
            "batch_total": 9,
            "stage": "extract",
            "progress": 50,
            "message": "正在提取正文",
            "metrics": {"chunks": 120, "content_length": 45000},
            "task_id": "job_fixture",
        }
    )

    assert formatter.format(record) == "\n".join(
        (
            "┌─ 任务类型：文献导入",
            "│ 时间：2026-07-23 18:00:00",
            "│ 状态：处理中",
            "│ 文献：paper.pdf",
            "│ 批次：2 / 9",
            "│ 阶段：提取全文",
            "│ 进度：[############------------]  50%",
            "│ 详情：正在提取正文",
            "│ 结果：检索片段 120；文本字符 45,000",
            "└─ 任务编号：job_fixture",
        )
    )


def test_indeterminate_progress_uses_plain_human_readable_text() -> None:
    """Unknown progress stays legible in Windows consoles and redirected logs."""

    assert progress_bar(None) == "[------------------------] 等待更新"


def test_task_console_formatter_sanitizes_untrusted_values() -> None:
    """Task blocks remove controls, credentials, paths, and unbounded values."""

    formatter = TaskConsoleFormatter("%(message)s", stream=io.StringIO())
    record = _record(
        scholar_task={
            "task_type": "resource_ingest\r\nforged",
            "status": "failed",
            "title": "\x1b[31mC:\\Users\\example-user\\private\\paper.pdf\x1b[0m",
            "stage": "extract_text\nforged",
            "message": (
                "Authorization: Bearer super-secret-token\r\n"
                "api_key=sk-live-secret client_secret=client-private "
                "token=token-private access_token=access-private password=pwd-private "
                "/home/example-user/private/source.pdf /secret /tmp "
                + "x" * 1000
            ),
            "metrics": {
                "chunks": "5\r\nforged",
                "content_length": 1000,
                "secret": "must-not-render",
            },
            "task_id": "job\r\nforged",
            "unknown": "must-not-render",
        }
    )

    output = formatter.format(record)

    assert "\x1b" not in output
    assert "\r" not in output
    assert "super-secret-token" not in output
    assert "sk-live-secret" not in output
    assert "client-private" not in output
    assert "token-private" not in output
    assert "access-private" not in output
    assert "pwd-private" not in output
    assert "C:\\Users\\example-user\\private\\paper.pdf" not in output
    assert "/home/example-user/private/source.pdf" not in output
    assert "/secret" not in output
    assert "/tmp" not in output
    assert "must-not-render" not in output
    assert "[凭据已隐藏]" in output
    assert "[路径已隐藏]" in output
    assert "\nforged" not in output
    assert len(output) < 1800


@pytest.mark.parametrize(
    "value",
    (
        '{"api_key": "TOPSECRET"}',
        "{'client_secret': 'TOPSECRET2'}",
        'api_key="TOP SECRET VALUE"',
        "Authorization: Bearer bearer-private",
        "Bearer standalone-private",
    ),
)
def test_sanitize_task_value_redacts_credential_assignments(value: str) -> None:
    """Credential assignments and bearer values are removed without leaking values."""

    output = sanitize_task_value(value)

    assert "TOPSECRET" not in output
    assert "TOPSECRET2" not in output
    assert "TOP SECRET VALUE" not in output
    assert "bearer-private" not in output
    assert "standalone-private" not in output
    assert "[凭据已隐藏]" in output


@pytest.mark.parametrize(
    ("value", "secret"),
    (
        ("OPENAI_API_KEY=TOPSECRET", "TOPSECRET"),
        ('{"OPENAI_API_KEY":"TOPSECRETJSON"}', "TOPSECRETJSON"),
        ("DATABASE_PASSWORD=database-private", "database-private"),
        ("MY_ACCESS_TOKEN=access-private", "access-private"),
    ),
)
def test_sanitize_task_value_redacts_provider_prefixed_credentials(value: str, secret: str) -> None:
    """Provider-prefixed env and JSON credential keys never expose their values."""

    output = sanitize_task_value(value)

    assert secret not in output
    assert "[凭据已隐藏]" in output


@pytest.mark.parametrize(
    "value",
    ("tokenizer completed", "secretary assigned", "token budget 2048"),
)
def test_sanitize_task_value_preserves_credential_like_prose(value: str) -> None:
    """Credential key fragments and unassigned prose remain unchanged."""

    assert sanitize_task_value(value) == value


def test_project_task_metrics_preserves_approved_metrics_and_canonicalizes_chunks() -> None:
    """Shared metric projection keeps legacy counters and emits chunks once."""

    assert project_task_metrics(
        {
            "chunks": 12,
            "total_chunks": 99,
            "content_length": 45000,
            "indexed": 10,
            "skipped": 2,
            "failed": 1,
            "asset_count": 3,
            "candidate_count": 4,
            "evidence_count": 5,
            "citation_count": 6,
            "unknown": 7,
            "boolean": True,
        }
    ) == {
        "chunks": 12,
        "content_length": 45000,
        "indexed": 10,
        "skipped": 2,
        "failed": 1,
        "asset_count": 3,
        "candidate_count": 4,
        "evidence_count": 5,
        "citation_count": 6,
    }

    assert project_task_metrics({"total_chunks": 8}) == {"chunks": 8}
    assert project_task_metrics({"chunks": -1, "indexed": "2", "failed": True}) == {}


@pytest.mark.parametrize("invalid_chunks", (-1, True, 1_000_000_000_000))
def test_project_task_metrics_falls_back_from_invalid_chunks(invalid_chunks: object) -> None:
    """A valid compatibility chunk total survives an invalid canonical value."""

    assert project_task_metrics({"chunks": invalid_chunks, "total_chunks": 8}) == {"chunks": 8}


def test_task_console_formatter_renders_canonical_metrics_without_duplicates() -> None:
    """Formatter keeps legacy approved metrics and does not repeat chunk totals."""

    formatter = TaskConsoleFormatter("%(message)s", stream=io.StringIO())
    output = formatter.format(
        _record(
            scholar_task={
                "task_type": "resource_ingest",
                "status": "in_progress",
                "metrics": {"chunks": 12, "total_chunks": 99, "indexed": 10, "skipped": 2},
                "task_id": "job_fixture",
            }
        )
    )

    assert output.count("检索片段") == 1
    assert "检索片段 12" in output
    assert "已索引 10" in output
    assert "已跳过 2" in output


@pytest.mark.parametrize(
    ("stage", "label"),
    (("read_source", "读取文献"), ("extract", "提取全文"), ("index", "建立索引")),
)
def test_task_console_formatter_maps_ingestion_stages(stage: str, label: str) -> None:
    """Actual ingestion stage keys render with stable Chinese labels."""

    formatter = TaskConsoleFormatter("%(message)s", stream=io.StringIO())

    output = formatter.format(
        _record(
            scholar_task={
                "task_type": "resource_ingest",
                "status": "in_progress",
                "stage": stage,
                "task_id": "job_fixture",
            }
        )
    )

    assert f"│ 阶段：{label}" in output


def test_task_console_formatter_delegates_plain_records_to_existing_format() -> None:
    """Ordinary records retain the established one-line console shape."""

    formatter = TaskConsoleFormatter("%(levelname)s %(name)s %(message)s", stream=io.StringIO())

    assert formatter.format(_record(message="ordinary event")) == "INFO WritingRuntime ordinary event"
    assert formatter.format(_record(message="ordinary event", scholar_task=["not", "a", "mapping"])) == (
        "INFO WritingRuntime ordinary event"
    )


def test_install_formatter_leaves_file_handlers_unchanged(tmp_path: Path) -> None:
    """Task block formatting is installed only on console stream handlers."""

    root_logger = logging.getLogger()
    original_formatters = {handler: handler.formatter for handler in root_logger.handlers}
    console_handler = logging.StreamHandler(io.StringIO())
    file_handler = logging.FileHandler(tmp_path / "backend.log", encoding="utf-8")
    original_file_formatter = ColorLogFormatter("FILE %(message)s", stream=file_handler.stream)
    file_handler.setFormatter(original_file_formatter)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    try:
        install_color_console_formatter("%(levelname)s %(message)s")

        assert isinstance(console_handler.formatter, TaskConsoleFormatter)
        assert file_handler.formatter is original_file_formatter
        assert not isinstance(file_handler.formatter, TaskConsoleFormatter)
    finally:
        for handler, formatter in original_formatters.items():
            handler.setFormatter(formatter)
        root_logger.removeHandler(console_handler)
        root_logger.removeHandler(file_handler)
        file_handler.close()


@pytest.mark.asyncio
async def test_writing_runtime_attaches_safe_task_context_without_changing_messages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Lifecycle logs expose bounded display context without sensitive job state."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(mode=SessionMode.HYBRID, metadata={"project_id": "private-project"})
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PIPELINE_RUN,
        input_text="private prompt body",
        action_id="resource.scan",
        metadata={
            "source": "resource_ingest",
            "filename": "paper.pdf",
            "batch_id": "batch-private",
            "batch_index": 2,
            "batch_total": 3,
            "source_path": r"C:\Users\example-user\private\paper.pdf",
            "project_id": "private-project",
        },
    )

    with caplog.at_level(logging.INFO, logger=runtime._logger.name):
        await runtime.start_job(job.job_id)
        runtime.emit_job_progress(
            job.job_id,
            stage="extract_text",
            message="Extracting text",
            progress=50,
            data={
                "total_chunks": 7,
                "content_length": 4096,
                "indexed": 6,
                "path": r"C:\Users\example-user\private\paper.pdf",
                "result": "private result body",
            },
        )
        await runtime.complete_job(job.job_id, result="private result body")

    task_records = [record for record in caplog.records if hasattr(record, "scholar_task")]
    assert [record.getMessage() for record in task_records] == [
        f"Started job {job.job_id}",
        f"[任务进度] job={job.job_id} stage=extract_text [############------------]  50% Extracting text (indexed=6, total_chunks=7, content_length=4096)",
        f"Completed job {job.job_id}",
    ]
    assert [record.scholar_task["status"] for record in task_records] == [
        "started",
        "in_progress",
        "completed",
    ]
    assert task_records[0].scholar_task["stage"] == "prepare"
    assert task_records[0].scholar_task["progress"] == 0
    assert task_records[0].scholar_task["message"] == "任务已开始"
    assert task_records[2].scholar_task["stage"] == "completed"
    assert task_records[2].scholar_task["progress"] == 100
    assert task_records[2].scholar_task["message"] == "任务已完成"
    for record in task_records:
        task = record.scholar_task
        assert task["task_type"] == "resource_ingest"
        assert task["title"] == "paper.pdf"
        assert task["batch_index"] == 2
        assert task["batch_total"] == 3
        assert task["task_id"] == job.job_id
        assert task["action"] == "resource.scan"
        assert set(task) <= {
            "task_type",
            "status",
            "title",
            "batch_index",
            "batch_total",
            "stage",
            "progress",
            "message",
            "metrics",
            "task_id",
            "action",
        }
        serialized = repr(task)
        assert session.session_id not in serialized
        assert "private-project" not in serialized
        assert "private prompt body" not in serialized
        assert r"C:\Users\example-user\private\paper.pdf" not in serialized
        assert "private result body" not in serialized

    assert task_records[1].scholar_task["metrics"] == {
        "chunks": 7,
        "content_length": 4096,
        "indexed": 6,
    }


@pytest.mark.asyncio
async def test_writing_runtime_completion_projects_final_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A completed task block reports final chunk and text totals when available."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(mode=SessionMode.PROMPT)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.PIPELINE_RUN,
        metadata={"source": "resource_ingest", "filename": "paper.pdf"},
    )

    with caplog.at_level(logging.INFO, logger=runtime._logger.name):
        await runtime.complete_job(
            job.job_id,
            result={"chunks": 86, "content_length": 14_413, "private": "must-not-render"},
        )

    task_record = next(record for record in caplog.records if hasattr(record, "scholar_task"))
    assert task_record.scholar_task["metrics"] == {
        "chunks": 86,
        "content_length": 14_413,
    }
    assert "must-not-render" not in repr(task_record.scholar_task)


@pytest.mark.asyncio
async def test_writing_runtime_ignores_legacy_batch_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Only canonical batch_index and batch_total metadata reach task logs."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(mode=SessionMode.HYBRID)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.RESOURCE_INGEST,
        metadata={"batch_id": 7, "index": 2, "total": 9},
    )

    with caplog.at_level(logging.INFO, logger=runtime._logger.name):
        await runtime.start_job(job.job_id)

    task_record = next(record for record in caplog.records if hasattr(record, "scholar_task"))
    assert "batch_index" not in task_record.scholar_task
    assert "batch_total" not in task_record.scholar_task


@pytest.mark.asyncio
async def test_writing_runtime_failure_log_exposes_only_bounded_error_detail() -> None:
    """Failure display context includes the error but never unrelated job bodies."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(mode=SessionMode.PROMPT)
    job = runtime.create_job(
        session_id=session.session_id,
        kind=JobKind.SMART_READ,
        input_text="private prompt body",
        action_id="client_secret=client-private /tmp",
        metadata={
            "title": "\x1b[31mapi_key=title-private /secret\x1b[0m",
            "batch_index": -1,
            "batch_total": "not-an-integer",
        },
    )
    error = "api_key=sk-live-secret at C:\\Users\\example-user\\private\\source.pdf " + "x" * 1000

    records: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    capture_handler = _CaptureHandler()
    previous_level = runtime._logger.level
    previous_propagate = runtime._logger.propagate
    runtime._logger.addHandler(capture_handler)
    runtime._logger.setLevel(logging.INFO)
    runtime._logger.propagate = False
    try:
        await runtime.fail_job(job.job_id, error)
    finally:
        runtime._logger.removeHandler(capture_handler)
        runtime._logger.setLevel(previous_level)
        runtime._logger.propagate = previous_propagate

    task_record = next(record for record in records if hasattr(record, "scholar_task"))
    assert task_record.msg == "Failed job %s: %s"
    assert task_record.args[0] == job.job_id
    assert task_record.getMessage().startswith(f"Failed job {job.job_id}: ")
    assert task_record.scholar_task["status"] == "failed"
    assert "sk-live-secret" not in task_record.scholar_task["message"]
    assert r"C:\Users\example-user\private\source.pdf" not in task_record.scholar_task["message"]
    assert len(task_record.scholar_task["message"]) <= 320
    assert "title-private" not in repr(task_record.scholar_task)
    assert "client-private" not in repr(task_record.scholar_task)
    assert "/secret" not in repr(task_record.scholar_task)
    assert "/tmp" not in repr(task_record.scholar_task)
    assert "batch_index" not in task_record.scholar_task
    assert "batch_total" not in task_record.scholar_task
    assert "input_text" not in task_record.scholar_task


@pytest.mark.asyncio
async def test_writing_runtime_rejects_invalid_terminal_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Structured progress metrics accept only bounded non-negative integers."""

    runtime = WritingRuntime(autosave=False)
    session = runtime.create_session(mode=SessionMode.HYBRID)
    job = runtime.create_job(session_id=session.session_id, kind=JobKind.RESOURCE_INGEST)

    with caplog.at_level(logging.INFO, logger=runtime._logger.name):
        runtime.emit_job_progress(
            job.job_id,
            stage="index",
            message="Indexing",
            data={"chunks": -1, "content_length": "45000"},
        )

    task_record = next(record for record in caplog.records if hasattr(record, "scholar_task"))
    assert "metrics" not in task_record.scholar_task

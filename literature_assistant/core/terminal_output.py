# -*- coding: utf-8 -*-
"""Terminal presentation helpers for human-readable local desktop logs."""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Mapping
from typing import TextIO


_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_.-])
    (?P<key_quote>["']?)
    [A-Za-z0-9_.-]{0,64}
    (?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|token|secret)\b
    (?P=key_quote)\s*[:=]\s*
    (?:"(?:[^"\\\r\n]|\\.)*"|'(?:[^'\\\r\n]|\\.)*'|[^\s,;}\]]+)
    '''
)
_BEARER_CREDENTIAL_RE = re.compile(
    r'''(?ix)
    \b(?:authorization\s*:\s*)?bearer\b\s+
    (?:"(?:[^"\\\r\n]|\\.)*"|'(?:[^'\\\r\n]|\\.)*'|[^\s,;]+)
    '''
)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?i)(?<![\w])(?:[a-z]:\\|\\\\)[^\s\"'<>|]+")
_POSIX_ABSOLUTE_PATH_RE = re.compile(r"(?<![\w])/(?:[^/\s\"'<>|]+/)*[^/\s\"'<>|]+")
_RESET = "\x1b[0m"
_STYLES: dict[str, str] = {
    "dim": "\x1b[2m",
    "info": "\x1b[36m",
    "ok": "\x1b[32m",
    "warn": "\x1b[33m",
    "error": "\x1b[31m",
    "accent": "\x1b[35m",
    "progress": "\x1b[34m",
}
_TASK_FIELD_LIMIT = 320
_TASK_TYPE_LABELS: dict[str, str] = {
    "prompt_action": "文本处理",
    "skill_action": "技能任务",
    "pipeline_run": "文档处理",
    "approval": "审批任务",
    "artifact_export": "成果导出",
    "smart_read": "智能阅读",
    "discussion": "多智能体讨论",
    "ai_review": "AI 审阅",
    "figure_load": "图表加载",
    "agent_request": "代理任务",
    "resource_ingest": "文献导入",
}
_TASK_STATUS_LABELS: dict[str, str] = {
    "created": "已创建",
    "queued": "排队中",
    "started": "已开始",
    "paused": "已暂停",
    "in_progress": "处理中",
    "approval_pending": "等待审批",
    "approval_rejected": "审批拒绝",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}
_TASK_STAGE_LABELS: dict[str, str] = {
    "queued": "排队等待",
    "prepare": "准备",
    "read_source": "读取文献",
    "extract": "提取全文",
    "extract_text": "文本提取",
    "chunk_text": "文本分块",
    "index": "建立索引",
    "persist": "保存结果",
    "agent_handoff": "代理交接",
    "completed": "完成",
}
_TASK_METRIC_LABELS: dict[str, str] = {
    "chunks": "检索片段",
    "content_length": "文本字符",
    "indexed": "已索引",
    "skipped": "已跳过",
    "failed": "失败数量",
    "asset_count": "资源数量",
    "candidate_count": "候选数量",
    "evidence_count": "证据数量",
    "citation_count": "引文数量",
}
_TASK_METRIC_KEYS = (
    "chunks",
    "content_length",
    "indexed",
    "skipped",
    "failed",
    "asset_count",
    "candidate_count",
    "evidence_count",
    "citation_count",
)
_MAX_TASK_BATCH_VALUE = 999_999_999
_MAX_TASK_METRIC_VALUE = 999_999_999_999


def _env_flag(name: str) -> str:
    """Return a normalized environment flag value."""

    return os.environ.get(name, "").strip().lower()


def _enable_windows_virtual_terminal() -> None:
    """Best-effort ANSI enablement for classic Windows consoles."""

    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            if not handle:
                continue
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        return


def terminal_supports_color(stream: TextIO | None = None) -> bool:
    """Return whether ANSI color should be emitted to the given stream.

    Args:
        stream: Output stream being formatted. ``sys.stderr`` is used when
            omitted.

    Returns:
        ``True`` only for interactive streams or explicit ``FORCE_COLOR``.
    """

    if _env_flag("NO_COLOR"):
        return False
    if _env_flag("LITASSIST_COLOR") in {"0", "false", "off", "no"}:
        return False
    if _env_flag("FORCE_COLOR") or _env_flag("LITASSIST_COLOR") in {"1", "true", "on", "yes"}:
        _enable_windows_virtual_terminal()
        return True
    target = stream or sys.stderr
    if os.environ.get("TERM", "").strip().lower() == "dumb":
        return False
    isatty = getattr(target, "isatty", None)
    if callable(isatty) and isatty():
        _enable_windows_virtual_terminal()
        return True
    return False


def strip_ansi(text: str) -> str:
    """Remove ANSI control sequences from terminal text."""

    return _ANSI_RE.sub("", str(text))


def colorize(text: object, style: str, *, stream: TextIO | None = None) -> str:
    """Wrap text in an ANSI style when the target stream supports color."""

    raw = str(text)
    code = _STYLES.get(style)
    if not code or not terminal_supports_color(stream):
        return raw
    return f"{code}{raw}{_RESET}"


def terminal_print(label: str, message: str, *, level: str = "info", stream: TextIO | None = None) -> None:
    """Print a labeled terminal line with optional ANSI color.

    Args:
        label: Short Chinese or ASCII prefix without square brackets.
        message: Human-facing status text.
        level: One of ``info``, ``ok``, ``warn``, ``error``, ``accent``, or
            ``progress``.
        stream: Destination stream. ``sys.stdout`` is used when omitted.
    """

    normalized_label = str(label or "").strip()
    normalized_message = str(message or "").strip()
    if not normalized_label:
        raise ValueError("label must be non-empty")
    if not normalized_message:
        raise ValueError("message must be non-empty")
    target = stream or sys.stdout
    prefix = colorize(f"[{normalized_label}]", level, stream=target)
    print(f"{prefix} {normalized_message}", file=target)


def progress_bar(progress: int | None, *, width: int = 24) -> str:
    """Return a compact percentage progress bar for terminal logs.

    Args:
        progress: Optional percentage. ``None`` returns a readable waiting state.
        width: Number of cells in the bar, from 8 to 48.

    Returns:
        A stable-width string such as ``[########--------] 50%``.
    """

    if not isinstance(width, int):
        raise TypeError("width must be an integer")
    width = max(8, min(48, width))
    if progress is None:
        return f"[{'-' * width}] 等待更新"
    value = max(0, min(100, int(progress)))
    filled = round(width * value / 100)
    return f"[{'#' * filled}{'-' * (width - filled)}] {value:3d}%"


class ColorLogFormatter(logging.Formatter):
    """Logging formatter that colors console lines while preserving text shape."""

    def __init__(self, fmt: str, *, stream: TextIO | None = None) -> None:
        super().__init__(fmt)
        self._stream = stream or sys.stderr

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        if record.levelno >= logging.ERROR:
            return colorize(line, "error", stream=self._stream)
        if record.levelno >= logging.WARNING:
            return colorize(line, "warn", stream=self._stream)
        if record.levelno <= logging.DEBUG:
            return colorize(line, "dim", stream=self._stream)
        logger_name = str(record.name or "")
        message = str(record.getMessage() or "")
        if "[任务进度]" in message:
            return colorize(line, "progress", stream=self._stream)
        if "[文献导入]" in message or logger_name in {"ResourcesRouter", "RuntimeRouter"}:
            return colorize(line, "info", stream=self._stream)
        if "ready" in message.lower() or "就绪" in message or "完成" in message:
            return colorize(line, "ok", stream=self._stream)
        return line


def sanitize_task_value(value: object, *, limit: int = _TASK_FIELD_LIMIT) -> str:
    """Return one bounded terminal-safe value for an untrusted task field.

    Args:
        value: Scalar-like value from structured logging context.
        limit: Maximum output characters, clamped to 16..1024.

    Returns:
        A single-line value with ANSI/control sequences removed, credential
        assignments and absolute paths replaced, and excessive text truncated.
    """

    text = strip_ansi(str(value))
    text = _CONTROL_RE.sub(" ", text)
    text = _CREDENTIAL_ASSIGNMENT_RE.sub("[凭据已隐藏]", text)
    text = _BEARER_CREDENTIAL_RE.sub("[凭据已隐藏]", text)
    text = _WINDOWS_ABSOLUTE_PATH_RE.sub("[路径已隐藏]", text)
    text = _POSIX_ABSOLUTE_PATH_RE.sub("[路径已隐藏]", text)
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return "-"
    bounded_limit = max(16, min(1024, int(limit)))
    if len(normalized) <= bounded_limit:
        return normalized
    return f"{normalized[: bounded_limit - 3]}..."


def _task_label(value: object, labels: Mapping[str, str]) -> str:
    """Map one internal task value to Chinese while preserving safe unknowns."""

    normalized = str(value or "").strip().lower()
    if not normalized:
        return "-"
    return labels.get(normalized, sanitize_task_value(value))


def _task_progress(value: object) -> str:
    """Render a bounded percentage or a safe indeterminate marker."""

    if value is None or isinstance(value, bool):
        return progress_bar(None)
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return progress_bar(None)
    try:
        progress = max(0, min(100, int(value)))
    except (TypeError, ValueError, OverflowError):
        return progress_bar(None)
    return progress_bar(progress)


def _bounded_integer(value: object, *, minimum: int, maximum: int) -> int | None:
    """Return an integer inside explicit display bounds, excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < minimum or value > maximum:
        return None
    return value


def project_task_metrics(value: object) -> dict[str, int]:
    """Project approved task counters into one canonical bounded mapping.

    Args:
        value: Candidate metrics mapping from a logging boundary.

    Returns:
        Approved non-boolean integer metrics in the range 0..999,999,999,999.
        ``total_chunks`` is accepted as a compatibility input and normalized to
        ``chunks``; an explicit valid ``chunks`` value takes precedence.
    """

    if not isinstance(value, Mapping):
        return {}
    projected: dict[str, int] = {}
    normalized_chunks = _bounded_integer(value.get("chunks"), minimum=0, maximum=_MAX_TASK_METRIC_VALUE)
    if normalized_chunks is None:
        normalized_chunks = _bounded_integer(
            value.get("total_chunks"),
            minimum=0,
            maximum=_MAX_TASK_METRIC_VALUE,
        )
    if normalized_chunks is not None:
        projected["chunks"] = normalized_chunks
    for key in _TASK_METRIC_KEYS[1:]:
        normalized = _bounded_integer(value.get(key), minimum=0, maximum=_MAX_TASK_METRIC_VALUE)
        if normalized is not None:
            projected[key] = normalized
    return projected


def _task_batch(task: Mapping[str, object]) -> str:
    """Render optional batch position without accepting arbitrary task fields."""

    index = _bounded_integer(task.get("batch_index"), minimum=1, maximum=_MAX_TASK_BATCH_VALUE)
    total = _bounded_integer(task.get("batch_total"), minimum=1, maximum=_MAX_TASK_BATCH_VALUE)
    if index is None and total is None:
        return "-"
    if index is None:
        return f"- / {total:,}"
    if total is None:
        return f"{index:,}"
    return f"{index:,} / {total:,}"


def _task_metrics(value: object) -> str:
    """Render only approved, bounded task metric values."""

    if not isinstance(value, Mapping):
        return "-"
    parts: list[str] = []
    for key, metric in project_task_metrics(value).items():
        parts.append(f"{_TASK_METRIC_LABELS[key]} {metric:,}")
    return "；".join(parts) if parts else "-"


class TaskConsoleFormatter(ColorLogFormatter):
    """Render approved structured task context as one atomic console block."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one record, delegating non-task records to the existing formatter."""

        task = getattr(record, "scholar_task", None)
        if not isinstance(task, Mapping):
            return super().format(record)

        lines = (
            f"┌─ 任务类型：{_task_label(task.get('task_type'), _TASK_TYPE_LABELS)}",
            f"│ 时间：{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}",
            f"│ 状态：{_task_label(task.get('status'), _TASK_STATUS_LABELS)}",
            f"│ 文献：{sanitize_task_value(task.get('title') or '-')}",
            f"│ 批次：{_task_batch(task)}",
            f"│ 阶段：{_task_label(task.get('stage'), _TASK_STAGE_LABELS)}",
            f"│ 进度：{_task_progress(task.get('progress'))}",
            f"│ 详情：{sanitize_task_value(task.get('message') or '-')}",
            f"│ 结果：{_task_metrics(task.get('metrics'))}",
            f"└─ 任务编号：{sanitize_task_value(task.get('task_id') or '-')}",
        )
        block = "\n".join(lines)
        status = str(task.get("status") or "").strip().lower()
        if record.levelno >= logging.ERROR or status == "failed":
            return colorize(block, "error", stream=self._stream)
        if record.levelno >= logging.WARNING:
            return colorize(block, "warn", stream=self._stream)
        if status == "completed":
            return colorize(block, "ok", stream=self._stream)
        return colorize(block, "progress", stream=self._stream)


def install_color_console_formatter(fmt: str) -> None:
    """Install color formatting on existing console handlers only."""

    if not str(fmt or "").strip():
        raise ValueError("fmt must be non-empty")
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            continue
        if isinstance(handler, logging.StreamHandler):
            stream = getattr(handler, "stream", None)
            handler.setFormatter(TaskConsoleFormatter(fmt, stream=stream))

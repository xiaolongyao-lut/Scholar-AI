# -*- coding: utf-8 -*-
"""Terminal presentation helpers for human-readable local desktop logs."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import TextIO


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
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


def _env_flag(name: str) -> str:
    """Return a normalized environment flag value."""

    return os.environ.get(name, "").strip().lower()


def _enable_windows_virtual_terminal() -> None:
    """Best-effort ANSI enablement for classic Windows consoles."""

    if os.name != "nt":
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
        progress: Optional percentage. ``None`` returns an indeterminate bar.
        width: Number of cells in the bar, from 8 to 48.

    Returns:
        A stable-width string such as ``[########--------] 50%``.
    """

    if not isinstance(width, int):
        raise TypeError("width must be an integer")
    width = max(8, min(48, width))
    if progress is None:
        return f"[{'?' * width}] --%"
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
            handler.setFormatter(ColorLogFormatter(fmt, stream=stream))

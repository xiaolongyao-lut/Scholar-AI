"""
Unified logging configuration for the scoring system

Provides:
- Centralized logger setup
- JSON logging for structured output
- Colored console output
- File rotation
"""

import logging
import logging.handlers
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging"""

    def format(self, record: logging.LogRecord) -> str:
        """Convert log record to JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class ColoredFormatter(logging.Formatter):
    """Format log records with ANSI colors for console output"""

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[41m", # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Add colors to log message"""
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)


def setup_logging(
    log_dir: Optional[str] = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    json_logs: bool = False,
    name: Optional[str] = None,
) -> logging.Logger:
    """
    Setup logging for the application

    Args:
        log_dir: Directory for log files (if None, logging to console only)
        console_level: Logging level for console output
        file_level: Logging level for file output
        json_logs: Whether to output JSON formatted logs to file
        name: Logger name (if None, returns root logger)

    Returns:
        Configured logger instance
    """
    logger_name = name or "scoring_system"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)  # Capture everything, filters apply at handler level

    # Avoid duplicate handlers
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_formatter = ColoredFormatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (if log_dir specified)
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        log_file = log_path / f"{logger_name}.log"

        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_file),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)

        if json_logs:
            file_formatter = JSONFormatter()
        else:
            file_formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(funcName)s:%(lineno)d] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with the given name"""
    return logging.getLogger(name)


# Module-level loggers
root_logger = logging.getLogger("scoring_system")
config_logger = get_logger("scoring_system.config")
classifier_logger = get_logger("scoring_system.classifier")
processor_logger = get_logger("scoring_system.processor")
batch_logger = get_logger("scoring_system.batch")
exporter_logger = get_logger("scoring_system.exporter")


def add_context_to_log(logger: logging.Logger, **context_data):
    """
    Create a logger adapter with context information

    Usage:
        logger = add_context_to_log(logger, paper_id="paper_001", goal="工艺参数")
        logger.info("Processing started")
        # Output: ... paper_id=paper_001, goal=工艺参数 - Processing started
    """
    class ContextFilter(logging.Filter):
        def filter(self, record):
            record.extra_data = context_data
            return True

    logger.addFilter(ContextFilter())
    return logger

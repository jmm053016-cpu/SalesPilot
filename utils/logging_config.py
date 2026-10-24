"""配置统一日志格式、轮转策略，并在输出前脱敏敏感信息。"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOGGER_NAME = "salespilot"
LOG_LEVEL_ENV = "SALESPILOT_LOG_LEVEL"
DEFAULT_LOG_LEVEL = logging.INFO
MAX_EXCEPTION_LENGTH = 500
_HANDLER_MARKER = "_salespilot_handler"
_LOG_ROOT_MARKER = "_salespilot_log_root"

_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}"), "[REDACTED]"),
    (
        re.compile(r"(?i)\b(?:deepseek_api_key|openai_api_key|api_key)\s*[:=]\s*[^\s,;]+"),
        "[REDACTED]",
    ),
    (re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+[^\s,;]+"), "[REDACTED]"),
)


def redact_sensitive(value: object, *, max_length: int = MAX_EXCEPTION_LENGTH) -> str:
    """Return a bounded string with common credentials removed."""
    text = str(value)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:max_length]


def safe_exception_summary(
    exc: BaseException, *, max_length: int = MAX_EXCEPTION_LENGTH
) -> str:
    return redact_sensitive(f"{type(exc).__name__}: {exc}", max_length=max_length)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        safe_record = logging.makeLogRecord(record.__dict__.copy())
        safe_record.msg = redact_sensitive(safe_record.getMessage())
        safe_record.args = ()
        return super().format(safe_record)

    def formatException(self, exc_info) -> str:
        return redact_sensitive(super().formatException(exc_info))

    def formatStack(self, stack_info: str) -> str:
        return redact_sensitive(super().formatStack(stack_info))


def _level_from_env(env: Mapping[str, str]) -> int:
    configured = env.get(LOG_LEVEL_ENV, "INFO").strip().upper()
    level = logging.getLevelName(configured)
    return level if isinstance(level, int) else DEFAULT_LOG_LEVEL


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith(LOGGER_NAME) else f"{LOGGER_NAME}.{name}")


def _remove_salespilot_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()


def configure_logging(
    log_root: Path | str = Path(".runtime/logs"),
    *,
    env: Mapping[str, str] | None = None,
) -> logging.Logger:
    """Configure application logging without blocking startup on file errors."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_level_from_env(os.environ if env is None else env))
    logger.propagate = False
    root = str(Path(log_root).resolve())
    existing_root = getattr(logger, _LOG_ROOT_MARKER, None)
    marked_handlers = [
        handler for handler in logger.handlers if getattr(handler, _HANDLER_MARKER, False)
    ]
    if existing_root == root and marked_handlers:
        for handler in marked_handlers:
            handler.setLevel(logger.level)
        return logger

    _remove_salespilot_handlers(logger)
    formatter = RedactingFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logger.level)
    console_handler.setFormatter(formatter)
    setattr(console_handler, _HANDLER_MARKER, True)
    logger.addHandler(console_handler)

    try:
        Path(log_root).mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            Path(log_root) / "salespilot.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        )
    except (OSError, PermissionError) as exc:
        print(f"SalesPilot 日志文件不可用，已降级为控制台日志：{safe_exception_summary(exc)}")
    else:
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _HANDLER_MARKER, True)
        logger.addHandler(file_handler)
    setattr(logger, _LOG_ROOT_MARKER, root)
    return logger

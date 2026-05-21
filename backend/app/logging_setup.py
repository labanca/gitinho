"""Structured logging with secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.config import Settings

_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(token|secret|api[_-]?key|password|authorization|private[_-]?key|cookie)"
)
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+")
_GH_TOKEN_PATTERN = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = _BEARER_PATTERN.sub(r"\1***", value)
        value = _GH_TOKEN_PATTERN.sub("ghX_***", value)
    return value


def _redact_processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict.keys()):
        if _SECRET_KEY_PATTERN.search(key):
            event_dict[key] = "***"
        else:
            event_dict[key] = _redact(event_dict[key])
    return event_dict


def configure_logging(settings: Settings) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        _redact_processor,
    ]

    if settings.LOG_FORMAT == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL)
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib loggers (uvicorn, sqlalchemy) through structlog.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.LOG_LEVEL,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    return structlog.get_logger(name)

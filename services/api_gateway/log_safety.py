"""
Helpers to keep structured logging safe when values may contain user input.
"""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from types import TracebackType
from typing import Any, Optional

_SAFE_LANGUAGE_CODE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8}){0,2}$")


def sanitize_log_value(value: Any, *, max_length: int = 200) -> Any:
    """Return a log-safe representation without control characters."""
    if isinstance(value, BaseException):
        value = f"{type(value).__name__}: {value}"
    elif isinstance(value, Path):
        value = str(value)

    if isinstance(value, str):
        sanitized = value.replace("\r", "\\r").replace("\n", "\\n")
        if len(sanitized) > max_length:
            return f"{sanitized[:max_length]}...(truncated)"
        return sanitized

    if isinstance(value, dict):
        return {
            str(key): sanitize_log_value(item, max_length=max_length) for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [sanitize_log_value(item, max_length=max_length) for item in value]

    return value


def safe_language_code(value: Any) -> str:
    """Return an allowlisted language tag for logging."""
    if not isinstance(value, str):
        return "invalid"

    normalized = value.strip()
    if not normalized:
        return "missing"

    if not _SAFE_LANGUAGE_CODE.fullmatch(normalized):
        return "invalid"

    return normalized[:32]


def safe_session_ref(session_id: Optional[str]) -> str:
    """A short, stable session handle for log lines.

    Unkeyed, so enumerable: session ids are 32-bit. Anything stored or joined
    beyond a log line belongs in `session_pseudonym` instead.
    """
    if not session_id:
        return "missing"
    return sha256(session_id.encode("utf-8")).hexdigest()[:12]


def safe_closed_value(value: Any, allowed: frozenset[str], *, fallback: str = "invalid") -> str:
    """Keep an operational field fixed-cardinality and free of caller text."""
    return value if isinstance(value, str) and value in allowed else fallback


_REDACTED_EXCEPTION_MESSAGE = "Exception details redacted"


class RedactedServerError(Exception):
    """An unhandled error with its message removed; the traceback is the original's."""


def redacted_exception_info(
    error: BaseException,
) -> tuple[type[BaseException], BaseException, Optional[TracebackType]]:
    """`exc_info` for logging an error without its message, which may carry user content."""
    return (RuntimeError, RuntimeError(_REDACTED_EXCEPTION_MESSAGE), error.__traceback__)

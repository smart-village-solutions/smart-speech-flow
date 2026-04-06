"""
Helpers to keep structured logging safe when values may contain user input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
            str(key): sanitize_log_value(item, max_length=max_length)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [sanitize_log_value(item, max_length=max_length) for item in value]

    return value

"""
Helpers to keep structured logging safe when values may contain user input.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
            str(key): sanitize_log_value(item, max_length=max_length)
            for key, item in value.items()
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

"""The environment settings every Studio client shares."""

from __future__ import annotations

import os


def studio_base_url() -> str:
    """Studio's origin, blank when Studio is not configured."""
    return os.getenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", "").strip()


def seconds_setting(name: str, default: float, maximum: float) -> float:
    """A positive number of seconds up to `maximum`; anything else is the default.

    An unusable value falls back rather than raising: these bound optional reads,
    and a typo must not cost the gateway a route or its startup.
    """
    raw = os.getenv(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if 0 < value <= maximum else default

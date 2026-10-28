"""What a recorded session's refinement telemetry says instead of its languages (spec §5.5)."""

from __future__ import annotations

from typing import Any

from .quality_telemetry import UNDETERMINED_LANGUAGE


def reported_languages(source_lang: str, target_lang: str, context: Any) -> tuple[str, str]:
    """The languages a refinement event names: none for a recorded session."""
    if isinstance(context, dict) and context.get("withhold_languages"):
        return UNDETERMINED_LANGUAGE, UNDETERMINED_LANGUAGE
    return source_lang, target_lang

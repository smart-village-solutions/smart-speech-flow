"""How long a terminated session's record and leftover delivery audio are kept.

Outside a recording nothing of a conversation is kept (spec §5.4): the
terminal record holds metadata only, and it expires after this period.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Final

from .studio_v2 import MAX_RETENTION_HOURS

logger = logging.getLogger(__name__)

TERMINAL_RECORD_HOURS_ENV: Final[str] = "SSF_TERMINAL_RECORD_HOURS"
DEFAULT_TERMINAL_RECORD_HOURS: Final[int] = 24
SESSION_MAX_HOURS_ENV: Final[str] = "SSF_SESSION_MAX_HOURS"
DEFAULT_SESSION_MAX_HOURS: Final[int] = 8
# The hour past the longest session covers a pipeline still finishing at its end.
_DELIVERY_AUDIO_MARGIN_HOURS: Final[int] = 1


def delivery_audio_hours() -> int:
    """Delivery audio older than this belongs to no live session: no session lives longer.

    A session's end deletes its audio; this bounds what an ending missed. Tied to
    the session lifetime, not the terminal record, so neither setting can reach
    a live conversation's audio or keep plaintext longer than a session runs.
    """
    raw = (os.environ.get(SESSION_MAX_HOURS_ENV) or "").strip()
    return _parsed_session_hours(raw) + _DELIVERY_AUDIO_MARGIN_HOURS


@lru_cache(maxsize=8)
def _parsed_session_hours(raw: str) -> int:
    if not raw:
        return DEFAULT_SESSION_MAX_HOURS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if not 0 < value <= MAX_RETENTION_HOURS:
        logger.warning(
            "%s is unusable for the audio cleanup; using %d",
            SESSION_MAX_HOURS_ENV,
            DEFAULT_SESSION_MAX_HOURS,
        )
        return DEFAULT_SESSION_MAX_HOURS
    return value


def terminal_record_hours() -> int:
    """The period, in hours, a terminal record is kept.

    Zero is refused like any other unusable value: a record must not live
    forever. Studio's cap bounds it too, so no cutoff falls out of the calendar.
    """
    return _parsed_terminal_record_hours((os.environ.get(TERMINAL_RECORD_HOURS_ENV) or "").strip())


# Read on every sweep and termination; a bad value is reported once, not each time.
@lru_cache(maxsize=8)
def _parsed_terminal_record_hours(raw: str) -> int:
    if not raw:
        return DEFAULT_TERMINAL_RECORD_HOURS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if not 0 < value <= MAX_RETENTION_HOURS:
        logger.warning(
            "%s must be between 1 and %d hours; using %d",
            TERMINAL_RECORD_HOURS_ENV,
            MAX_RETENTION_HOURS,
            DEFAULT_TERMINAL_RECORD_HOURS,
        )
        return DEFAULT_TERMINAL_RECORD_HOURS
    return value

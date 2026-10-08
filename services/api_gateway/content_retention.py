"""How long a session's conversation content and terminal record are kept.

A session keeps the Studio retention of the live read that granted consent
(Studio v2). Every other session, and one granted before that value was
captured, gets the short terminal-record period.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from .consent import ConsentStatus
from .studio_v2 import MAX_RETENTION_HOURS

if TYPE_CHECKING:
    from .session_models import Session

logger = logging.getLogger(__name__)

TERMINAL_RECORD_HOURS_ENV: Final[str] = "SSF_TERMINAL_RECORD_HOURS"
DEFAULT_TERMINAL_RECORD_HOURS: Final[int] = 24


def terminal_record_hours() -> int:
    """The short period, in hours, for content no granted consent covers.

    Zero is refused like any other unusable value: a record without consented
    content must not live forever. Studio's cap bounds it too, so no cutoff
    falls out of the calendar.
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


def valid_retention_hours(value: object) -> int | None:
    """A stored retention Studio could have sent, or None.

    Beyond Studio's cap a cutoff can fall before year 1 and raise.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_RETENTION_HOURS else None


def captured_retention_hours(session: Session | None) -> int | None:
    """The retention captured with granted consent, or None when there is none."""
    if session is None or session.consent_status is not ConsentStatus.GRANTED:
        return None
    return session.consent_retention_hours


def session_retention_hours(session: Session) -> int:
    """Hours this session's content and terminal record are kept; 0 keeps them."""
    captured = captured_retention_hours(session)
    return terminal_record_hours() if captured is None else captured

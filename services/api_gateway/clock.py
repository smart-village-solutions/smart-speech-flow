"""The gateway's shared `utc_now`, so the helper has one definition (#346)."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

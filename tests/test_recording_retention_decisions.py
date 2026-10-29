"""Retention decisions as the gateway makes them (spec §16.1)."""

from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording.retention.decisions import (
    MAX_EXTENSION,
    ConversationSummary,
    RetentionRefusedError,
    check_extension,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def test_an_extension_must_move_the_date_later():
    with pytest.raises(RetentionRefusedError) as refused:
        check_extension(NOW + timedelta(days=2), NOW + timedelta(days=2), NOW)
    assert refused.value.code == "retention_not_extended"


def test_an_extension_reaches_at_most_a_year_from_now():
    assert MAX_EXTENSION == timedelta(hours=8760)
    check_extension(NOW + MAX_EXTENSION, NOW + timedelta(days=1), NOW)
    with pytest.raises(RetentionRefusedError) as refused:
        check_extension(NOW + MAX_EXTENSION + timedelta(seconds=1), NOW, NOW)
    assert refused.value.code == "retention_too_far"


def test_a_summary_names_no_content():
    summary = ConversationSummary(
        conversation_id="c",
        employee_sub="emp",
        started_at=NOW,
        ended_at=None,
        retention_until=NOW,
        legal_hold=False,
        shredded_at=NOW,
    )
    assert summary.public() == {
        "conversation_id": "c",
        "employee_sub": "emp",
        "started_at": NOW.isoformat(),
        "ended_at": None,
        "retention_until": NOW.isoformat(),
        "legal_hold": False,
        "shredded": True,
    }

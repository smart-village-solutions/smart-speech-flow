"""Which retention governs a session: the one captured with consent, else the short default."""

import pytest

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.content_retention import (
    captured_retention_hours,
    session_retention_hours,
    terminal_record_hours,
)
from services.api_gateway.session_models import Session

REVISION = f"sha256:{'a' * 64}"


@pytest.fixture(autouse=True)
def default_terminal_period(monkeypatch):
    monkeypatch.delenv("SSF_TERMINAL_RECORD_HOURS", raising=False)


def _session(status: ConsentStatus, hours: int | None) -> Session:
    return Session(
        id="SESSION1",
        tenant_id="tenant-a",
        configuration_revision=REVISION,
        consent_status=status,
        consent_retention_hours=hours,
    )


def test_the_terminal_record_period_defaults_to_24_hours():
    assert terminal_record_hours() == 24


def test_the_terminal_record_period_is_configurable(monkeypatch):
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "72")

    assert terminal_record_hours() == 72


@pytest.mark.parametrize("raw", ["", "  ", "x", "0", "-3", "1.5"])
def test_an_unusable_terminal_record_period_falls_back_to_24_hours(monkeypatch, raw):
    # Zero included: a record without consented content must not live forever.
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", raw)

    assert terminal_record_hours() == 24


@pytest.mark.parametrize("hours", [4320, 72, 0])
def test_a_granted_session_uses_its_captured_hours(hours):
    session = _session(ConsentStatus.GRANTED, hours)

    assert captured_retention_hours(session) == hours
    assert session_retention_hours(session) == hours


@pytest.mark.parametrize(
    "status", [ConsentStatus.PENDING, ConsentStatus.DECLINED, ConsentStatus.POLICY_DISABLED]
)
def test_a_session_without_granted_consent_uses_the_short_default(monkeypatch, status):
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "48")
    session = _session(status, 4320)

    assert captured_retention_hours(session) is None
    assert session_retention_hours(session) == 48


def test_a_session_granted_before_capture_existed_uses_the_short_default():
    session = _session(ConsentStatus.GRANTED, None)

    assert captured_retention_hours(session) is None
    assert session_retention_hours(session) == 24


def test_an_unusable_period_is_reported_once_not_on_every_call(monkeypatch, caplog):
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "zero-once")

    with caplog.at_level("WARNING"):
        for _ in range(3):
            assert terminal_record_hours() == 24

    assert caplog.text.count("SSF_TERMINAL_RECORD_HOURS") == 1


@pytest.mark.parametrize("raw", ["8761", "1000000000"])
def test_a_period_beyond_studios_cap_falls_back_to_24_hours(monkeypatch, raw):
    # Past the cap a cutoff can fall before year 1 and stop every cleanup.
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", raw)

    assert terminal_record_hours() == 24


def test_the_cap_itself_is_accepted(monkeypatch):
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "8760")

    assert terminal_record_hours() == 8760


def test_no_session_has_no_captured_retention():
    assert captured_retention_hours(None) is None

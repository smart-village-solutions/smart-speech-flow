"""One configurable period governs authorised audio and authorised text."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.api_gateway import audio_storage
from services.api_gateway.audio_storage import retention_hours
from services.api_gateway.session_manager import (
    ClientType,
    SessionManager,
    SessionMessage,
)
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def test_retention_defaults_to_24_hours(monkeypatch):
    monkeypatch.delenv("SSF_CONTENT_RETENTION_HOURS", raising=False)
    assert retention_hours() == 24


def test_retention_is_configurable(monkeypatch):
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "72")
    assert retention_hours() == 72


def test_zero_disables_automatic_deletion(monkeypatch):
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    assert retention_hours() == 0


@pytest.mark.parametrize("raw", ["", "  ", "not-a-number", "-5"])
def test_invalid_values_fall_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", raw)
    assert retention_hours() == 24


@pytest.fixture
def audio_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    real_delete = audio_storage.delete_message_audio

    def delete(key, message_id, variant, *, base_dir=None):
        return real_delete(key, message_id, variant, base_dir=tmp_path)

    monkeypatch.setattr(audio_storage, "delete_message_audio", delete)
    return tmp_path


@pytest.fixture
def manager() -> SessionManager:
    return SessionManager(store=MemoryTenantSessionStore())


async def _session_aged(manager, *, age: timedelta, authorized: bool):
    session = await manager.create_admin_session("tenant-test", SNAPSHOT)
    session.created_at = NOW - age
    manager.add_message(
        session.key,
        SessionMessage(
            id="m1",
            sender=ClientType.CUSTOMER,
            original_text="hallo",
            translated_text="hello",
            audio_base64=None,
            source_lang="de",
            target_lang="en",
            timestamp=NOW - age,
            record_authorized=authorized,
            original_audio_authorized=authorized,
            translated_audio_authorized=authorized,
        ),
    )
    return session.key


async def test_authorised_text_expires_at_the_retention_boundary(
    manager, audio_dir, monkeypatch
):
    monkeypatch.delenv("SSF_CONTENT_RETENTION_HOURS", raising=False)
    key = await _session_aged(manager, age=timedelta(hours=25), authorized=True)
    manager.sweep_expired_content(NOW)
    assert manager.get_session(key).messages == []


async def test_authorised_text_survives_inside_the_retention_window(
    manager, audio_dir, monkeypatch
):
    monkeypatch.delenv("SSF_CONTENT_RETENTION_HOURS", raising=False)
    key = await _session_aged(manager, age=timedelta(hours=2), authorized=True)
    manager.sweep_expired_content(NOW)
    assert len(manager.get_session(key).messages) == 1


async def test_authorised_text_survives_when_deletion_is_disabled(
    manager, audio_dir, monkeypatch
):
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    key = await _session_aged(manager, age=timedelta(days=30), authorized=True)
    manager.sweep_expired_content(NOW)
    assert len(manager.get_session(key).messages) == 1


async def test_refused_content_in_an_abandoned_session_is_removed(
    manager, audio_dir, monkeypatch
):
    # Disabling automatic deletion must not retain refused content.
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    key = await _session_aged(manager, age=timedelta(hours=9), authorized=False)
    manager.sweep_expired_content(NOW)
    assert manager.get_session(key).messages == []


async def test_refused_content_survives_inside_the_session_lifetime(
    manager, audio_dir, monkeypatch
):
    # Removal belongs to termination; the sweep is the net for what never ends.
    monkeypatch.setenv("SSF_CONTENT_RETENTION_HOURS", "0")
    key = await _session_aged(manager, age=timedelta(hours=2), authorized=False)
    manager.sweep_expired_content(NOW)
    assert len(manager.get_session(key).messages) == 1

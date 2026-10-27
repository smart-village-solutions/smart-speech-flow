"""Recording wires only when its database and secrets are both configured."""

from __future__ import annotations

import base64
import os
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.api_gateway.recording import wiring
from services.api_gateway.recording.ceremony_model import CeremonyError
from services.api_gateway.recording.secrets import BLOB_KEY_FILE_ENV, SIGNING_KEY_FILE_ENV
from services.api_gateway.recording.session_store import MemoryRecordingStateStore

DSN = "postgresql://ssf_recording_app@db/ssf_recording"


@pytest.fixture(autouse=True)
def database_password(monkeypatch):
    monkeypatch.setenv(wiring.RECORDING_PASSWORD_ENV, "test-only-password")


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        recording_keys=None,
        recording_repository=None,
        recording_secrets=None,
        recording_ceremony=None,
        studio_token_provider=None,
        studio_runtime_flow=None,
        recording_state_store=MemoryRecordingStateStore(),
        recording_sessions=None,
        websocket_manager=SimpleNamespace(recording=None),
        session_manager=SimpleNamespace(recording=None),
    )


@pytest.fixture
def secrets_on_disk(tmp_path, monkeypatch):
    signing = tmp_path / "signing-key.pem"
    signing.write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    blob = tmp_path / "blob-key"
    blob.write_text(base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv(SIGNING_KEY_FILE_ENV, str(signing))
    monkeypatch.setenv(BLOB_KEY_FILE_ENV, str(blob))


class _Repository:
    def __init__(self) -> None:
        self.registered: list[str] = []
        self.closed = False

    async def register_gateway_key(self, key_id, public_key, at) -> None:
        self.registered.append(key_id)

    async def record_audit(self, event) -> None:
        pass

    async def active_recovery_key(self, tenant_id):
        return None

    async def close(self) -> None:
        self.closed = True


async def test_no_dsn_or_no_password_leaves_recording_off_without_retrying(monkeypatch):
    state = _state()
    assert await wiring.connect_recording(state, "") is True
    monkeypatch.delenv(wiring.RECORDING_PASSWORD_ENV)
    assert await wiring.connect_recording(state, DSN) is True
    assert state.recording_keys is None


async def test_missing_secrets_leave_recording_off_without_retrying(tmp_path, monkeypatch):
    monkeypatch.setenv(SIGNING_KEY_FILE_ENV, str(tmp_path / "absent"))
    state = _state()
    assert await wiring.connect_recording(state, DSN) is True
    assert state.recording_keys is None


async def test_an_unreachable_database_asks_for_a_retry(secrets_on_disk, monkeypatch):
    async def refuse(**_):
        raise OSError("connection refused")

    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", refuse)
    assert await wiring.connect_recording(_state(), DSN) is False


async def test_a_connected_gateway_registers_its_signing_key(secrets_on_disk, monkeypatch):
    repository = _Repository()

    async def create(**_):
        return repository

    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    state = _state()
    assert await wiring.connect_recording(state, DSN) is True
    assert state.recording_keys is not None
    assert state.recording_ceremony is not None
    assert repository.registered == [state.recording_secrets.signing_key_id]
    sessions = state.recording_sessions
    assert sessions is not None
    assert state.websocket_manager.recording is sessions
    assert state.session_manager.recording is sessions
    await wiring.close_recording(state)
    assert state.recording_sessions is None
    assert state.websocket_manager.recording is None
    assert state.session_manager.recording is None


async def test_without_studio_the_ceremony_cannot_name_custodians(secrets_on_disk, monkeypatch):
    async def create(**_):
        return _Repository()

    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    monkeypatch.delenv("STUDIO_RUNTIME_CONFIGURATION_BASE_URL", raising=False)
    state = _state()
    await wiring.connect_recording(state, DSN)
    with pytest.raises(CeremonyError) as caught:
        await state.recording_ceremony.candidates("tenant-test", "corr")
    assert caught.value.code == "DIRECTORY_UNAVAILABLE"

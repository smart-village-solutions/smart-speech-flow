"""Recording wires only when its database and secrets are both configured."""

from __future__ import annotations

import base64
import json
import os
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from services.api_gateway.recording import wiring
from services.api_gateway.recording.ceremony_model import CeremonyError
from services.api_gateway.recording.secrets import BLOB_KEY_FILE_ENV, SIGNING_KEY_FILE_ENV
from services.api_gateway.recording.session_service import RecordingUnavailableError
from services.api_gateway.recording.session_store import MemoryRecordingStateStore
from services.api_gateway.session_models import SessionStatus

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
        recording_retention=None,
        studio_token_provider=None,
        studio_runtime_flow=None,
        recording_state_store=MemoryRecordingStateStore(),
        recording_sessions=None,
        recording_archive=None,
        recording_spools=None,
        recording_archive_client=None,
        recording_archive_access=None,
        recording_stamper=None,
        websocket_manager=SimpleNamespace(recording=None),
        session_manager=SimpleNamespace(
            recording=None, pseudonymizer=SimpleNamespace(recording_reference=str)
        ),
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

    async def active_user_key(self, tenant_id, user_sub):
        return None

    @property
    def pool(self):
        return object()

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
    assert state.recording_retention is not None
    assert repository.registered == [state.recording_secrets.signing_key_id]
    sessions = state.recording_sessions
    assert sessions is not None
    assert state.websocket_manager.recording is sessions
    assert state.session_manager.recording is sessions
    await wiring.close_recording(state)
    assert state.recording_sessions is None
    assert state.recording_retention is None
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


async def test_without_an_archive_store_recording_is_wired_but_unavailable(
    secrets_on_disk, monkeypatch
):
    async def create(**_):
        return _Repository()

    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    monkeypatch.delenv("SSF_ARCHIVE_ENDPOINT", raising=False)
    state = _state()
    await wiring.connect_recording(state, DSN)

    assert state.recording_archive is None and state.recording_stamper is None
    assert state.recording_archive_access is None
    with pytest.raises(RecordingUnavailableError) as caught:
        await state.recording_sessions.check_available("tenant-test")
    assert caught.value.code == "ARCHIVE_UNAVAILABLE"
    await wiring.close_recording(state)


async def test_an_archive_store_wires_spools_that_stop_with_recording(
    secrets_on_disk, monkeypatch, tmp_path
):
    async def create(**_):
        return _Repository()

    writers = tmp_path / "archive-writers.json"
    writers.write_text(
        json.dumps({"tenant-test": {"access_key_id": "k", "secret_access_key": "s"}})
    )
    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    monkeypatch.setenv("SSF_ARCHIVE_ENDPOINT", "http://archive.test:8333")
    monkeypatch.setenv("SSF_ARCHIVE_WRITERS_FILE", str(writers))
    monkeypatch.setenv("SSF_ARCHIVE_SPOOL_DIR", str(tmp_path / "spool"))
    state = _state()
    await wiring.connect_recording(state, DSN)

    assert state.recording_archive is not None
    assert state.recording_sessions._archive is state.recording_archive
    access = state.recording_archive_access
    assert access is not None
    assert access._spools is state.recording_spools
    assert (tmp_path / "spool").is_dir()
    spools = state.recording_spools
    spools.spool("tenant-test")
    assert spools._tasks  # an uploader per tenant, running
    await wiring.close_recording(state)
    assert spools._tasks == {} and state.recording_archive is None
    assert state.recording_archive_access is None


async def test_the_archive_counts_a_session_live_until_it_ends(
    secrets_on_disk, monkeypatch, tmp_path
):
    async def create(**_):
        return _Repository()

    writers = tmp_path / "archive-writers.json"
    writers.write_text(
        json.dumps({"tenant-test": {"access_key_id": "k", "secret_access_key": "s"}})
    )
    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    monkeypatch.setenv("SSF_ARCHIVE_ENDPOINT", "http://archive.test:8333")
    monkeypatch.setenv("SSF_ARCHIVE_WRITERS_FILE", str(writers))
    monkeypatch.setenv("SSF_ARCHIVE_SPOOL_DIR", str(tmp_path / "spool"))
    state = _state()
    listed = [
        SimpleNamespace(id="LIVE0001", status=SessionStatus.ACTIVE),
        SimpleNamespace(id="WAIT0001", status=SessionStatus.PENDING),
        SimpleNamespace(id="DONE0001", status=SessionStatus.TERMINATED),
    ]

    async def list_for_tenant(tenant_id):
        assert tenant_id == "tenant-test"
        return listed

    state.session_manager.store = SimpleNamespace(list_for_tenant=list_for_tenant)
    await wiring.connect_recording(state, DSN)

    live = await state.recording_archive._live_sessions("tenant-test")
    assert sorted(live) == ["LIVE0001", "WAIT0001"]
    assert state.recording_stamper.tenants() == ("tenant-test",)
    await wiring.close_recording(state)


async def test_a_stamp_pass_ends_orphans_before_it_stamps():
    calls = []

    async def retry_pending_ends():
        calls.append("retry")

    async def end_orphaned(tenant_ids):
        calls.append(("orphans", tuple(tenant_ids)))

    async def run_once():
        calls.append("stamp")

    state = SimpleNamespace(
        recording_archive=SimpleNamespace(
            retry_pending_ends=retry_pending_ends, end_orphaned=end_orphaned
        ),
        recording_stamper=SimpleNamespace(tenants=lambda: ("tenant-test",), run_once=run_once),
    )

    await wiring.stamp_once(state)

    assert calls == ["retry", ("orphans", ("tenant-test",)), "stamp"]


async def test_a_tenant_missing_from_the_writers_file_cannot_record(
    secrets_on_disk, monkeypatch, tmp_path
):
    async def create(**_):
        return _Repository()

    writers = tmp_path / "archive-writers.json"
    writers.write_text(
        json.dumps({"tenant-test": {"access_key_id": "k", "secret_access_key": "s"}})
    )
    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    monkeypatch.setenv("SSF_ARCHIVE_ENDPOINT", "http://archive.test:8333")
    monkeypatch.setenv("SSF_ARCHIVE_WRITERS_FILE", str(writers))
    monkeypatch.setenv("SSF_ARCHIVE_SPOOL_DIR", str(tmp_path / "spool"))
    state = _state()
    await wiring.connect_recording(state, DSN)

    assert state.recording_archive.can_record("tenant-test")
    with pytest.raises(RecordingUnavailableError) as caught:
        await state.recording_sessions.check_available("tenant-other")
    assert caught.value.code == "ARCHIVE_UNAVAILABLE"
    await wiring.close_recording(state)


async def test_an_unreadable_writers_file_leaves_the_archive_off(
    secrets_on_disk, monkeypatch, tmp_path
):
    async def create(**_):
        return _Repository()

    monkeypatch.setattr(wiring.PostgresCeremonyRepository, "create", create)
    monkeypatch.setenv("SSF_ARCHIVE_ENDPOINT", "http://archive.test:8333")
    monkeypatch.setenv("SSF_ARCHIVE_WRITERS_FILE", str(tmp_path / "absent.json"))
    state = _state()

    assert await wiring.connect_recording(state, DSN) is True
    assert state.recording_archive is None
    assert state.recording_sessions is not None
    await wiring.close_recording(state)

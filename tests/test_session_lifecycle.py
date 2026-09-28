"""The session lifecycle decisions the admin and customer routes map onto HTTP (#228 task 2.3)."""

from __future__ import annotations

import pytest

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.consent import ConsentStatus
from services.api_gateway.session_lifecycle import (
    SessionLifecycleService,
    SessionNotFoundError,
    SessionTerminatedError,
    TenantConflictError,
)
from services.api_gateway.session_manager import SessionStatus, TenantSessionManager
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.studio_runtime_client import StudioRuntimeClientError
from services.api_gateway.studio_runtime_flow import StudioRuntimeFlow
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot, TenantSessionKey
from tests.gateway_contract.contract_support import runtime_configuration

REVISION = f"sha256:{'a' * 64}"
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


class _Unread(Exception):
    """Raised by a correlation id source that must not be read."""


def _must_not_read() -> str:
    raise _Unread


class _FailingFetcher:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.correlation_ids: list[str] = []

    async def fetch(self, tenant_id: str, correlation_id: str) -> object:
        self.correlation_ids.append(correlation_id)
        raise self.error


@pytest.fixture
def sessions() -> TenantSessionManager:
    return TenantSessionManager(
        store=MemoryTenantSessionStore(),
        audio_store=AudioStore.from_environment(),
    )


async def _pending(sessions: TenantSessionManager) -> TenantSessionKey:
    return (await sessions.create_admin_session("tenant-a", SNAPSHOT)).key


async def test_a_repeated_activation_never_reads_the_correlation_id(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    await lifecycle.activate(key, "en", True, None, lambda: "first")

    same = await lifecycle.activate(key, "en", None, None, _must_not_read)
    switched = await lifecycle.activate(key, "ar", None, None, _must_not_read)

    assert same.already_active and switched.already_active
    assert switched.session.customer_language == "ar"


async def test_a_first_activation_reads_the_correlation_id_without_studio(
    sessions: TenantSessionManager,
) -> None:
    key = await _pending(sessions)

    with pytest.raises(_Unread):
        await SessionLifecycleService(sessions).activate(key, "en", True, None, _must_not_read)

    session = sessions.get_session(key)
    assert session is not None
    assert session.status is SessionStatus.PENDING


@pytest.mark.parametrize(
    "code", ["tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"]
)
async def test_a_tenant_conflict_refuses_activation(
    sessions: TenantSessionManager, code: str
) -> None:
    key = await _pending(sessions)
    fetcher = _FailingFetcher(StudioRuntimeClientError(code, retryable=False))

    with pytest.raises(TenantConflictError) as raised:
        await SessionLifecycleService(sessions).activate(
            key, "en", True, StudioRuntimeFlow(fetcher), lambda: "corr-1"
        )

    assert raised.value.code == code
    assert fetcher.correlation_ids == ["corr-1"]
    session = sessions.get_session(key)
    assert session is not None
    assert session.status is SessionStatus.PENDING


async def test_any_other_studio_failure_activates_without_consent(
    sessions: TenantSessionManager,
) -> None:
    key = await _pending(sessions)
    fetcher = _FailingFetcher(StudioRuntimeClientError("studio_unavailable", retryable=True))

    activation = await SessionLifecycleService(sessions).activate(
        key, "en", True, StudioRuntimeFlow(fetcher), lambda: "corr-1"
    )

    assert not activation.already_active
    assert activation.session.status is SessionStatus.ACTIVE
    assert activation.session.consent_status is not ConsentStatus.GRANTED


async def test_a_terminated_session_is_not_activated(sessions: TenantSessionManager) -> None:
    key = await _pending(sessions)
    await sessions.terminate_session(key, "test")

    with pytest.raises(SessionTerminatedError):
        await SessionLifecycleService(sessions).activate(key, "en", True, None, _must_not_read)


async def test_terminate_reports_whether_it_ended_the_session(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)

    assert await lifecycle.terminate(key) is True
    assert await lifecycle.terminate(key) is False
    with pytest.raises(SessionNotFoundError):
        await lifecycle.terminate(TenantSessionKey("tenant-a", "UNKNOWN1"))


async def test_create_replaces_only_the_same_tenants_active_session(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    first = await lifecycle.create("tenant-a", runtime_configuration("tenant-a"))
    other = await lifecycle.create("tenant-b", runtime_configuration("tenant-b"))
    second = await lifecycle.create("tenant-a", runtime_configuration("tenant-a"))

    assert sessions.get_session(first.key).status is SessionStatus.TERMINATED
    assert sessions.get_session(other.key).status is SessionStatus.PENDING
    assert lifecycle.current("tenant-a", None).id == second.id


@pytest.mark.parametrize(
    ("first", "second", "logged"),
    [
        ("en", "ar", ["en", "en", "ar"]),
        ("xx<injected>", "yy\nforged", ["unsupported", "unsupported", "unsupported"]),
    ],
)
async def test_activation_logs_only_allowlisted_language_codes(
    sessions: TenantSessionManager,
    caplog: pytest.LogCaptureFixture,
    first: str,
    second: str,
    logged: list[str],
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)

    with caplog.at_level("INFO", logger="services.api_gateway.session_lifecycle"):
        await lifecycle.activate(key, first, True, None, lambda: "first")
        await lifecycle.activate(key, second, None, None, _must_not_read)

    text = caplog.text
    activated = next(
        r.getMessage() for r in caplog.records if "erfolgreich aktiviert" in r.getMessage()
    )
    switched = next(
        r.getMessage() for r in caplog.records if "Sprache wird aktualisiert" in r.getMessage()
    )
    assert f"'customer_language': '{logged[0]}'" in activated
    assert f"'previous_language': '{logged[1]}'" in switched
    assert f"'new_language': '{logged[2]}'" in switched
    assert "injected" not in text
    assert "forged" not in text

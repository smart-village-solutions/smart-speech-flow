"""The session lifecycle decisions the admin and customer routes map onto HTTP (#228 task 2.3)."""

from __future__ import annotations

import asyncio

import pytest

from services.api_gateway.audio_storage import AudioStore
from services.api_gateway.guest_token import guest_token_admits
from services.api_gateway.session_lifecycle import (
    GuestConflictError,
    SessionLifecycleService,
    SessionNotFoundError,
    SessionTerminatedError,
    TenantConflictError,
)
from services.api_gateway.session_manager import TenantSessionManager
from services.api_gateway.session_models import SessionStatus
from services.api_gateway.session_store import MemoryTenantSessionStore
from services.api_gateway.studio_runtime_flow import StudioRuntimeFlow
from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError
from services.api_gateway.tenant_context import admin_ref
from services.api_gateway.tenant_session import TenantSessionKey
from tests.runtime_policy_helpers import runtime_read

REVISION = f"sha256:{'a' * 64}"


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
    return (await sessions.create_admin_session("tenant-a", REVISION)).key


async def test_a_repeated_activation_never_reads_the_correlation_id(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    token = (await lifecycle.activate(key, "en", None, lambda: "first")).guest_token

    same = await lifecycle.activate(key, "en", None, _must_not_read, guest_token=token)
    switched = await lifecycle.activate(key, "ar", None, _must_not_read, guest_token=token)

    assert same.already_active and switched.already_active
    assert switched.session.customer_language == "ar"


async def test_a_first_activation_reads_the_correlation_id_without_studio(
    sessions: TenantSessionManager,
) -> None:
    key = await _pending(sessions)

    with pytest.raises(_Unread):
        await SessionLifecycleService(sessions).activate(key, "en", None, _must_not_read)

    session = await sessions.get_session(key)
    assert session is not None
    assert session.status is SessionStatus.PENDING


@pytest.mark.parametrize(
    "code", ["tenant_suspended", "ssf_plugin_inactive", "ssf_tenant_not_ready"]
)
async def test_a_tenant_conflict_refuses_activation(
    sessions: TenantSessionManager, code: str
) -> None:
    key = await _pending(sessions)
    fetcher = _FailingFetcher(StudioRuntimeV2ClientError(code, retryable=False))

    with pytest.raises(TenantConflictError) as raised:
        await SessionLifecycleService(sessions).activate(
            key, "en", StudioRuntimeFlow(fetcher), lambda: "corr-1"
        )

    assert raised.value.code == code
    assert fetcher.correlation_ids == ["corr-1"]
    session = await sessions.get_session(key)
    assert session is not None
    assert session.status is SessionStatus.PENDING


async def test_any_other_studio_failure_lets_the_activation_through(
    sessions: TenantSessionManager,
) -> None:
    key = await _pending(sessions)
    fetcher = _FailingFetcher(StudioRuntimeV2ClientError("studio_unavailable", retryable=True))

    activation = await SessionLifecycleService(sessions).activate(
        key, "en", StudioRuntimeFlow(fetcher), lambda: "corr-1"
    )

    assert not activation.already_active
    assert activation.session.status is SessionStatus.ACTIVE


async def test_a_terminated_session_is_not_activated(sessions: TenantSessionManager) -> None:
    key = await _pending(sessions)
    await sessions.terminate_session(key, "test")

    with pytest.raises(SessionTerminatedError):
        await SessionLifecycleService(sessions).activate(key, "en", None, _must_not_read)


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
    tenant_a_admin = admin_ref("tenant-a", "admin-subject")
    first = await lifecycle.create("tenant-a", REVISION, owner_ref=tenant_a_admin)
    other = await lifecycle.create(
        "tenant-b",
        REVISION,
        owner_ref=admin_ref("tenant-b", "admin-subject"),
    )
    second = await lifecycle.create("tenant-a", REVISION, owner_ref=tenant_a_admin)

    assert (await sessions.get_session(first.key)).status is SessionStatus.TERMINATED
    assert (await sessions.get_session(other.key)).status is SessionStatus.PENDING
    assert (await lifecycle.current("tenant-a", None, owner_ref=tenant_a_admin)).id == second.id


@pytest.mark.parametrize(
    ("first", "second", "logged"),
    [
        ("en", "ar", ["en", "en", "ar"]),
        ("zh", "hi", ["zh", "zh", "hi"]),
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
        first_activation = await lifecycle.activate(key, first, None, lambda: "first")
        await lifecycle.activate(
            key, second, None, _must_not_read, guest_token=first_activation.guest_token
        )

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


class _GatedFetcher:
    """Hands out one read per call, each released by the test."""

    def __init__(self, *reads: object) -> None:
        self.reads = list(reads)
        self.gates = [asyncio.Event() for _ in reads]
        self.calls = 0

    async def fetch(self, tenant_id: str, correlation_id: str) -> object:
        index = self.calls
        self.calls += 1
        await self.gates[index].wait()
        return self.reads[index]


async def test_a_second_join_waits_and_makes_no_studio_read(
    sessions: TenantSessionManager,
) -> None:
    # A double-submitted join must not swap the guest token the first one claimed.
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    fetcher = _GatedFetcher(runtime_read("tenant-a"))
    flow = StudioRuntimeFlow(fetcher)

    first = asyncio.create_task(lifecycle.activate(key, "en", flow, lambda: "first"))
    second = asyncio.create_task(lifecycle.activate(key, "en", flow, lambda: "second"))
    while fetcher.calls < 1:
        await asyncio.sleep(0)
    for _ in range(5):
        await asyncio.sleep(0)
    assert fetcher.calls == 1
    fetcher.gates[0].set()
    activated, repeated = await asyncio.gather(first, second, return_exceptions=True)

    assert not activated.already_active
    assert isinstance(repeated, GuestConflictError)
    assert fetcher.calls == 1
    stored = await sessions.store.load(key)
    assert stored.status is SessionStatus.ACTIVE
    assert guest_token_admits(stored.guest_token_hash, activated.guest_token)


async def test_a_read_finishing_while_the_first_activation_saves_cannot_overwrite_it(
    sessions: TenantSessionManager,
) -> None:
    # Both reads return together: the second resumes while the first is still
    # inside activate_session, before the status says ACTIVE.
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    fetcher = _GatedFetcher(
        runtime_read("tenant-a"),
        runtime_read("tenant-a", revision=f"sha256:{'b' * 64}"),
    )
    flow = StudioRuntimeFlow(fetcher)
    first = asyncio.create_task(lifecycle.activate(key, "en", flow, lambda: "first"))
    second = asyncio.create_task(lifecycle.activate(key, "tr", flow, lambda: "second"))
    while fetcher.calls < 1:
        await asyncio.sleep(0)
    for gate in fetcher.gates:
        gate.set()

    activated, repeated = await asyncio.gather(first, second, return_exceptions=True)

    assert isinstance(repeated, GuestConflictError)
    stored = await sessions.store.load(key)
    assert stored.customer_language == "en"
    assert guest_token_admits(stored.guest_token_hash, activated.guest_token)


class _Sockets:
    """Records what the session manager broadcasts."""

    def __init__(self) -> None:
        self.frames: list[tuple[TenantSessionKey, dict]] = []

    async def broadcast_to_session(self, key, frame, **_options) -> None:
        self.frames.append((key, dict(frame)))

    async def handle_session_termination(self, key, reason) -> None:
        return None


async def test_the_first_activation_issues_a_token_and_keeps_only_its_digest(
    sessions: TenantSessionManager,
) -> None:
    key = await _pending(sessions)

    activated = await SessionLifecycleService(sessions).activate(
        key, "en", None, lambda: "c"
    )

    assert activated.guest_token
    stored = await sessions.store.load(key)
    assert stored.guest_token_hash
    assert activated.guest_token not in stored.guest_token_hash


async def test_the_holder_switches_language_and_the_session_is_told(
    sessions: TenantSessionManager,
) -> None:
    sockets = _Sockets()
    sessions.register_websocket_manager(sockets)
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    token = (await lifecycle.activate(key, "en", None, lambda: "c")).guest_token

    switched = await lifecycle.activate(key, "tr", None, _must_not_read, guest_token=token)

    assert switched.guest_token is None
    assert switched.session.customer_language == "tr"
    assert [frame["role"] for _, frame in sockets.frames] == ["customer_language_changed"]
    assert sockets.frames[0][0] == key
    assert sockets.frames[0][1]["customer_language"] == "tr"


async def test_the_holder_repeating_the_same_language_changes_nothing(
    sessions: TenantSessionManager,
) -> None:
    sockets = _Sockets()
    sessions.register_websocket_manager(sockets)
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    token = (await lifecycle.activate(key, "en", None, lambda: "c")).guest_token

    same = await lifecycle.activate(key, "en", None, _must_not_read, guest_token=token)

    assert same.already_active
    assert sockets.frames == []


@pytest.mark.parametrize("presented", [None, "", "not-the-token"])
async def test_a_stranger_cannot_reactivate_a_claimed_session(
    sessions: TenantSessionManager, presented: str | None
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    await lifecycle.activate(key, "en", None, lambda: "c")

    with pytest.raises(GuestConflictError):
        await lifecycle.activate(key, "tr", None, _must_not_read, guest_token=presented)

    session = await sessions.get_session(key)
    assert session is not None and session.customer_language == "en"


async def test_concurrent_first_activations_admit_exactly_one_guest(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    fetcher = _GatedFetcher(runtime_read("tenant-a"))
    flow = StudioRuntimeFlow(fetcher)

    first = asyncio.create_task(lifecycle.activate(key, "en", flow, lambda: "a"))
    second = asyncio.create_task(lifecycle.activate(key, "tr", flow, lambda: "b"))
    while fetcher.calls < 1:
        await asyncio.sleep(0)
    fetcher.gates[0].set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    winners = [result for result in results if not isinstance(result, BaseException)]
    losers = [result for result in results if isinstance(result, GuestConflictError)]
    assert len(winners) == 1 and len(losers) == 1
    assert winners[0].guest_token
    session = await sessions.get_session(key)
    assert session is not None and session.customer_language == "en"


async def test_a_session_activated_before_tokens_existed_keeps_todays_behaviour(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    await lifecycle.activate(key, "en", None, lambda: "c")
    session = await sessions.get_session(key)
    assert session is not None
    session.guest_token_hash = None

    switched = await lifecycle.activate(key, "ar", None, _must_not_read)

    assert switched.session.customer_language == "ar"


async def test_the_browser_chooses_the_token_so_a_lost_response_can_be_retried(
    sessions: TenantSessionManager,
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    chosen = "c" * 43

    claimed = await lifecycle.activate(key, "en", None, lambda: "c", guest_token=chosen)
    # The response never arrived; the browser retries with the token it kept.
    retried = await lifecycle.activate(key, "en", None, _must_not_read, guest_token=chosen)

    assert claimed.guest_token == chosen
    assert retried.already_active


async def test_a_claim_whose_save_fails_leaves_the_session_unclaimed(
    sessions: TenantSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)

    async def failing_save(*_args) -> None:
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(sessions, "activate_session", failing_save)
    with pytest.raises(RuntimeError):
        await lifecycle.activate(key, "en", None, lambda: "c", guest_token="d" * 43)

    session = await sessions.get_session(key)
    assert session is not None and session.guest_token_hash is None


@pytest.mark.parametrize("language", ["ti", "ku", "kmr", "ti-ER", "ku-TR", "kmr-TR"])
@pytest.mark.parametrize("active", [False, True])
async def test_removed_languages_cannot_activate_or_switch_a_session(sessions, language, active):
    lifecycle = SessionLifecycleService(sessions)
    key = await _pending(sessions)
    token = None
    if active:
        token = (await lifecycle.activate(key, "en", None, lambda: "c")).guest_token
    before = (await sessions.get_session(key)).to_dict(include_messages=True)

    with pytest.raises(ValueError, match="Unsupported language"):
        await lifecycle.activate(key, language, None, lambda: "c", guest_token=token)

    assert (await sessions.get_session(key)).to_dict(include_messages=True) == before

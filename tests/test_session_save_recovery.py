"""Persistence snapshots and recovery after an ambiguous save acknowledgement."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.api_gateway.session_models import Session, SessionStatus
from services.api_gateway.session_store import MemoryTenantSessionStore


def make_session() -> Session:
    return Session(
        id="ABC12345",
        tenant_id="tenant-a",
        configuration_revision=f"sha256:{'a' * 64}",
        usage_language_changes=[{"at": "2026-11-18T10:00:00+00:00", "language": "en"}],
    )


async def test_memory_create_keeps_an_independent_persisted_snapshot() -> None:
    store = MemoryTenantSessionStore()
    session = make_session()
    assert await store.create(session)

    session.customer_language = "fr"
    session.usage_language_changes[0]["language"] = "fr"

    persisted = await store.load(session.key)
    assert persisted is not None
    assert persisted.customer_language is None
    assert persisted.usage_language_changes[0]["language"] == "en"


@pytest.mark.parametrize("committed", [False, True])
async def test_reconciliation_restores_the_canonical_save_result(committed: bool) -> None:
    from services.api_gateway.session_save_recovery import reconcile_failed_save

    store = MemoryTenantSessionStore()
    session = make_session()
    assert await store.create(session)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "fr"
    session.usage_language_changes.append({"at": "2026-11-18T10:05:00+00:00", "language": "fr"})
    if committed:
        await store.save(session)

    assert await reconcile_failed_save(store, session) is True
    assert session.status == (SessionStatus.ACTIVE if committed else SessionStatus.PENDING)
    assert session.customer_language == ("fr" if committed else None)
    assert len(session.usage_language_changes) == (2 if committed else 1)
    session.usage_language_changes[0]["language"] = "de"
    persisted = await store.load(session.key)
    assert persisted is not None
    assert persisted.usage_language_changes[0]["language"] == "en"


async def test_reconciliation_returns_false_without_a_persisted_record() -> None:
    from services.api_gateway.session_save_recovery import reconcile_failed_save

    session = make_session()
    assert await reconcile_failed_save(MemoryTenantSessionStore(), session) is False
    assert session.usage_language_changes[0]["language"] == "en"


async def test_reconciliation_propagates_an_unavailable_canonical_store() -> None:
    from services.api_gateway.session_save_recovery import reconcile_failed_save

    class UnavailableStore(MemoryTenantSessionStore):
        async def load(self, key):
            raise ConnectionError("canonical state unavailable")

    session = make_session()
    with pytest.raises(ConnectionError, match="canonical state unavailable"):
        await reconcile_failed_save(UnavailableStore(), session)
    assert session.usage_language_changes[0]["language"] == "en"


async def test_memory_save_and_load_keep_nested_state_independent() -> None:
    store = MemoryTenantSessionStore()
    session = make_session()
    assert await store.create(session)
    session.customer_language = "en"
    await store.save(session)

    session.customer_language = "fr"
    persisted = await store.load(session.key)
    assert persisted is not None
    assert persisted.customer_language == "en"
    persisted.usage_language_changes[0]["language"] = "fr"
    reloaded = await store.load(session.key)
    assert reloaded is not None
    assert reloaded.usage_language_changes[0]["language"] == "en"


@pytest.mark.parametrize("retry", [False, True])
async def test_memory_terminate_returns_independent_terminal_snapshot(retry: bool) -> None:
    store = MemoryTenantSessionStore()
    session = make_session()
    assert await store.create(session)
    session.status = SessionStatus.TERMINATED
    session.terminated_at = datetime(2026, 11, 18, 11, tzinfo=timezone.utc)
    terminal = await store.terminate(session)
    if retry:
        terminal = await store.terminate(session)

    terminal.usage_language_changes[0]["language"] = "fr"
    session.customer_language = "fr"
    persisted = await store.load(session.key)
    assert persisted is not None
    assert persisted.customer_language is None
    assert persisted.usage_language_changes[0]["language"] == "en"

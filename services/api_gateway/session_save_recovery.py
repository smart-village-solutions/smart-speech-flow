"""Recover canonical state when a session save's acknowledgement is lost."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields

from .session_models import Session
from .session_store import TenantSessionStore


async def reconcile_failed_save(store: TenantSessionStore, session: Session) -> bool:
    """Restore the existing object from persistence, preserving its identity.

    A failed save may already have committed. Read the authoritative record
    before choosing a rollback. False means no record was available; load
    errors propagate so the caller can evict its cache rather than trust an
    unknown state. The caller must hold its session lifecycle lock throughout
    the attempted save and this reconciliation.
    """
    canonical = await store.load(session.key)
    if canonical is None:
        return False
    snapshot = deepcopy(canonical)
    for item in fields(Session):
        setattr(session, item.name, getattr(snapshot, item.name))
    return True

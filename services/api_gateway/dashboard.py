"""Compose owned sessions and authorized archive metadata without opening contents."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from redis.exceptions import RedisError

from .recording.permissions import RECORDING_PERMISSIONS, SUPERVISE
from .recording.verification_model import summary
from .session_models import Session, SessionStatus
from .session_pseudonym import SessionPseudonymizer
from .session_store import SessionStoreConsistencyError


class DashboardUnavailableError(Exception):
    """A required source failed; absence of a recording cannot be asserted."""


class SessionSource(Protocol):
    async def list_for_tenant(self, tenant_id: str) -> list[Session]: ...


class RecordingSource(Protocol):
    async def overview(
        self,
        tenant_id: str,
        sub: str,
        refs: Mapping[str, datetime],
        before: tuple[str, str] | None,
        limit: int,
        supervisor: bool | None,
    ) -> list[dict[str, Any]]: ...


class DashboardCursor:
    """Opaque authenticated keyset boundaries, scoped to the user and tenant."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Dashboard key must contain 32 bytes")
        self._key = key

    @classmethod
    def from_environment(cls) -> "DashboardCursor":
        configured = (os.environ.get("SSF_QUALITY_TELEMETRY_SESSION_KEY") or "").strip()
        if configured:
            master = configured.encode()
        else:
            master = base64.b64decode(
                os.environ.get("SSF_FEEDBACK_ENCRYPTION_KEY", ""), validate=True
            )
            if len(master) != 32:
                raise ValueError("A shared deployment secret is required for dashboard cursors")
        return cls(hmac.digest(master, b"SSF-DASHBOARD-CURSOR-V1", "sha256"))

    def row_id(self, tenant: str, session_id: str) -> str:
        message = json.dumps(["dashboard-row", tenant, session_id]).encode()
        return "s-" + hmac.new(self._key, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _aad(tenant: str, sub: str) -> bytes:
        return json.dumps(["dashboard-cursor-v1", tenant, sub]).encode()

    def encode(self, tenant: str, sub: str, boundary: tuple[str, str]) -> str:
        nonce = secrets.token_bytes(12)
        body = json.dumps([*boundary, datetime.now(timezone.utc).timestamp()]).encode()
        sealed = AESGCM(self._key).encrypt(nonce, body, self._aad(tenant, sub))
        return base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")

    def decode(self, tenant: str, sub: str, token: str) -> tuple[str, str]:
        try:
            if len(token) > 1024:
                raise ValueError
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            body = AESGCM(self._key).decrypt(raw[:12], raw[12:], self._aad(tenant, sub))
            at, row_id, issued = json.loads(body)
            age = datetime.now(timezone.utc).timestamp() - issued
            if not 0 <= age <= 900 or not isinstance(row_id, str):
                raise ValueError
            datetime.fromisoformat(at)
            return at, row_id
        except (ValueError, TypeError, InvalidTag, json.JSONDecodeError):
            raise ValueError("Invalid dashboard cursor") from None


class Dashboard:
    def __init__(
        self,
        sessions: SessionSource,
        recordings: RecordingSource | None,
        pseudonymizer: SessionPseudonymizer,
        cursor: DashboardCursor | None = None,
    ) -> None:
        self.sessions = sessions
        self.recordings = recordings
        self.pseudonymizer = pseudonymizer
        self.cursor = cursor or DashboardCursor.from_environment()

    async def conversations(
        self,
        tenant: str,
        sub: str,
        owner: str,
        permissions: frozenset[str],
        limit: int,
        token: str | None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("Invalid dashboard page size")
        before = self.cursor.decode(tenant, sub, token) if token else None
        try:
            sessions = [
                row
                for row in await self.sessions.list_for_tenant(tenant)
                if row.tenant_id == tenant and row.is_owned_by(owner)
            ]
            by_ref = {self.pseudonymizer.recording_reference(row.id): row for row in sessions}
            has_archive_permission = not permissions.isdisjoint(RECORDING_PERMISSIONS)
            if has_archive_permission and self.recordings is None:
                raise DashboardUnavailableError
            records = (
                await self.recordings.overview(
                    tenant,
                    sub,
                    {ref: row.created_at for ref, row in by_ref.items()},
                    before,
                    limit + 1,
                    SUPERVISE in permissions if has_archive_permission else None,
                )
                if self.recordings is not None
                else []
            )
        except (OSError, TimeoutError, ConnectionError, RedisError, SessionStoreConsistencyError):
            raise DashboardUnavailableError from None
        items: dict[str, dict[str, Any]] = {}
        linked: set[str] = set()
        for record in records:
            source = by_ref.get(record["session_ref"])
            if record.get("private_recorded") or not (
                has_archive_permission and record["can_open"]
            ):
                if source is not None:
                    linked.add(source.id)
                    if record.get("archive_accessible") and has_archive_permission:
                        continue
                    item = self._session(tenant, source, recorded=True)
                    items[item["id"]] = item
                continue
            if source is not None:
                linked.add(source.id)
                items.pop(self.cursor.row_id(tenant, source.id), None)
            item = self._recording(record, sub, source)
            items[item["id"]] = item
        for source in sessions:
            if source.id not in linked:
                item = self._session(tenant, source)
                items[item["id"]] = item
        rows = sorted(
            items.values(), key=lambda item: (item["started_at"], item["id"]), reverse=True
        )
        if before:
            rows = [row for row in rows if (row["started_at"], row["id"]) < before]
        page = rows[:limit]
        cursor = (
            self.cursor.encode(tenant, sub, (page[-1]["started_at"], page[-1]["id"]))
            if len(rows) > limit
            else None
        )
        return {"items": page, "next_cursor": cursor}

    def _session(self, tenant: str, row: Session, *, recorded: bool = False) -> dict[str, Any]:
        ended = row.status == SessionStatus.TERMINATED
        recorded = recorded or self.pseudonymizer.is_recorded(row.id)
        return {
            "id": self.cursor.row_id(tenant, row.id),
            "session_id": row.id,
            "recording_id": None,
            "origin": "own",
            "started_at": row.created_at.isoformat(),
            "ended_at": row.terminated_at.isoformat() if row.terminated_at else None,
            "conversation_status": "ended" if ended else row.status.value,
            "recording_status": "unavailable" if recorded else "none",
            "recording_access": "none",
            "customer_language": None if recorded else row.customer_language,
            "language_visibility": (
                "encrypted" if recorded else "clear" if row.customer_language else "unknown"
            ),
            "verification": None,
            "actions": ([] if recorded else ["open_details"]) if ended else ["resume"],
        }

    @staticmethod
    def _recording(record: dict[str, Any], sub: str, source: Session | None) -> dict[str, Any]:
        ongoing = source is not None and source.status != SessionStatus.TERMINATED
        ended_at: datetime | None = source.terminated_at if source else record["ended_at"]
        available = bool(record["can_open"])
        actions = ["resume"] if ongoing else ["open_recording"] if available else []
        return {
            "id": "r-" + str(record["conversation_id"]),
            "session_id": source.id if source else None,
            "recording_id": str(record["conversation_id"]),
            "origin": "own" if record["employee_sub"] == sub else "transferred",
            "started_at": (source.created_at if source else record["started_at"]).isoformat(),
            "ended_at": ended_at.isoformat() if ended_at else None,
            "conversation_status": (
                source.status.value if source is not None and ongoing else "ended"
            ),
            "recording_status": "incomplete" if record["incomplete"] else "available",
            "recording_access": "available" if available else "transfer_required",
            "customer_language": None,
            "language_visibility": "encrypted",
            "verification": summary(list(record["verification_statuses"] or ())),
            "actions": actions,
        }

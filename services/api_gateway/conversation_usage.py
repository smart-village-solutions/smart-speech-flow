"""Content-free elapsed conversation accounting, independent of Redis retention."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from pydantic import BaseModel, Field

from .clock import utc_now
from .session_models import Session, _ensure_utc


class UsageUnavailable(RuntimeError):
    """Usage could not be recorded or read reliably."""


class UsageScope(BaseModel):
    total_seconds: float = 0
    by_language: dict[str, float] = Field(default_factory=dict)


class UsageReport(BaseModel):
    window_start: datetime
    window_end: datetime
    coverage_start: datetime
    complete: bool
    personal: UsageScope
    organisation: UsageScope
    server: UsageScope


@dataclass(frozen=True)
class UsageSnapshot:
    """The allowlisted projection; never a serialised conversation or message."""

    key: str
    tenant_id: str
    owner_ref: str | None
    changes: str
    ended_at: float | None
    deadline: float
    updated_at: float

    @classmethod
    def of(cls, session: Session, now: datetime) -> UsageSnapshot | None:
        if not session.usage_language_changes:
            return None
        return cls(
            key=hashlib.sha256(f"{session.key.tenant_id}\0{session.id}".encode()).hexdigest(),
            tenant_id=session.key.tenant_id,
            owner_ref=session.owner_ref,
            changes=json.dumps(session.usage_language_changes, separators=(",", ":")),
            ended_at=(
                _ensure_utc(session.terminated_at).timestamp()
                if session.terminated_at is not None
                else None
            ),
            deadline=_ensure_utc(session.next_timeout_at()).timestamp(),
            updated_at=_ensure_utc(now).timestamp(),
        )


class ConversationUsage:
    """A single-gateway SQLite ledger. All disk work runs outside the event loop.

    A dedicated volume holds only identifiers and timing/language metadata, never
    transcripts, audio or token material. None selects process-local SQLite for
    development and tests. Production supplies SSF_USAGE_DATABASE_PATH.
    """

    def __init__(self, path: str | None = None, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.path = path or ":memory:"
        self.started_at = _ensure_utc(clock())
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> ConversationUsage:
        path = os.environ.get("SSF_USAGE_DATABASE_PATH", "").strip() or None
        if path is None and os.environ.get("SSF_DEPLOYMENT_ENV", "").casefold() == "production":
            path = "/var/lib/ssf-usage/usage.sqlite3"
        return cls(path)

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS usage_metadata (
                        name TEXT PRIMARY KEY, value REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS usage_sessions (
                        session_key TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        owner_ref TEXT,
                        changes TEXT NOT NULL,
                        ended_at REAL,
                        deadline REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS usage_sessions_end
                        ON usage_sessions(ended_at);
                    """)
                connection.execute(
                    "INSERT OR IGNORE INTO usage_metadata VALUES ('coverage_start', ?)",
                    (self.started_at.timestamp(),),
                )
                previous = connection.execute(
                    "SELECT value FROM usage_metadata WHERE name = 'run_open'"
                ).fetchone()
                if previous is not None and previous[0] == 1:
                    # Completed rows are trustworthy. Open rows must first be
                    # recovered from canonical Redis state after a hard stop.
                    connection.execute("DELETE FROM usage_sessions WHERE ended_at IS NULL")
                    connection.execute(
                        "UPDATE usage_metadata SET value = ? WHERE name = 'coverage_start'",
                        (self.started_at.timestamp(),),
                    )
                connection.execute("INSERT OR REPLACE INTO usage_metadata VALUES ('run_open', 1)")
                connection.commit()
                if self.path != ":memory:":
                    os.chmod(self.path, 0o600)
            except BaseException:
                connection.close()
                raise
            self._connection = connection
        return self._connection

    async def initialize(self) -> None:
        try:
            await asyncio.to_thread(self._initialize)
        except (sqlite3.Error, OSError):
            raise UsageUnavailable("Conversation usage unavailable") from None

    def _initialize(self) -> None:
        with self._lock:
            self._db()

    async def record(self, snapshot: UsageSnapshot) -> None:
        try:
            await asyncio.to_thread(self._record, snapshot)
        except (sqlite3.Error, OSError):
            raise UsageUnavailable("Conversation usage unavailable") from None

    def _record(self, snapshot: UsageSnapshot) -> None:
        with self._lock:
            db = self._db()
            with db:
                db.execute(
                    """INSERT INTO usage_sessions VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_key) DO UPDATE SET
                        changes=excluded.changes, ended_at=excluded.ended_at,
                        deadline=excluded.deadline, updated_at=excluded.updated_at
                    WHERE usage_sessions.ended_at IS NULL
                      AND excluded.updated_at >= usage_sessions.updated_at
                    """,
                    (
                        snapshot.key,
                        snapshot.tenant_id,
                        snapshot.owner_ref,
                        snapshot.changes,
                        snapshot.ended_at,
                        snapshot.deadline,
                        snapshot.updated_at,
                    ),
                )

    async def prune(self, now: datetime) -> None:
        try:
            await asyncio.to_thread(self._prune, _ensure_utc(now).timestamp())
        except (sqlite3.Error, OSError):
            raise UsageUnavailable("Conversation usage unavailable") from None

    async def finish_recovery(self, known_keys: set[str], now: datetime) -> None:
        """Discard open projections whose canonical live/terminal state was lost."""
        try:
            await asyncio.to_thread(self._finish_recovery, known_keys, _ensure_utc(now).timestamp())
        except (sqlite3.Error, OSError):
            raise UsageUnavailable("Conversation usage unavailable") from None

    def _finish_recovery(self, known_keys: set[str], now: float) -> None:
        with self._lock:
            db = self._db()
            missing = [
                row[0]
                for row in db.execute(
                    "SELECT session_key FROM usage_sessions WHERE ended_at IS NULL"
                ).fetchall()
                if row[0] not in known_keys
            ]
            if missing:
                with db:
                    db.executemany(
                        "DELETE FROM usage_sessions WHERE session_key = ?",
                        [(key,) for key in missing],
                    )
                    db.execute(
                        "UPDATE usage_metadata SET value = ? WHERE name = 'coverage_start'", (now,)
                    )

    def _prune(self, now: float) -> None:
        with self._lock:
            with self._db() as db:
                # An orphaned running row is bounded by its last known timeout.
                db.execute(
                    "DELETE FROM usage_sessions WHERE COALESCE(ended_at, deadline) < ?",
                    (now - timedelta(days=30).total_seconds(),),
                )

    async def report(self, tenant_id: str, owner_ref: str, now: datetime) -> UsageReport:
        try:
            return await asyncio.to_thread(self._report, tenant_id, owner_ref, _ensure_utc(now))
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
            raise UsageUnavailable("Conversation usage unavailable") from None

    def _report(self, tenant_id: str, owner_ref: str, now: datetime) -> UsageReport:
        window_start = now - timedelta(days=30)
        with self._lock:
            db = self._db()
            coverage = db.execute(
                "SELECT value FROM usage_metadata WHERE name = 'coverage_start'"
            ).fetchone()[0]
            rows = db.execute(
                """SELECT tenant_id, owner_ref, changes, ended_at, deadline
                   FROM usage_sessions WHERE COALESCE(ended_at, deadline) >= ?""",
                (window_start.timestamp(),),
            ).fetchall()
        personal, organisation, server = UsageScope(), UsageScope(), UsageScope()
        for tenant, owner, raw_changes, ended_at, deadline in rows:
            changes = json.loads(raw_changes)
            end = min(now.timestamp(), ended_at if ended_at is not None else deadline)
            scopes = [server]
            if tenant == tenant_id:
                scopes.append(organisation)
                if owner is not None and owner == owner_ref:
                    scopes.append(personal)
            for index, change in enumerate(changes):
                start = max(
                    datetime.fromisoformat(change["started_at"]).timestamp(),
                    window_start.timestamp(),
                )
                stop = end
                if index + 1 < len(changes):
                    stop = min(
                        stop, datetime.fromisoformat(changes[index + 1]["started_at"]).timestamp()
                    )
                seconds = max(0.0, stop - start)
                if seconds == 0:
                    continue
                language = change.get("language") or "unknown"
                for scope in scopes:
                    scope.total_seconds += seconds
                    scope.by_language[language] = scope.by_language.get(language, 0) + seconds
        return UsageReport(
            window_start=window_start,
            window_end=now,
            coverage_start=datetime.fromtimestamp(coverage, timezone.utc),
            complete=coverage <= window_start.timestamp(),
            personal=personal,
            organisation=organisation,
            server=server,
        )

    async def close(self, *, clean: bool = True) -> None:
        try:
            await asyncio.to_thread(self._close, clean)
        except (sqlite3.Error, OSError):
            raise UsageUnavailable("Conversation usage unavailable") from None

    def _close(self, clean: bool) -> None:
        with self._lock:
            if self._connection is not None:
                try:
                    if clean:
                        with self._connection:
                            self._connection.execute(
                                "UPDATE usage_metadata SET value = 0 WHERE name = 'run_open'"
                            )
                finally:
                    self._connection.close()
                    self._connection = None

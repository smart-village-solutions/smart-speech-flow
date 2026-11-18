"""Tenant transactions and the short-lived single-use possession challenge."""

from __future__ import annotations

import hmac
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar, cast

import asyncpg
from fastapi import HTTPException

from .audit import AuditEvent
from .crypto import ecies, tags
from .crypto.encoding import from_b64url
from .permissions import coded
from .repository import (
    COMMAND_TIMEOUT_SECONDS,
    DRIVER_FAILURE,
    append_audit,
    bind_tenant,
    storage_unavailable,
)
from .secrets import ServerLayer

T = TypeVar("T")


def utc_text(instant: datetime) -> str:
    return (
        instant.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def error(status: int, code: str) -> HTTPException:
    return coded(status, code, "Recording operation refused")


class Preparations:
    def __init__(
        self,
        pool: asyncpg.Pool,
        server_layer: ServerLayer,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.pool = pool
        self.server_layer = server_layer
        self.now = clock or (lambda: datetime.now(timezone.utc))

    async def run(
        self, tenant: str, work: Callable[[asyncpg.Connection], Awaitable[T | HTTPException]]
    ) -> T:
        try:
            async with self.pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as db, db.transaction():
                await bind_tenant(db, tenant)
                result = await work(db)
        except DRIVER_FAILURE as exc:
            raise storage_unavailable(exc) from None
        # Failed possession attempts and expiry invalidate secrets even on a refusal.
        if isinstance(result, HTTPException):
            raise result
        return result

    async def expire_secrets(self) -> None:
        try:
            async with self.pool.acquire(timeout=COMMAND_TIMEOUT_SECONDS) as db:
                await db.execute("SELECT public.expire_recording_preparation_secrets()")
        except DRIVER_FAILURE as exc:
            raise storage_unavailable(exc) from None

    async def challenge(
        self,
        db: asyncpg.Connection,
        tenant: str,
        actor: str,
        purpose: str,
        key: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any]]:
        pid = str(uuid.uuid4())
        expiry = self.now() + timedelta(minutes=5)
        expiry_text = utc_text(expiry)
        nonce = os.urandom(32)
        context = (tenant, actor, pid, purpose, key["keyId"], key["version"], expiry_text)
        sealed = ecies.seal(tags.ORG_POSSESSION, from_b64url(key["publicKey"]), nonce, context)
        await db.execute(
            "UPDATE key_preparations SET sealed_nonce=NULL WHERE expires_at<=$1 AND sealed_nonce IS NOT NULL",
            self.now(),
        )
        await db.execute(
            "INSERT INTO key_preparations(tenant_id,preparation_id,actor_sub,purpose,key_id,snapshot,expires_at,sealed_nonce) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            tenant,
            pid,
            actor,
            purpose,
            key["keyId"],
            json.dumps(snapshot),
            expiry,
            self.server_layer.seal_nonce(nonce, tenant, pid, purpose),
        )
        await append_audit(
            db,
            AuditEvent(
                tenant,
                actor,
                f"recording.{purpose}.prepared",
                f"{pid}:{key['keyId']}:{key['version']}",
                self.now(),
            ),
        )
        return pid, expiry_text, json.loads(sealed.to_json())

    async def locked(
        self, db: asyncpg.Connection, tenant: str, actor: str, pid: str, purpose: str
    ) -> asyncpg.Record:
        row = await db.fetchrow(
            "SELECT * FROM key_preparations WHERE preparation_id=$1 AND actor_sub=$2 AND purpose=$3 FOR UPDATE",
            pid,
            actor,
            purpose,
        )
        if row is None:
            raise error(404, "PREPARATION_NOT_FOUND")
        return row

    async def verify(
        self,
        db: asyncpg.Connection,
        row: asyncpg.Record,
        proof: bytes,
        transcript: bytes,
        request_digest: bytes,
    ) -> dict[str, Any] | HTTPException | None:
        if row["receipt"] is not None:
            if hmac.compare_digest(row["request_digest"], request_digest):
                return cast(dict[str, Any], json.loads(row["receipt"]))
            return error(409, "PREPARATION_USED")
        pid = str(row["preparation_id"])
        if row["expires_at"] <= self.now():
            await db.execute(
                "UPDATE key_preparations SET sealed_nonce=NULL WHERE preparation_id=$1", pid
            )
            return error(410, "PREPARATION_EXPIRED")
        if row["sealed_nonce"] is None:
            return error(409, "PREPARATION_USED")
        nonce = self.server_layer.open_nonce(
            row["sealed_nonce"], row["tenant_id"], pid, row["purpose"]
        )
        if not hmac.compare_digest(hmac.digest(nonce, transcript, "sha256"), proof):
            await db.execute(
                "UPDATE key_preparations SET failures=failures+1, "
                "sealed_nonce=CASE WHEN failures<4 THEN sealed_nonce END WHERE preparation_id=$1",
                pid,
            )
            await append_audit(
                db,
                AuditEvent(
                    row["tenant_id"],
                    row["actor_sub"],
                    f"recording.{row['purpose']}.proof_refused",
                    f"{pid}:{row['key_id']}",
                    self.now(),
                ),
            )
            return error(422, "INVALID_PROOF")
        return None

    async def committed(
        self,
        db: asyncpg.Connection,
        row: asyncpg.Record,
        request_digest: bytes,
        result: dict[str, Any],
        ref: str,
    ) -> dict[str, Any]:
        pid = str(row["preparation_id"])
        await db.execute(
            "UPDATE key_preparations SET sealed_nonce=NULL, request_digest=$2,receipt=$3 WHERE preparation_id=$1",
            pid,
            request_digest,
            json.dumps(result),
        )
        await append_audit(
            db,
            AuditEvent(
                row["tenant_id"],
                row["actor_sub"],
                "recording." + row["purpose"] + ".committed",
                f"{pid}:{ref}",
                self.now(),
            ),
        )
        return result

"""Authoritative organisation key registration and compare-and-swap activation."""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
from fastapi import HTTPException

from .audit import AuditEvent
from .conversation_keys import Recipient
from .crypto.curve import decode_point
from .crypto.encoding import b64url, enc
from .crypto.lifecycle import activation_transcript, digest, organisation_fingerprint
from .preparations import Preparations, error, utc_text
from .repository import append_audit


def metadata(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "keyId": str(row["key_id"]),
        "version": row["version"],
        "publicKey": b64url(row["public_key"]),
        "fingerprint": b64url(row["fingerprint"]),
        "state": row["state"],
        "createdAt": utc_text(row["created_at"]),
        "activatedAt": utc_text(row["activated_at"]) if row["activated_at"] else None,
    }


async def registry_lock(db: asyncpg.Connection, tenant: str) -> None:
    await db.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "ssf-org-registry:" + tenant
    )


async def check_active(db: asyncpg.Connection, expected: str | None) -> None:
    active = await db.fetchval("SELECT key_id FROM organisation_keys WHERE state='active'")
    if (str(active) if active else None) != expected:
        raise error(409, "KEY_VERSION_CHANGED")


class OrganisationKeys(Preparations):
    async def active_recipient(self, tenant: str) -> Recipient | None:
        async def work(db: asyncpg.Connection) -> Recipient | None:
            row = await db.fetchrow("SELECT * FROM organisation_keys WHERE state='active'")
            return (
                None
                if row is None
                else Recipient(
                    "organisation",
                    str(row["key_id"]),
                    row["public_key"],
                    row["fingerprint"],
                    row["version"],
                )
            )

        return await self.run(tenant, work)

    async def list(self, tenant: str) -> dict[str, Any]:
        async def work(db: asyncpg.Connection) -> dict[str, Any]:
            keys = [
                metadata(r)
                for r in await db.fetch("SELECT * FROM organisation_keys ORDER BY version DESC")
            ]
            return {
                "keys": keys,
                "activeKeyId": next((k["keyId"] for k in keys if k["state"] == "active"), None),
            }

        return await self.run(tenant, work)

    async def prepare(
        self, tenant: str, actor: str, public: bytes, expected: str | None
    ) -> dict[str, Any]:
        try:
            decode_point(public)
        except ValueError:
            raise error(422, "INVALID_KEY") from None

        async def work(db: asyncpg.Connection) -> dict[str, Any]:
            await registry_lock(db, tenant)
            await check_active(db, expected)
            kid = str(uuid.uuid4())
            version = await db.fetchval("SELECT coalesce(max(version),0)+1 FROM organisation_keys")
            fp = organisation_fingerprint(tenant, kid, version, public)
            row = await db.fetchrow(
                "INSERT INTO organisation_keys(tenant_id,key_id,version,public_key,fingerprint,state,created_at) "
                "VALUES ($1,$2,$3,$4,$5,'prepared',$6) RETURNING *",
                tenant,
                kid,
                version,
                public,
                fp,
                self.now(),
            )
            key = metadata(row)
            pid, expiry, challenge = await self.challenge(
                db, tenant, actor, "activation", key, {"expected": expected}
            )
            return {
                "preparationId": pid,
                "keyId": kid,
                "version": version,
                "fingerprint": key["fingerprint"],
                "expiresAt": expiry,
                "challengeEnvelope": challenge,
            }

        return await self.run(tenant, work)

    async def activate(self, tenant: str, actor: str, pid: str, proof: bytes) -> dict[str, Any]:
        async def work(db: asyncpg.Connection) -> dict[str, Any] | HTTPException:
            await registry_lock(db, tenant)
            row = await self.locked(db, tenant, actor, pid, "activation")
            key = metadata(
                await db.fetchrow(
                    "SELECT * FROM organisation_keys WHERE key_id=$1 FOR UPDATE", row["key_id"]
                )
            )
            expected = json.loads(row["snapshot"])["expected"]
            transcript = activation_transcript(
                tenant, actor, pid, key, expected, utc_text(row["expires_at"])
            )
            request = digest(enc(proof, "saved"))
            result = await self.verify(db, row, proof, transcript, request)
            if result is not None:
                return result
            await check_active(db, expected)
            await db.execute("UPDATE organisation_keys SET state='superseded' WHERE state='active'")
            active = await db.fetchrow(
                "UPDATE organisation_keys SET state='active', activated_at=$2 WHERE key_id=$1 RETURNING *",
                row["key_id"],
                self.now(),
            )
            return await self.committed(
                db, row, request, metadata(active), f"{key['keyId']}:{key['version']}"
            )

        return await self.run(tenant, work)

    async def cancel(self, tenant: str, actor: str, pid: str) -> None:
        async def work(db: asyncpg.Connection) -> None:
            row = await self.locked(db, tenant, actor, pid, "activation")
            if row["receipt"] is not None:
                raise error(409, "PREPARATION_USED")
            if row["sealed_nonce"] is not None:
                await db.execute(
                    "UPDATE key_preparations SET sealed_nonce=NULL WHERE preparation_id=$1", pid
                )
                await append_audit(
                    db,
                    AuditEvent(
                        tenant,
                        actor,
                        "recording.activation.cancelled",
                        f"{pid}:{row['key_id']}",
                        self.now(),
                    ),
                )

        await self.run(tenant, work)

    async def revoke(self, tenant: str, actor: str, sub: str, version: int) -> None:
        from .key_retirement import revoke_personal_version

        await self.run(
            tenant, lambda db: revoke_personal_version(db, tenant, actor, sub, version, self.now())
        )

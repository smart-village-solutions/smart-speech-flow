"""Authorised exact-scope organisation transfers. No recording objects are fetched."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from .crypto import tags
from .crypto.ecies import Sealed
from .crypto.encoding import b64url, enc, from_b64url
from .crypto.lifecycle import (
    digest,
    envelope_bytes,
    scope_digest,
    transfer_transcript,
    wraps_digest,
)
from .crypto.signatures import sign_fields
from .directory import StudioCustodianDirectory
from .organisation_keys import metadata
from .preparations import Preparations, error, utc_text
from .secrets import RecordingSecrets

_AVAILABLE = "ended_at IS NOT NULL AND shredded_at IS NULL AND (legal_hold OR retention_until>$1)"
_SOURCE = """
SELECT k.conversation_id,k.key_id,k.epoch,w.blob,w.creator_ref,w.creator_signature,s.public_key,w.recipient_ref,w.recipient_version,w.recipient_fingerprint
FROM conversation_keys k LEFT JOIN key_wraps w ON w.tenant_id=k.tenant_id AND w.key_id=k.key_id
 AND w.recipient_kind='organisation'
LEFT JOIN gateway_signing_keys s ON s.key_id=w.creator_ref
WHERE k.conversation_id=ANY($1::uuid[]) ORDER BY k.conversation_id,k.key_id LIMIT 1001
"""


def strict_wrap(wire: dict[str, Any]) -> Sealed:
    try:
        if (
            type(wire) is not dict
            or set(wire) != {"v", "t", "R", "nonce", "ct"}
            or type(wire["v"]) is not int
        ):
            raise ValueError
        sealed = Sealed.from_json(json.dumps(wire), expected_type=tags.CK_WRAP_V2)
        if (
            json.loads(sealed.to_json()) != wire
            or len(sealed.nonce) != 12
            or len(sealed.ciphertext) != 48
        ):
            raise ValueError
        return sealed
    except (TypeError, KeyError, ValueError):
        raise error(422, "INVALID_KEY") from None


async def target(db: asyncpg.Connection, sub: str) -> dict[str, Any]:
    row = await db.fetchrow(
        "SELECT user_sub,key_version,fingerprint,enc_pub,sig_pub FROM user_keys WHERE user_sub=$1 AND state='active' FOR SHARE",
        sub,
    )
    if row is None:
        raise error(409, "KEY_VERSION_CHANGED")
    return {
        "userSub": sub,
        "version": row["key_version"],
        "fingerprint": b64url(row["fingerprint"]),
        "encPub": b64url(row["enc_pub"]),
        "sigPub": b64url(row["sig_pub"]),
    }


async def organisation(db: asyncpg.Connection, kid: str) -> dict[str, Any]:
    row = await db.fetchrow(
        "SELECT * FROM organisation_keys WHERE key_id=$1 AND state IN ('active','superseded') FOR SHARE",
        kid,
    )
    if row is None:
        raise error(404, "PREPARATION_NOT_FOUND")
    return metadata(row)


async def inventory(
    db: asyncpg.Connection, ids: list[str], org: dict[str, Any], now: datetime, *, preparing: bool
) -> tuple[list[dict[str, Any]], bytes, str]:
    # Organisation, target, selected conversations (UUID order), then the preparation.
    retained = await db.fetch(
        f"SELECT conversation_id FROM conversations WHERE {_AVAILABLE} AND conversation_id=ANY($2::uuid[]) ORDER BY conversation_id FOR UPDATE",
        now,
        ids,
    )
    if len(retained) != len(ids):
        raise error(
            404 if preparing else 409, "PREPARATION_NOT_FOUND" if preparing else "SCOPE_CHANGED"
        )
    rows = await db.fetch(_SOURCE, ids)
    if len(rows) > 1000:
        raise error(
            422 if preparing else 409, "TRANSFER_SCOPE_TOO_LARGE" if preparing else "SCOPE_CHANGED"
        )
    members, keys, full_scope = [], [], []
    for row in rows:
        if not row["blob"] or not row["public_key"] or not row["recipient_fingerprint"]:
            raise error(409, "SCOPE_CHANGED")
        cid, kid = str(row["conversation_id"]), str(row["key_id"])
        source = strict_wrap(json.loads(row["blob"]))
        full_scope.append(
            enc(
                cid,
                kid,
                row["epoch"],
                row["recipient_ref"],
                row["recipient_version"],
                row["recipient_fingerprint"],
                digest(envelope_bytes(source)),
                row["creator_ref"],
                row["creator_signature"],
                row["public_key"],
            )
        )
        if (row["recipient_ref"], row["recipient_version"]) != (org["keyId"], org["version"]):
            continue
        if b64url(row["recipient_fingerprint"]) != org["fingerprint"]:
            raise error(409, "SCOPE_CHANGED")
        members.append((cid, kid, row["epoch"], source))
        keys.append(
            {
                "conversationId": cid,
                "keyId": kid,
                "epoch": row["epoch"],
                "sourceWrap": {
                    "envelope": json.loads(source.to_json()),
                    "signature": b64url(row["creator_signature"]),
                },
                "sourceSigner": {
                    "keyId": row["creator_ref"],
                    "publicKey": b64url(row["public_key"]),
                },
            }
        )
    if set(ids) != {m[0] for m in members}:
        raise error(409, "SCOPE_CHANGED")
    return keys, scope_digest(members, org), b64url(digest(enc(*full_scope)))


class AccessTransfer(Preparations):
    def __init__(
        self,
        pool: asyncpg.Pool,
        secrets: RecordingSecrets,
        directory: StudioCustodianDirectory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(pool, secrets.server_layer, clock)
        self.secrets = secrets
        self.directory = directory

    async def authorize(
        self,
        tenant: str,
        actor: str,
        permission: str | frozenset[str],
        target_sub: str | None = None,
    ) -> None:
        directory = await self.directory.snapshot(tenant, "recording-access")
        if directory is None:
            raise error(503, "RECORDING_UNAVAILABLE")
        options = (permission,) if isinstance(permission, str) else permission
        if not any(actor in directory.holders_of(option) for option in options):
            raise error(403, "PERMISSION_REQUIRED")
        if target_sub is not None and target_sub not in {u.sub for u in directory.users}:
            raise error(409, "KEY_VERSION_CHANGED")

    async def target(self, tenant: str, actor: str, sub: str) -> dict[str, Any]:
        from .permissions import TRANSFER

        await self.authorize(tenant, actor, TRANSFER, sub)
        return await self.run(tenant, lambda db: target(db, sub))

    async def candidates(
        self, tenant: str, actor: str, employee: str, cursor: str | None
    ) -> dict[str, Any]:
        from .permissions import TRANSFER

        await self.authorize(tenant, actor, TRANSFER)
        cursor_context = b64url(digest(enc(actor, employee)))
        before = None
        if cursor:
            try:
                before = str(
                    UUID(
                        self.server_layer.open_nonce(
                            from_b64url(cursor), tenant, cursor_context, "transfer-cursor"
                        ).decode()
                    )
                )
            except (ValueError, UnicodeError):
                raise error(422, "INVALID_CURSOR") from None

        async def work(db: asyncpg.Connection) -> dict[str, Any]:
            rows = await db.fetch(
                f"""
                SELECT c.conversation_id,c.started_at,c.ended_at, array_agg(DISTINCT k.key_id ORDER BY k.key_id) AS keys,
                array_agg(DISTINCT w.recipient_ref ORDER BY w.recipient_ref) AS organisations,
                jsonb_agg(jsonb_build_object('keyId',k.key_id,'organisationKeyId',w.recipient_ref) ORDER BY k.key_id) AS scopes
                FROM (SELECT * FROM conversations WHERE {_AVAILABLE} AND employee_sub=$2
                      AND ($3::uuid IS NULL OR conversation_id<$3) ORDER BY conversation_id DESC LIMIT 51) c
                JOIN conversation_keys k USING (tenant_id,conversation_id)
                LEFT JOIN key_wraps w ON w.tenant_id=k.tenant_id AND w.key_id=k.key_id AND w.recipient_kind='organisation'
                GROUP BY c.conversation_id,c.started_at,c.ended_at ORDER BY c.conversation_id DESC""",
                self.now(),
                employee,
                before,
            )
            items = [
                {
                    "conversationId": str(r["conversation_id"]),
                    "employeeSub": employee,
                    "startedAt": utc_text(r["started_at"]),
                    "endedAt": utc_text(r["ended_at"]),
                    "keyIds": [str(k) for k in r["keys"]],
                    "organisationKeyIds": [k for k in r["organisations"] if k],
                    "keyScopes": json.loads(r["scopes"]),
                }
                for r in rows[:50]
            ]
            after = (
                b64url(
                    self.server_layer.seal_nonce(
                        items[-1]["conversationId"].encode(),
                        tenant,
                        cursor_context,
                        "transfer-cursor",
                    )
                )
                if len(rows) > 50
                else None
            )
            return {"items": items, "nextCursor": after}

        return await self.run(tenant, work)

    async def prepare(
        self,
        tenant: str,
        actor: str,
        ids: list[str],
        kid: str,
        sub: str,
        version: int,
        fingerprint: str,
        reason: str,
    ) -> dict[str, Any]:
        from .permissions import TRANSFER

        if (
            not 1 <= len(ids) <= 100
            or len(set(ids)) != len(ids)
            or not reason.strip()
            or len(reason) > 1000
        ):
            raise error(422, "INVALID_SCOPE")
        await self.authorize(tenant, actor, TRANSFER, sub)

        async def work(db: asyncpg.Connection) -> dict[str, Any]:
            org = await organisation(db, kid)
            person = await target(db, sub)
            if person["version"] != version or person["fingerprint"] != fingerprint:
                raise error(409, "KEY_VERSION_CHANGED")
            keys, scope, inventory_digest = await inventory(
                db, ids, org, self.now(), preparing=True
            )
            snapshot = {
                "ids": sorted(ids),
                "inventory": inventory_digest,
                "org": org,
                "target": person,
                "reason": reason,
                "scope": b64url(scope),
                "members": [[k["conversationId"], k["keyId"]] for k in keys],
            }
            pid, expiry, challenge = await self.challenge(
                db, tenant, actor, "transfer", org, snapshot
            )
            return {
                "transferId": pid,
                "scopeDigest": b64url(scope),
                "expiresAt": expiry,
                "organisationKey": org,
                "targetKey": person,
                "challengeEnvelope": challenge,
                "keys": keys,
            }

        return await self.run(tenant, work)

    async def commit(
        self, tenant: str, actor: str, pid: str, proof: bytes, wraps: dict[tuple[str, str], Sealed]
    ) -> dict[str, Any]:
        from .permissions import TRANSFER

        async def work(db: asyncpg.Connection) -> dict[str, Any] | HTTPException:
            raw = await db.fetchval(
                "SELECT snapshot FROM key_preparations WHERE preparation_id=$1 AND actor_sub=$2 AND purpose='transfer'",
                pid,
                actor,
            )
            if raw is None:
                raise error(404, "PREPARATION_NOT_FOUND")
            snap = json.loads(raw)
            org, person = snap["org"], snap["target"]
            # Take all locks in the writers' order. Check state after the preparation
            # lock so an identical successful retry survives later key rotation.
            await db.execute(
                "SELECT 1 FROM organisation_keys WHERE key_id=$1 FOR SHARE", org["keyId"]
            )
            await db.execute(
                "SELECT 1 FROM user_keys WHERE user_sub=$1 AND key_version=$2 FOR SHARE",
                person["userSub"],
                person["version"],
            )
            await db.execute(
                "SELECT 1 FROM conversations WHERE conversation_id=ANY($1::uuid[]) ORDER BY conversation_id FOR UPDATE",
                snap["ids"],
            )
            row = await self.locked(db, tenant, actor, pid, "transfer")
            await self.authorize(tenant, actor, TRANSFER, person["userSub"])
            result_digest = wraps_digest(wraps)
            request = digest(enc(proof, result_digest))
            transcript = transfer_transcript(
                tenant,
                actor,
                pid,
                org,
                person,
                from_b64url(snap["scope"]),
                snap["reason"],
                result_digest,
                utc_text(row["expires_at"]),
            )
            if row["receipt"] is None and {tuple(m) for m in snap["members"]} != set(wraps):
                raise error(409, "SCOPE_CHANGED")
            result = await self.verify(db, row, proof, transcript, request)
            if result is not None:
                return result
            current_org = await organisation(db, org["keyId"])
            if any(
                current_org[field] != org[field]
                for field in ("version", "publicKey", "fingerprint")
            ):
                raise error(409, "KEY_VERSION_CHANGED")
            if (await target(db, person["userSub"])) != person:
                raise error(409, "KEY_VERSION_CHANGED")
            _, scope, inventory_digest = await inventory(
                db, snap["ids"], org, self.now(), preparing=False
            )
            if b64url(scope) != snap["scope"] or inventory_digest != snap["inventory"]:
                raise error(409, "SCOPE_CHANGED")
            now = self.now()
            for (cid, key_id), envelope in sorted(wraps.items()):
                context = enc(
                    tenant,
                    cid,
                    key_id,
                    "user",
                    person["userSub"],
                    person["version"],
                    from_b64url(person["fingerprint"]),
                )
                signature = sign_fields(
                    self.secrets.signing_key, tags.WRAP_SIG_V2, context, envelope_bytes(envelope)
                )
                # If this recipient previously only had an assigner-signed review
                # wrap, the independent transfer must outlive the assignment.
                await db.execute(
                    "DELETE FROM key_wraps WHERE key_id=$1 AND recipient_kind='user' AND "
                    "recipient_ref=$2 AND recipient_version=$3 AND NOT EXISTS "
                    "(SELECT 1 FROM gateway_signing_keys s WHERE s.key_id=key_wraps.creator_ref)",
                    key_id,
                    person["userSub"],
                    person["version"],
                )
                await db.execute(
                    "INSERT INTO key_wraps(tenant_id,key_id,recipient_kind,recipient_ref,blob,creator_ref,creator_signature,granted_at,recipient_version,recipient_fingerprint) "
                    "VALUES ($1,$2,'user',$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING",
                    tenant,
                    key_id,
                    person["userSub"],
                    envelope.to_json(),
                    self.secrets.signing_key_id,
                    signature,
                    now,
                    person["version"],
                    from_b64url(person["fingerprint"]),
                )
                await db.execute(
                    "INSERT INTO key_grants VALUES ($1,$2,$3,$4,'transfer',$5) ON CONFLICT DO NOTHING",
                    tenant,
                    key_id,
                    person["userSub"],
                    person["version"],
                    pid,
                )
            receipt = {
                "transferId": pid,
                "status": "committed",
                "targetUserSub": person["userSub"],
                "targetKeyVersion": person["version"],
                "scopeDigest": snap["scope"],
                "grantedKeyIds": [kid for _, kid in sorted(wraps)],
                "committedAt": utc_text(now),
            }
            return await self.committed(
                db,
                row,
                request,
                receipt,
                f"{org['keyId']}:{org['version']}:{person['userSub']}:{person['version']}:{snap['scope']}",
            )

        return await self.run(tenant, work)

"""Recording protocol generation two against an isolated migrated Postgres."""

import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
from fastapi import HTTPException

from services.api_gateway.recording.repository import bind_tenant

pytestmark = pytest.mark.integration


@pytest.fixture
async def db():
    url = os.environ.get("SSF_RECORDING_OWNER_DATABASE_URL")
    if not url:
        pytest.skip("requires isolated recording Postgres")
    conn = await asyncpg.connect(
        url, password=os.environ.get("SSF_RECORDING_OWNER_DATABASE_PASSWORD")
    )
    try:
        yield conn
    finally:
        await conn.close()


async def test_legacy_state_fails_closed_for_its_tenant(db):
    tenant = str(uuid.uuid4())
    async with db.transaction():
        await db.execute("INSERT INTO recording_protocol VALUES ($1,1)", tenant)
        with pytest.raises(HTTPException) as error:
            await bind_tenant(db, tenant)
        assert error.value.detail["error_code"] == "RECORDING_PROTOCOL_UPGRADE_REQUIRED"
        await bind_tenant(db, tenant + "-other")


async def test_activation_requires_local_open_and_idempotent_authorized_retry(db):
    import hmac
    import json

    from services.api_gateway.recording import organisation_keys as org
    from services.api_gateway.recording.crypto import ecies
    from services.api_gateway.recording.crypto.encoding import b64url, enc, from_b64url
    from services.api_gateway.recording.secrets import ServerLayer
    from tests import recording_crypto_reference as ref

    tenant, actor = str(uuid.uuid4()), "actor"
    pool = await asyncpg.create_pool(
        os.environ["SSF_RECORDING_DATABASE_URL"],
        password=os.environ.get("SSF_RECORDING_DATABASE_PASSWORD"),
        min_size=1,
        max_size=2,
    )
    try:
        service = org.OrganisationKeys(pool, ServerLayer(bytes(32)))
        public = ref.public_point(11)
        prepared = await service.prepare(tenant, actor, public, None)
        assert (await service.list(tenant))["activeKeyId"] is None
        pid, kid, version, expiry = (
            prepared[k] for k in ("preparationId", "keyId", "version", "expiresAt")
        )
        challenge = ecies.Sealed.from_json(
            json.dumps(prepared["challengeEnvelope"]), expected_type="SSF-ORG-POSSESSION-V1"
        )
        nonce = ecies.open_with_private_key(
            challenge, ref.private_key(11), (tenant, actor, pid, "activation", kid, version, expiry)
        )
        transcript = enc(
            "SSF-ORG-ACTIVATE-V1",
            tenant,
            actor,
            pid,
            kid,
            version,
            public,
            from_b64url(prepared["fingerprint"]),
            "",
            expiry,
            "saved",
        )
        proof = hmac.digest(nonce, transcript, "sha256")
        with pytest.raises(HTTPException) as wrong:
            await service.activate(tenant, actor, pid, bytes(32))
        assert wrong.value.detail["error_code"] == "INVALID_PROOF"
        result = await service.activate(tenant, actor, pid, proof)
        assert result["state"] == "active"
        assert await service.activate(tenant, actor, pid, proof) == result
        with pytest.raises(HTTPException) as replay:
            await service.activate(tenant, actor, pid, bytes(32))
        assert replay.value.detail["error_code"] == "PREPARATION_USED"
        events = await db.fetch(
            "SELECT actor_sub,event_type,object_ref FROM audit_events WHERE tenant_id=$1 ORDER BY seq",
            tenant,
        )
        assert [e["event_type"] for e in events] == [
            "recording.activation.prepared",
            "recording.activation.proof_refused",
            "recording.activation.committed",
        ]
        assert all(
            e["actor_sub"] == actor
            and pid in e["object_ref"]
            and b64url(proof) not in e["object_ref"]
            for e in events
        )
        assert await db.fetchval(
            "SELECT sealed_nonce IS NULL FROM key_preparations WHERE preparation_id=$1", pid
        )
    finally:
        await pool.close()


@pytest.mark.parametrize(
    "mutation,denied",
    [
        (None, None),
        ("permission", "PERMISSION_REQUIRED"),
        ("target", "KEY_VERSION_CHANGED"),
        ("inventory", "SCOPE_CHANGED"),
        ("source_fingerprint", "SCOPE_CHANGED"),
        ("organisation_public", "KEY_VERSION_CHANGED"),
        ("expired", "SCOPE_CHANGED"),
        ("deleted", "SCOPE_CHANGED"),
        ("wrong_actor", "PREPARATION_NOT_FOUND"),
        ("wrong_tenant", "PREPARATION_NOT_FOUND"),
        ("invalid_proof", "INVALID_PROOF"),
        ("target_left", "KEY_VERSION_CHANGED"),
    ],
)
async def test_transfer_commits_exact_scope_and_superseded_grant_survives(db, mutation, denied):
    import hmac
    import json
    from datetime import timedelta
    from types import SimpleNamespace

    from services.api_gateway.recording.access_transfer import AccessTransfer
    from services.api_gateway.recording.archive_access_repository import PostgresArchiveAccess
    from services.api_gateway.recording.archive_repository import NewKey, _insert_key
    from services.api_gateway.recording.conversation_keys import (
        Recipient,
        new_conversation_key,
        wrap_key,
    )
    from services.api_gateway.recording.crypto import ecies, tags
    from services.api_gateway.recording.crypto.encoding import b64url, from_b64url
    from services.api_gateway.recording.crypto.lifecycle import transfer_transcript, wraps_digest
    from tests import recording_crypto_reference as ref
    from tests.recording_archive_fakes import gateway_secrets

    tenant, org, cid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    pool = await asyncpg.create_pool(
        os.environ["SSF_RECORDING_DATABASE_URL"],
        password=os.environ.get("SSF_RECORDING_DATABASE_PASSWORD"),
        min_size=1,
        max_size=3,
    )
    secrets = gateway_secrets()

    class Directory:
        actor_has_access = True
        target_is_member = True

        async def snapshot(self, tenant_id, _):
            return SimpleNamespace(
                users=[SimpleNamespace(sub="bob")] if self.target_is_member else [],
                holders_of=lambda perm: {"admin"} if self.actor_has_access else set(),
            )

    try:
        await db.execute(
            "INSERT INTO gateway_signing_keys VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
            secrets.signing_key_id,
            secrets.signing_public_key,
            now,
        )
        await db.execute(
            "INSERT INTO organisation_keys VALUES ($1,$2,1,$3,$4,'active',$5,$5)",
            tenant,
            org,
            ref.public_point(11),
            bytes([1]) * 32,
            now,
        )
        for sub, n in [("alice", 12), ("bob", 15)]:
            await db.execute(
                "INSERT INTO user_keys(tenant_id,user_sub,key_version,enc_pub,sig_pub,fingerprint,created_at) VALUES ($1,$2,1,$3,$4,$5,$6)",
                tenant,
                sub,
                ref.public_point(n),
                ref.public_point(n + 1),
                bytes([n]) * 32,
                now,
            )
        await db.execute(
            "INSERT INTO conversations(tenant_id,conversation_id,session_ref,employee_sub,legal_basis,timestamp_authority_url,started_at,ended_at,retention_until) VALUES ($1,$2,'ref','alice','consent','https://tsa.example',$3,$3,$4)",
            tenant,
            cid,
            now,
            now + timedelta(days=1),
        )
        ck = new_conversation_key(1)
        wraps = tuple(
            wrap_key(
                ck,
                r,
                tenant_id=tenant,
                conversation_id=cid,
                signing_key=secrets.signing_key,
                signer_key_id=secrets.signing_key_id,
            )
            for r in [
                Recipient("organisation", org, ref.public_point(11), bytes([1]) * 32, 1),
                Recipient("user", "alice", ref.public_point(12), bytes([12]) * 32, 1),
            ]
        )
        async with pool.acquire() as conn, conn.transaction():
            await bind_tenant(conn, tenant)
            await _insert_key(conn, tenant, cid, NewKey(ck.key_id, 1, now, wraps))
        directory = Directory()
        transfer = AccessTransfer(pool, secrets, directory)
        preview = await transfer.prepare(
            tenant, "admin", [cid], org, "bob", 1, b64url(bytes([15]) * 32), "grant"
        )
        pid, expiry = preview["transferId"], preview["expiresAt"]
        challenge = ecies.Sealed.from_json(
            json.dumps(preview["challengeEnvelope"]), expected_type=tags.ORG_POSSESSION
        )
        nonce = ecies.open_with_private_key(
            challenge, ref.private_key(11), (tenant, "admin", pid, "transfer", org, 1, expiry)
        )
        source = ecies.Sealed.from_json(
            json.dumps(preview["keys"][0]["sourceWrap"]["envelope"]), expected_type=tags.CK_WRAP_V2
        )
        plain = ecies.open_with_private_key(
            source,
            ref.private_key(11),
            (tenant, cid, ck.key_id, "organisation", org, 1, bytes([1]) * 32),
        )
        assert plain == ck.secret
        result = {
            (cid, ck.key_id): ecies.seal(
                tags.CK_WRAP_V2,
                ref.public_point(15),
                plain,
                (tenant, cid, ck.key_id, "user", "bob", 1, bytes([15]) * 32),
            )
        }
        transcript = transfer_transcript(
            tenant,
            "admin",
            pid,
            preview["organisationKey"],
            preview["targetKey"],
            from_b64url(preview["scopeDigest"]),
            "grant",
            wraps_digest(result),
            expiry,
        )
        proof = hmac.digest(nonce, transcript, "sha256")
        with pytest.raises(HTTPException) as scope:
            await transfer.commit(tenant, "admin", pid, proof, {})
        assert scope.value.detail["error_code"] == "SCOPE_CHANGED"
        with pytest.raises(HTTPException) as extra:
            await transfer.commit(
                tenant,
                "admin",
                pid,
                proof,
                {**result, (cid, str(uuid.uuid4())): next(iter(result.values()))},
            )
        assert extra.value.detail["error_code"] == "SCOPE_CHANGED"
        assert not await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM key_grants WHERE tenant_id=$1 AND user_sub='bob')", tenant
        )
        if mutation:
            directory.actor_has_access = mutation != "permission"
            directory.target_is_member = mutation != "target_left"
            if mutation == "target":
                await db.execute(
                    "UPDATE user_keys SET retired_at=now(),superseded_at=now() WHERE tenant_id=$1 AND user_sub='bob'",
                    tenant,
                )
            if mutation == "source_fingerprint":
                await db.execute(
                    "UPDATE key_wraps SET recipient_fingerprint=$2 WHERE tenant_id=$1 AND recipient_kind='organisation'",
                    tenant,
                    bytes(32),
                )
            if mutation == "organisation_public":
                await db.execute(
                    "UPDATE organisation_keys SET public_key=$2 WHERE tenant_id=$1",
                    tenant,
                    ref.public_point(55),
                )
            if mutation == "inventory":
                await db.execute(
                    "UPDATE key_wraps SET creator_signature=$2 WHERE tenant_id=$1 AND recipient_kind='organisation'",
                    tenant,
                    bytes(64),
                )
            if mutation == "expired":
                await db.execute(
                    "UPDATE conversations SET retention_until=now() WHERE tenant_id=$1", tenant
                )
            if mutation == "deleted":
                await db.execute(
                    "UPDATE conversations SET shredded_at=now() WHERE tenant_id=$1", tenant
                )
            with pytest.raises(HTTPException) as refused:
                await transfer.commit(
                    tenant + "-other" if mutation == "wrong_tenant" else tenant,
                    "other" if mutation == "wrong_actor" else "admin",
                    pid,
                    bytes(32) if mutation == "invalid_proof" else proof,
                    result,
                )
            assert refused.value.detail["error_code"] == denied
            assert not await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM key_grants WHERE tenant_id=$1 AND user_sub='bob')",
                tenant,
            )
            return
        receipt = await transfer.commit(tenant, "admin", pid, proof, result)
        assert (
            receipt["grantedKeyIds"] == [ck.key_id]
            and await transfer.commit(tenant, "admin", pid, proof, result) == receipt
        )
        await db.execute(
            "UPDATE user_keys SET retired_at=$2,superseded_at=$2 WHERE tenant_id=$1 AND user_sub='bob'",
            tenant,
            now,
        )
        assert await PostgresArchiveAccess(pool).openable(tenant, "bob", cid, now)
        assert not await PostgresArchiveAccess(pool).openable(tenant + "-other", "bob", cid, now)
        await db.execute(
            "UPDATE user_keys SET superseded_at=NULL WHERE tenant_id=$1 AND user_sub='bob'", tenant
        )
        assert not await PostgresArchiveAccess(pool).openable(tenant, "bob", cid, now)
    finally:
        await pool.close()


async def test_explicit_revocation_shreds_only_selected_blob_and_preserves_signers(db):
    from services.api_gateway.recording.organisation_keys import OrganisationKeys
    from services.api_gateway.recording.repository import PostgresRecordingRepository
    from services.api_gateway.recording.secrets import ServerLayer
    from tests.recording_fakes import ref

    tenant = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    pool = await asyncpg.create_pool(
        os.environ["SSF_RECORDING_DATABASE_URL"],
        password=os.environ.get("SSF_RECORDING_DATABASE_PASSWORD"),
        min_size=1,
        max_size=2,
    )
    try:
        for v in (1, 2):
            await db.execute(
                "INSERT INTO user_keys(tenant_id,user_sub,key_version,enc_pub,sig_pub,fingerprint,created_at,retired_at,superseded_at,encrypted_private) "
                "VALUES($1,'alice',$2,$3,$4,$5,$6,$7,$7,'blob')",
                tenant,
                v,
                ref.public_point(v + 100),
                ref.public_point(v + 102),
                bytes([v]) * 32,
                now,
                now if v == 1 else None,
            )
        keys = PostgresRecordingRepository(pool)
        assert (await keys.usable_user_key(tenant, "alice", 1)).state == "superseded"
        await OrganisationKeys(pool, ServerLayer(bytes(32))).revoke(tenant, "manager", "alice", 1)
        assert await keys.usable_user_key(tenant, "alice", 1) is None
        assert (await keys.usable_user_key(tenant, "alice", 2)).state == "active"
        assert [
            (r.key_version, r.state, r.sig_pub)
            for r in await keys.user_key_versions(tenant, "alice")
        ] == [(2, "active", ref.public_point(104)), (1, "revoked", ref.public_point(103))]
    finally:
        await pool.close()


async def test_org_preparations_are_scoped_expiring_and_compare_and_swap(db):
    import asyncio
    import hmac
    import json
    from datetime import timedelta

    from services.api_gateway.recording.crypto import ecies, tags
    from services.api_gateway.recording.crypto.encoding import b64url, from_b64url
    from services.api_gateway.recording.crypto.lifecycle import activation_transcript
    from services.api_gateway.recording.organisation_keys import OrganisationKeys
    from services.api_gateway.recording.secrets import ServerLayer
    from tests import recording_crypto_reference as ref

    tenant, actor = str(uuid.uuid4()), "manager"
    now = datetime.now(timezone.utc)
    pool = await asyncpg.create_pool(
        os.environ["SSF_RECORDING_DATABASE_URL"],
        password=os.environ.get("SSF_RECORDING_DATABASE_PASSWORD"),
        min_size=1,
        max_size=4,
    )
    service = OrganisationKeys(pool, ServerLayer(bytes(32)), lambda: now)

    async def preview(n, expected=None):
        public = ref.public_point(n)
        p = await service.prepare(tenant, actor, public, expected)
        pid, kid, v, expiry = (p[k] for k in ("preparationId", "keyId", "version", "expiresAt"))
        source = ecies.Sealed.from_json(
            json.dumps(p["challengeEnvelope"]), expected_type=tags.ORG_POSSESSION
        )
        nonce = ecies.open_with_private_key(
            source, ref.private_key(n), (tenant, actor, pid, "activation", kid, v, expiry)
        )
        key = {**p, "publicKey": b64url(public)}
        return p, hmac.digest(
            nonce, activation_transcript(tenant, actor, pid, key, expected, expiry), "sha256"
        )

    try:
        p, proof = await preview(7)
        for t, a in [(tenant, "someone-else"), (tenant + "-other", actor)]:
            with pytest.raises(HTTPException) as missing:
                await service.activate(t, a, p["preparationId"], proof)
            assert missing.value.status_code == 404
        results = await asyncio.gather(
            *[service.activate(tenant, actor, p["preparationId"], proof) for _ in range(2)]
        )
        assert results[0] == results[1]
        q, qp = await preview(8, p["keyId"])
        r, rp = await preview(9, p["keyId"])
        res = await asyncio.gather(
            service.activate(tenant, actor, q["preparationId"], qp),
            service.activate(tenant, actor, r["preparationId"], rp),
            return_exceptions=True,
        )
        assert sorted(
            [x.detail["error_code"] if isinstance(x, HTTPException) else x["state"] for x in res]
        ) == ["KEY_VERSION_CHANGED", "active"]
        assert await service.activate(tenant, actor, p["preparationId"], proof) == results[0]
        active = (await service.list(tenant))["activeKeyId"]
        fresh, _ = await preview(10, active)
        for _ in range(5):
            with pytest.raises(HTTPException) as invalid:
                await service.activate(tenant, actor, fresh["preparationId"], bytes(32))
            assert invalid.value.detail["error_code"] == "INVALID_PROOF"
        with pytest.raises(HTTPException) as spent:
            await service.activate(tenant, actor, fresh["preparationId"], bytes(32))
        assert spent.value.detail["error_code"] == "PREPARATION_USED"
        expired, ep = await preview(11, active)
        now += timedelta(minutes=5)
        with pytest.raises(HTTPException) as gone:
            await service.activate(tenant, actor, expired["preparationId"], ep)
        assert gone.value.detail["error_code"] == "PREPARATION_EXPIRED"
        abandoned, ap = await preview(12, active)
        await service.cancel(tenant, actor, abandoned["preparationId"])
        with pytest.raises(HTTPException) as cancelled:
            await service.activate(tenant, actor, abandoned["preparationId"], ap)
        assert cancelled.value.detail["error_code"] == "PREPARATION_USED"
        assert (await service.list(tenant))["activeKeyId"] == active
    finally:
        await pool.close()


async def test_background_expiry_drops_unused_challenge_secrets(db):
    from services.api_gateway.recording.organisation_keys import OrganisationKeys
    from services.api_gateway.recording.secrets import ServerLayer
    from tests import recording_crypto_reference as ref

    pool = await asyncpg.create_pool(
        os.environ["SSF_RECORDING_DATABASE_URL"],
        password=os.environ.get("SSF_RECORDING_DATABASE_PASSWORD"),
        min_size=1,
        max_size=2,
    )
    try:
        service = OrganisationKeys(pool, ServerLayer(bytes(32)))
        expired = await service.prepare(str(uuid.uuid4()), "a", ref.public_point(10), None)
        unexpired = await service.prepare(str(uuid.uuid4()), "b", ref.public_point(20), None)
        await db.execute(
            "UPDATE key_preparations SET expires_at=now() WHERE preparation_id=$1",
            expired["preparationId"],
        )
        await service.expire_secrets()
        for record, expected in ((expired, False), (unexpired, True)):
            assert (
                await db.fetchval(
                    "SELECT sealed_nonce IS NOT NULL FROM key_preparations WHERE preparation_id=$1",
                    record["preparationId"],
                )
                == expected
            )
    finally:
        await pool.close()

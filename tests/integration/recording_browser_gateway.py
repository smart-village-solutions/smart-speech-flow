"""Loopback Keycloak/Gateway/Studio acceptance fixture, with an isolated recording database.

Set KEYCLOAK_BASE_URL, SSF_RECORDING_DATABASE_URL/PASSWORD and SSF_AUDIO_BASE_DIR.
The disposable database ssf_gateway_browser_test must already have all migrations.
Run as a module with 'serve' or 'seed TENANT EMPLOYEE TARGET ACTIVE_ORG_ID'.
The JSON directory is local fixture input. All bearer validation and crypto are real.
"""

import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI
from prometheus_client import CollectorRegistry

from services.api_gateway.dependencies import build_gateway_dependencies
from services.api_gateway.recording.access_transfer import AccessTransfer
from services.api_gateway.recording.archive_repository import (
    ConversationRecord,
    NewKey,
    PostgresArchiveRepository,
    WindowOpening,
)
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.chain import seal_entry
from services.api_gateway.recording.conversation_keys import (
    Recipient,
    new_conversation_key,
    wrap_key,
)
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.keys import Enrolment, KeyEnrolmentService, sealed_record
from services.api_gateway.recording.organisation_keys import OrganisationKeys
from services.api_gateway.recording.repository import PostgresRecordingRepository, UserKeyRecord
from services.api_gateway.routes.recording import router
from services.api_gateway.studio_recording_directory_client import RecordingDirectory
from tests import recording_crypto_reference as ref
from tests.recording_archive_fakes import gateway_secrets
from tests.recording_fakes import sealed_blob

path = Path(os.environ.get("SSF_BROWSER_DIRECTORY", "/tmp/ssf-dashboard-browser-directory.json"))


async def repository():
    base = os.environ["SSF_RECORDING_DATABASE_URL"]
    if urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("requires loopback test database")
    return await PostgresRecordingRepository.create(
        dsn=base.rsplit("/", 1)[0] + "/ssf_gateway_browser_test",
        password=os.environ["SSF_RECORDING_DATABASE_PASSWORD"],
    )


def tenants():
    return json.loads(path.read_text())["tenants"] if path.is_file() else []


class Login:
    async def get(self, correlation):
        return SimpleNamespace(
            tenants=[SimpleNamespace(id=r["id"], realm=r["realm"]) for r in tenants()]
        )


class Membership:
    async def snapshot(self, tenant, correlation):
        row = next((r for r in tenants() if r["id"] == tenant), None)
        if not row:
            return None
        return RecordingDirectory.model_validate(
            {
                "contractVersion": "2.0",
                "tenantId": tenant,
                "directoryRevision": "sha256:" + "0" * 64,
                "users": [{**u, "displayName": "Browser fixture"} for u in row["users"]],
            }
        )


@asynccontextmanager
async def lifespan(app):
    state = build_gateway_dependencies(
        prometheus_registry=CollectorRegistry(), translation_refiner=None
    )
    app.state.dependencies = state
    state.login_directory = Login()
    repo = await repository()
    secret = gateway_secrets()
    from datetime import datetime, timezone

    await repo.register_gateway_key(
        secret.signing_key_id, secret.signing_public_key, datetime.now(timezone.utc)
    )
    state.recording_keys = KeyEnrolmentService(repository=repo, server_layer=secret.server_layer)
    state.recording_organisation_keys = OrganisationKeys(repo.pool, secret.server_layer)
    state.recording_access_transfer = AccessTransfer(repo.pool, secret, Membership())
    yield
    await repo.close()


app = FastAPI(lifespan=lifespan)
app.include_router(router)


async def seed(tenant, employee, target, expected_org):
    repo = await repository()
    now = datetime.now(timezone.utc)
    signer = gateway_secrets()
    try:
        registr = OrganisationKeys(repo.pool, signer.server_layer)
        org = await registr.active_recipient(tenant)
        if org is None or org.ref != expected_org:
            raise RuntimeError("fixture organisation does not match")
        user_versions = {}
        for sub in dict.fromkeys((employee, target)):
            current = await repo.active_user_key(tenant, sub)
            if current is None:
                enrol = Enrolment(
                    ref.public_point(11), ref.public_point(12), sealed_blob(tenant, sub)
                )
                record = sealed_record(signer.server_layer, tenant, sub, enrol, version=1, now=now)
                await repo.enrol_user_key(record)
                current = await repo.active_user_key(tenant, sub)
            user_versions[sub] = current
        person = user_versions[employee]
        cid, wid = str(uuid.uuid4()), str(uuid.uuid4())
        conv = ConversationRecord(
            tenant,
            cid,
            "browser-fixture-" + cid,
            employee,
            "consent",
            "https://tsa.example",
            now,
            now + timedelta(days=1),
        )
        ck = new_conversation_key(1)
        recipients = (
            org,
            Recipient("user", employee, person.enc_pub, person.fingerprint, person.key_version),
        )
        wraps = tuple(
            wrap_key(
                ck,
                r,
                tenant_id=tenant,
                conversation_id=cid,
                signing_key=signer.signing_key,
                signer_key_id=signer.signing_key_id,
            )
            for r in recipients
        )
        entry = seal_entry(
            tenant_id=tenant,
            conversation_id=cid,
            seq=1,
            entry_id=str(uuid.uuid4()),
            kind="consent",
            window_id=wid,
            key_id=ck.key_id,
            objects=(),
            prev_hash=bytes(32),
            created_at=now,
            signing_key=signer.signing_key,
            signer_key_id=signer.signing_key_id,
        )
        archive = PostgresArchiveRepository(repo.pool)
        await archive.open_window(
            WindowOpening(
                conv,
                True,
                wid,
                now,
                NewKey(ck.key_id, 1, now, wraps),
                entry,
                AuditEvent(tenant, employee, "recording.arming", wid, now),
            )
        )
        await archive.close_window(tenant, cid, wid, now, "stopped_by_employee")
        await archive.end_conversation(tenant, cid, now)
        target_key = user_versions[target]
        print(
            json.dumps(
                {
                    "conversationId": cid,
                    "keyId": ck.key_id,
                    "targetKeyVersion": target_key.key_version,
                    "targetFingerprint": b64url(target_key.fingerprint),
                }
            )
        )
    finally:
        await repo.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["serve"]:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=int(os.environ.get("SSF_BROWSER_PORT", "55441")),
            access_log=False,
            log_level="warning",
        )
    elif len(sys.argv) == 6 and sys.argv[1] == "seed":
        asyncio.run(seed(*sys.argv[2:]))
    else:
        raise SystemExit("serve | seed TENANT EMPLOYEE TARGET ACTIVE_ORG_ID")

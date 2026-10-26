"""In-memory stand-ins for the recording database, shared by the recording tests."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.repository import KeyAlreadyEnrolled, UserKeyRecord
from tests import recording_crypto_reference as ref


@dataclass
class FakeRecordingRepository:
    keys: dict[tuple[str, str], UserKeyRecord] = field(default_factory=dict)
    audit: list[AuditEvent] = field(default_factory=list)

    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None:
        return self.keys.get((tenant_id, user_sub))

    async def enrol_user_key(self, record: UserKeyRecord, audit: AuditEvent) -> None:
        if (record.tenant_id, record.user_sub) in self.keys:
            raise KeyAlreadyEnrolled()
        self.keys[(record.tenant_id, record.user_sub)] = record
        self.audit.append(audit)

    async def record_audit(self, event: AuditEvent) -> None:
        self.audit.append(event)


def sealed_blob(tenant_id: str = "tenant-test", user_sub: str = "alice") -> str:
    """A blob with the enrolment work factor; the gateway checks only its shape."""
    return ref.seal_private_keys(
        "Kanne Wolke Ferne Tisch 42",
        tenant_id,
        user_sub,
        {"enc": ref.pkcs8(11), "sig": ref.pkcs8(12)},
        salt=os.urandom(16),
        nonces={"enc": os.urandom(12), "sig": os.urandom(12)},
        params=(65536, 3, 1),
    )


def enrolment_body(tenant_id: str = "tenant-test", user_sub: str = "alice") -> dict[str, str]:
    return {
        "enc_pub": b64url(ref.public_point(11)),
        "sig_pub": b64url(ref.public_point(12)),
        "blob": sealed_blob(tenant_id, user_sub),
    }


def with_kdf(blob: str, **overrides: object) -> str:
    body = json.loads(blob)
    body["kdf"].update(overrides)
    return json.dumps(body)

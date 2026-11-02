"""Keys, grants, notes and directories for the #619 tests, with real crypto."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from services.api_gateway.recording.crypto import aead, ecies, tags
from services.api_gateway.recording.crypto.signatures import (
    sign_fields,
    signed_digest,
    wrap_fields,
)
from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.crypto.verification import (
    note_aad,
    notes_digest,
    verification_fields,
)
from services.api_gateway.recording.verification_model import AssignWrap, KeyRow, NotePost
from services.api_gateway.studio_recording_directory_client import RecordingDirectory
from services.studio_mock.contract_fixtures import revision
from tests import recording_crypto_reference as ref

TENANT = "tenant-a"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Person:
    key: KeyRow
    enc_scalar: int
    sig_scalar: int

    @property
    def sub(self) -> str:
        return self.key.sub


def person(sub: str, seed: int, version: int = 1, tenant_id: str = TENANT) -> Person:
    enc_scalar, sig_scalar = 1000 + seed, 2000 + seed
    enc_pub, sig_pub = ref.public_point(enc_scalar), ref.public_point(sig_scalar)
    key = KeyRow(sub, version, fingerprint(tenant_id, sub, enc_pub, sig_pub), enc_pub, sig_pub)
    return Person(key, enc_scalar, sig_scalar)


def grant(
    conversation_id: str,
    key_id: str,
    signer: Person,
    reviewer: Person,
    *,
    tenant_id: str = TENANT,
) -> AssignWrap:
    context = ecies.ck_wrap_context(tenant_id, conversation_id, key_id, "user", reviewer.sub)
    sealed = ecies.seal(tags.CK_WRAP, reviewer.key.enc_pub, os.urandom(32), context)
    fields = wrap_fields(
        tenant_id,
        conversation_id,
        key_id,
        sealed.ephemeral,
        "user",
        reviewer.sub,
        reviewer.key.fingerprint,
    )
    signature = sign_fields(ref.private_key(signer.sig_scalar), tags.WRAP_SIG, *fields)
    return AssignWrap(key_id, sealed.to_json(), signature)


def directory(*users: tuple[str, Sequence[str]], tenant_id: str = TENANT) -> RecordingDirectory:
    body = {
        "contractVersion": "2.0",
        "tenantId": tenant_id,
        "users": [
            {
                "sub": sub,
                "displayName": sub.title(),
                "permissions": list(permissions),
                "languages": ["de", "tr"],
            }
            for sub, permissions in users
        ],
    }
    body["directoryRevision"] = revision(body)
    return RecordingDirectory.model_validate(body)


def sealed_note(
    key: bytes,
    conversation_id: str,
    verification_id: str,
    entry_id: str,
    key_id: str,
    *,
    part: str = "note",
    tenant_id: str = TENANT,
) -> bytes:
    aad = note_aad(tenant_id, conversation_id, verification_id, part, entry_id, key_id)  # type: ignore[arg-type]
    return aead.seal(key, b'{"v":1}', aad)


def decision_signature(
    reviewer: Person,
    conversation_id: str,
    verification_id: str,
    reviewed_head: bytes,
    outcome: str,
    overall: bytes | None,
    notes: Sequence[NotePost],
    snapshot: Sequence[str],
    *,
    tenant_id: str = TENANT,
) -> tuple[bytes, bytes]:
    """The browser's signature over a decision, and the digest it signed."""
    digest = notes_digest(overall, [(n.entry_id, n.key_id, n.ciphertext) for n in notes])
    fields = verification_fields(
        tenant_id, verification_id, conversation_id, reviewed_head, outcome, digest, snapshot
    )
    signature = sign_fields(ref.private_key(reviewer.sig_scalar), tags.VERIFICATION_SIG, *fields)
    return signature, signed_digest(tags.VERIFICATION_SIG, *fields)

"""Conversation keys and their wraps (spec §8.1, §8.2, Appendix A.3, A.4, A.6).

A conversation key lives in gateway memory only. Before anything is
encrypted under it, it is wrapped to the public keys of whoever may open the
conversation later, and each wrap is signed by the gateway, so a browser
re-wraps only keys the gateway vouched for. The gateway itself can never
unwrap them: it holds no matching private key.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Final, Literal

from cryptography.hazmat.primitives.asymmetric import ec

from .crypto import aead, ecies, tags
from .crypto.signatures import sign_fields, wrap_fields

RecipientKind = Literal["user", "recovery"]
_KEY_BYTES: Final[int] = 32


@dataclass(frozen=True)
class ConversationKey:
    key_id: str
    epoch: int
    # Kept out of repr, so no log or traceback ever prints it.
    secret: bytes = field(repr=False)


@dataclass(frozen=True)
class Recipient:
    kind: RecipientKind
    ref: str  # the user's sub, or the recovery key's ID
    public_key: bytes
    # A user's key fingerprint, or the transcript hash that certifies a recovery key.
    fingerprint: bytes


@dataclass(frozen=True)
class KeyWrap:
    key_id: str
    recipient_kind: RecipientKind
    recipient_ref: str
    blob: str
    creator_ref: str
    creator_signature: bytes
    # The user key the wrap is sealed to; checked again when the wrap is stored (§9.6).
    recipient_fingerprint: bytes | None = None


def new_conversation_key(epoch: int) -> ConversationKey:
    return ConversationKey(str(uuid.uuid4()), epoch, os.urandom(_KEY_BYTES))


def wrap_key(
    key: ConversationKey,
    recipient: Recipient,
    *,
    tenant_id: str,
    conversation_id: str,
    signing_key: ec.EllipticCurvePrivateKey,
    signer_key_id: str,
) -> KeyWrap:
    context = ecies.ck_wrap_context(
        tenant_id, conversation_id, key.key_id, recipient.kind, recipient.ref
    )
    sealed = ecies.seal(tags.CK_WRAP, recipient.public_key, key.secret, context)
    signed = wrap_fields(
        tenant_id,
        conversation_id,
        key.key_id,
        sealed.ephemeral,
        recipient.kind,
        recipient.ref,
        recipient.fingerprint,
    )
    return KeyWrap(
        key_id=key.key_id,
        recipient_kind=recipient.kind,
        recipient_ref=recipient.ref,
        blob=sealed.to_json(),
        creator_ref=signer_key_id,
        creator_signature=sign_fields(signing_key, tags.WRAP_SIG, *signed),
        recipient_fingerprint=recipient.fingerprint if recipient.kind == "user" else None,
    )


def seal_object(
    key: ConversationKey,
    plaintext: bytes,
    *,
    tenant_id: str,
    conversation_id: str,
    entry_id: str,
    object_type: str,
) -> bytes:
    """A.3: the associated data pins the object to its tenant, conversation, entry, type and key."""
    aad = aead.object_aad(tenant_id, conversation_id, entry_id, object_type, key.key_id)
    return aead.seal(key.secret, plaintext, aad)

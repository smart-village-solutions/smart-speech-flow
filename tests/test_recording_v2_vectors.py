"""Shared known answers generated independently of the Gateway protocol implementation."""

import hmac
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import load_der_private_key

from services.api_gateway.recording.conversation_keys import ConversationKey, Recipient, wrap_key
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.encoding import b64url, enc, from_b64url
from services.api_gateway.recording.crypto.lifecycle import (
    activation_transcript,
    envelope_bytes,
    organisation_fingerprint,
    scope_digest,
    transfer_transcript,
    wraps_digest,
)
from services.api_gateway.recording.crypto.signatures import verify_fields
from tests import recording_crypto_reference as ref

V = json.loads((Path(__file__).parent / "fixtures/recording/lifecycle_v2.json").read_text())


def test_vector_decrypt_verify_and_rewrap():
    tenant = V["tenantId"]
    org = {
        "keyId": V["organisationKeyId"],
        "version": V["organisationVersion"],
        "publicKey": V["organisationPublicKey"],
        "fingerprint": V["organisationFingerprint"],
    }
    target = {
        "userSub": V["targetUserSub"],
        "version": V["targetVersion"],
        "fingerprint": V["targetFingerprint"],
    }
    actor, expiry = V["actorSub"], V["expiresAt"]
    cid, kid = V["conversationId"], V["keyId"]
    assert (
        b64url(
            organisation_fingerprint(
                tenant, org["keyId"], org["version"], from_b64url(org["publicKey"])
            )
        )
        == org["fingerprint"]
    )
    org_private = load_der_private_key(from_b64url(V["organisationPrivateKeyPkcs8"]), None)
    user_private = load_der_private_key(from_b64url(V["targetPrivateKeyPkcs8"]), None)

    def opened(field, tag, key, context):
        sealed = ecies.Sealed.from_json(json.dumps(V[field]), expected_type=tag)
        plain = ecies.open_with_private_key(sealed, key, context)
        with pytest.raises(ecies.SealedPayloadError):
            ecies.open_with_private_key(sealed, key, (*context[:-1], "changed"))
        return sealed, plain

    _, nonce = opened(
        "activationChallenge",
        tags.ORG_POSSESSION,
        org_private,
        (tenant, actor, V["preparationId"], "activation", org["keyId"], org["version"], expiry),
    )
    a = activation_transcript(tenant, actor, V["preparationId"], org, None, expiry)
    assert b64url(a) == V["activationTranscript"]
    assert b64url(hmac.digest(nonce, a, "sha256")) == V["activationProof"]
    oc = (
        tenant,
        cid,
        kid,
        "organisation",
        org["keyId"],
        org["version"],
        from_b64url(org["fingerprint"]),
    )
    tc = (
        tenant,
        cid,
        kid,
        "user",
        target["userSub"],
        target["version"],
        from_b64url(target["fingerprint"]),
    )
    src, ck = opened("sourceEnvelope", tags.CK_WRAP_V2, org_private, oc)
    dst, key = opened("targetEnvelope", tags.CK_WRAP_V2, user_private, tc)
    assert b64url(ck) == b64url(key) == V["contentKey"]
    scope = scope_digest([(cid, kid, V["epoch"], src)], org)
    result = wraps_digest({(cid, kid): dst})
    assert b64url(scope) == V["scopeDigest"] and b64url(result) == V["resultDigest"]
    transcript = transfer_transcript(
        tenant, actor, V["transferId"], org, target, scope, V["reason"], result, expiry
    )
    assert b64url(transcript) == V["transferTranscript"]
    assert b64url(hmac.digest(nonce, transcript, "sha256")) == V["transferProof"]
    assert verify_fields(
        from_b64url(V["gatewayPublicKey"]),
        from_b64url(V["sourceSignature"]),
        tags.WRAP_SIG_V2,
        enc(*oc),
        envelope_bytes(src),
    )
    wrap = wrap_key(
        ConversationKey(kid, 1, ck),
        Recipient(
            "user",
            target["userSub"],
            from_b64url(V["targetEncPub"]),
            from_b64url(target["fingerprint"]),
            target["version"],
        ),
        tenant_id=tenant,
        conversation_id=cid,
        signing_key=ref.private_key(103),
        signer_key_id="gateway",
    )
    sealed = ecies.Sealed.from_json(wrap.blob, expected_type=tags.CK_WRAP_V2)
    assert ecies.open_with_private_key(sealed, user_private, tc) == ck
    assert verify_fields(
        from_b64url(V["gatewayPublicKey"]),
        wrap.creator_signature,
        tags.WRAP_SIG_V2,
        enc(*tc),
        envelope_bytes(sealed),
    )

"""What custodians' browsers and the ceremony device do, in Python, for gateway tests.

Mirrors services/frontend/src/core/crypto/ceremony.ts. Test-only: nothing
under services/ imports it, and no production path holds a share.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from services.api_gateway.recording.ceremony_model import CeremonySnapshot, DealingSubmission
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.curve import ORDER
from services.api_gateway.recording.crypto.encoding import scalar_from_bytes, scalar_to_bytes
from services.api_gateway.recording.crypto.proofs import verify_subshare
from services.api_gateway.recording.crypto.signatures import dealing_fields, sign_fields
from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.repository import UserKeyRecord
from services.api_gateway.recording.secrets import RecordingSecrets, ServerLayer, gateway_key_id
from tests import recording_crypto_reference as ref

TENANT = "tenant-test"


@dataclass(frozen=True)
class Holder:
    """A custodian (enc and sig keys) or the ceremony device (enc key only)."""

    sub: str
    enc_scalar: int
    sig_scalar: int = 0

    @property
    def enc_pub(self) -> bytes:
        return ref.public_point(self.enc_scalar)

    def key_record(self, tenant_id: str = TENANT) -> UserKeyRecord:
        sig_pub = ref.public_point(self.sig_scalar)
        return UserKeyRecord(
            tenant_id=tenant_id,
            user_sub=self.sub,
            key_version=1,
            enc_pub=self.enc_pub,
            sig_pub=sig_pub,
            fingerprint=fingerprint(tenant_id, self.sub, self.enc_pub, sig_pub),
            encrypted_private=b"\x01" + bytes(40),
            created_at=datetime(2026, 10, 26, tzinfo=timezone.utc),
        )

    def deal(
        self, snapshot: CeremonySnapshot, coefficients: list[int], nonce: int = 4242
    ) -> DealingSubmission:
        ceremony = snapshot.ceremony
        index = next(p.holder_index for p in snapshot.custodians if p.holder_ref == self.sub)
        commitments = ref.commitments(coefficients)
        c, s = ref.schnorr_prove(
            ceremony.tenant_id, ceremony.ceremony_id, index, coefficients[0], nonce
        )
        subshares = {
            p.holder_index: ecies.seal(
                tags.SUBSHARE,
                p.enc_pub,
                scalar_to_bytes(ref.evaluate(coefficients, p.holder_index)),
                ecies.subshare_context(
                    ceremony.tenant_id, ceremony.ceremony_id, index, p.holder_index
                ),
            ).to_json()
            for p in snapshot.participants
        }
        return DealingSubmission(
            commitments=commitments,
            proof_c=c,
            proof_s=s,
            signature=self.dealing_signature(snapshot, commitments, c, s),
            subshares=subshares,
        )

    def dealing_signature(
        self, snapshot: CeremonySnapshot, commitments: tuple[bytes, ...], c: int, s: int
    ) -> bytes:
        ceremony = snapshot.ceremony
        index = next(p.holder_index for p in snapshot.custodians if p.holder_ref == self.sub)
        signed = dealing_fields(ceremony.tenant_id, ceremony.ceremony_id, index, commitments, c, s)
        return sign_fields(ref.private_key(self.sig_scalar), tags.DEALING_SIG, *signed)

    def share(self, snapshot: CeremonySnapshot, index: int, received: Mapping[int, str]) -> int:
        """x_i = Σ_j f_j(i), each sub-share checked against its dealer's commitments."""
        ceremony = snapshot.ceremony
        dealings = {d.dealer_index: d for d in snapshot.dealings}
        total = 0
        for dealer, text in received.items():
            sealed = ecies.Sealed.from_json(text, expected_type=tags.SUBSHARE)
            context = ecies.subshare_context(
                ceremony.tenant_id, ceremony.ceremony_id, dealer, index
            )
            value = scalar_from_bytes(
                ecies.open_with_private_key(sealed, ref.private_key(self.enc_scalar), context)
            )
            assert verify_subshare(index, value, dealings[dealer].commitments)
            total = (total + value) % ORDER
        return total

    def confirmation(
        self, snapshot: CeremonySnapshot, index: int, share: int, transcript_hash: bytes
    ) -> tuple[bytes, str]:
        ceremony = snapshot.ceremony
        sealed = ecies.seal(
            tags.SHARE,
            self.enc_pub,
            scalar_to_bytes(share),
            ecies.share_context(ceremony.tenant_id, ceremony.ceremony_id, index, self.sub),
        )
        signature = sign_fields(ref.private_key(self.sig_scalar), tags.TRANSCRIPT, transcript_hash)
        return signature, sealed.to_json()


ANNA = Holder("anna", 101, 201)
BERND = Holder("bernd", 102, 202)
CARLA = Holder("carla", 103, 203)
DEVICE = Holder("device", 104)
ORG_ADMIN = "olga"
POLYNOMIALS = {"anna": [11, 12], "bernd": [21, 22], "carla": [31, 32]}
GATEWAY_SCALAR = 77


def gateway_secrets() -> RecordingSecrets:
    public = ref.public_point(GATEWAY_SCALAR)
    return RecordingSecrets(
        signing_key=ref.private_key(GATEWAY_SCALAR),
        signing_key_id=gateway_key_id(public),
        signing_public_key=public,
        server_layer=ServerLayer(os.urandom(32)),
    )

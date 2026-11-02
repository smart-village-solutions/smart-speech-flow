"""Decision timestamps: the imprint, back-off and failures (spec §10.7, A.3a)."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from services.api_gateway.recording.archive_service import STAMP_RETRY_INITIAL
from services.api_gateway.recording.crypto import tags
from services.api_gateway.recording.crypto.signatures import signed_digest
from services.api_gateway.recording.crypto.verification import verification_fields
from services.api_gateway.recording.decision_stamps import DecisionStamper, imprint_of
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.timestamps import Timestamp, TimestampUnavailableError
from services.api_gateway.recording.verification_model import PendingDecisionStamp
from tests.recording_verification_world import NOW, TENANT

STAMP = PendingDecisionStamp(
    verification_id="v-1",
    conversation_id="c-1",
    reviewed_head=b"\x05" * 32,
    outcome="approved",
    notes_digest=b"\x06" * 32,
    permission_snapshot=("ssf.recording.review",),
    signature=b"\x07" * 64,
    url="https://tsa.test/tsr",
    attempts=2,
)


class Store:
    def __init__(self, due=(STAMP,), down=False) -> None:
        self.due, self.down = list(due), down
        self.saved: list = []
        self.deferred: list = []

    async def pending_decision_stamps(self, tenant_id, now, limit=20):
        if self.down:
            raise RecordingStorageUnavailable("down")
        return self.due

    async def save_decision_stamp(self, tenant_id, stamp, token, stamped_at):
        self.saved.append((stamp.verification_id, token, stamped_at))

    async def defer_decision_stamp(self, tenant_id, stamp, next_attempt_at):
        self.deferred.append((stamp.verification_id, next_attempt_at))


class Authority:
    def __init__(self, fail=None) -> None:
        self.fail, self.digests = fail, []

    async def stamp(self, url, digest):
        self.digests.append((url, digest))
        if self.fail is not None:
            raise self.fail
        return Timestamp(b"token", NOW)


def test_the_imprint_covers_the_signed_digest_and_the_signature():
    fields = verification_fields(
        TENANT, "v-1", "c-1", b"\x05" * 32, "approved", b"\x06" * 32, ["ssf.recording.review"]
    )
    expected = hashlib.sha256(signed_digest(tags.VERIFICATION_SIG, *fields) + b"\x07" * 64).digest()
    assert imprint_of(TENANT, STAMP) == expected


async def test_a_token_is_saved_for_the_imprint():
    store, authority = Store(), Authority()
    await DecisionStamper(store, authority, lambda: [TENANT], lambda: NOW).run_once()
    assert authority.digests == [("https://tsa.test/tsr", imprint_of(TENANT, STAMP))]
    assert store.saved == [("v-1", b"token", NOW)] and store.deferred == []


async def test_a_failed_authority_defers_with_back_off_and_a_down_store_skips():
    store = Store()
    await DecisionStamper(
        store,
        Authority(TimestampUnavailableError("tsa_unavailable")),
        lambda: [TENANT],
        lambda: NOW,
    ).run_once()
    assert store.deferred == [("v-1", NOW + STAMP_RETRY_INITIAL * 4)]
    other = Store()
    await DecisionStamper(
        other, Authority(ValueError("x")), lambda: [TENANT], lambda: NOW
    ).run_once()
    assert other.deferred[0][1] - NOW == timedelta(seconds=120)
    down = Store(down=True)
    await DecisionStamper(down, Authority(), lambda: [TENANT, "other"], lambda: NOW).run_once()
    assert down.saved == []

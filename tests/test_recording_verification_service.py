"""The verification service: directory reads, signature checks and refusals (spec §10.7)."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest

from services.api_gateway.recording.archive_access import ArchiveAccessError
from services.api_gateway.recording.recovery_requests_model import Refused
from services.api_gateway.recording.repository import RecordingStorageUnavailable
from services.api_gateway.recording.verification import VerificationError, Verifications
from services.api_gateway.recording.verification_model import (
    AssignRequest,
    InboxRow,
    VerificationRow,
)
from tests.recording_verification_world import NOW, TENANT, directory, grant, person

CONVERSATION = str(uuid.uuid4())
KEY_1, KEY_2 = sorted(str(uuid.uuid4()) for _ in range(2))
ALICE, RITA, RALF = person("alice", 1), person("rita", 2), person("ralf", 3)
REVIEWER = ["ssf.recording.review"]
SWORN = ["ssf.recording.review", "ssf.recording.review.sworn"]


class FakeDirectory:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)

    async def snapshot(self, tenant_id, correlation_id):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class FakeAccess:
    def __init__(self, openable: bool = True) -> None:
        self.openable, self.refused = openable, []

    async def require_openable(self, tenant_id, sub, conversation_id, *, supervisor=False):
        if not self.openable:
            self.refused.append(conversation_id)
            raise ArchiveAccessError("not_found")

    async def refuse(self, tenant_id, sub, conversation_ref):
        self.refused.append(conversation_ref)
        return ArchiveAccessError("not_found")

    def mark_opened(self, tenant_id, sub, conversation_id):
        self.opened = (sub, conversation_id)

    async def names_of(self, tenant_id, subs, correlation_id):
        return {"alice": "Alice Employee"} if "alice" in subs else {}


class FakeStore:
    def __init__(self, *, keys=(ALICE, RITA, RALF), excluded=frozenset(), assigned=None) -> None:
        self.keys = {p.sub: p.key for p in keys}
        self._excluded = excluded
        self.assigned = assigned
        self.assignments: list = []
        self.down = False
        self.review_calls: list = []
        self.opened = None
        self.answer = None
        self.record = None
        self.decisions: list = []

    async def inbox(self, tenant_id, sub, now):
        return [InboxRow("v-1", "awaiting", now, "alice", now, None, 2, True)]

    async def open_review(self, tenant_id, sub, verification_id, now, *, reviewer):
        self.review_calls.append((sub, verification_id, reviewer))
        return self.opened

    async def start(self, tenant_id, sub, verification_id, expected_head_seq, snapshot, now):
        self.review_calls.append(("start", expected_head_seq, tuple(snapshot)))
        return self.answer or opened_review().record

    async def save_draft(self, tenant_id, sub, verification_id, overall, notes, now):
        self.review_calls.append(("draft", overall, tuple(notes)))
        return self.answer

    async def decline(self, tenant_id, sub, verification_id, now):
        self.review_calls.append(("decline", verification_id))
        return self.answer

    async def record_of(self, tenant_id, sub, verification_id):
        return self.record

    async def decide(self, tenant_id, sub, verification_id, decision, now):
        self.decisions.append(decision)
        return self.answer or dataclasses.replace(
            self.record, status=decision.outcome, outcome=decision.outcome
        )

    async def excluded(self, tenant_id, conversation_id, subs):
        if self.down:
            raise RecordingStorageUnavailable("down")
        return frozenset(subs) & self._excluded

    async def active_keys(self, tenant_id, subs):
        return {sub: self.keys[sub] for sub in subs if sub in self.keys}

    async def assign(self, assignment, now, *, supervisor):
        self.assignments.append((assignment, supervisor))
        return self.assigned or VerificationRow(
            verification_id="v-1",
            conversation_id=assignment.conversation_id,
            status="awaiting",
            requested_by=assignment.requester_sub,
            requester_key_version=1,
            requested_at=now,
            directory_read_at=assignment.directory_read_at,
            reviewer_sub=assignment.reviewer_sub,
            reviewer_key_version=1,
            reviewer_fingerprint=assignment.reviewer_fingerprint,
        )


def service(store=None, studio=None, access=None) -> Verifications:
    return Verifications(
        store=store or FakeStore(),
        directory=studio
        or FakeDirectory(directory(("rita", SWORN), ("ralf", REVIEWER), ("alice", REVIEWER))),
        access=access or FakeAccess(),
        clock=lambda: NOW,
    )


def request(*, wraps=None, reviewer=RITA, key_version=1, reviewer_version=1) -> AssignRequest:
    return AssignRequest(
        key_version=key_version,
        reviewer_sub=reviewer.sub,
        reviewer_key_version=reviewer_version,
        wraps=(
            wraps
            if wraps is not None
            else tuple(grant(CONVERSATION, key, ALICE, reviewer) for key in (KEY_1, KEY_2))
        ),
    )


async def test_candidates_are_reviewers_with_keys_minus_the_excluded_in_name_order():
    store = FakeStore(keys=(ALICE, RITA, RALF, person("zoe", 9)), excluded=frozenset({"alice"}))
    studio = FakeDirectory(
        directory(
            ("zoe", REVIEWER),
            ("rita", SWORN),
            ("ralf", REVIEWER),
            ("alice", REVIEWER),
            ("nokey", REVIEWER),
            ("sam", ["ssf.recording.supervise"]),
        )
    )

    found = await service(store, studio).candidates(
        TENANT, "alice", CONVERSATION, "c", supervisor=False
    )

    assert [(c.sub, c.sworn) for c in found] == [("ralf", False), ("rita", True), ("zoe", False)]
    assert found[1].key == RITA.key and found[1].languages == ("de", "tr")


async def test_candidates_need_the_opening_rule_and_a_readable_directory():
    access = FakeAccess(openable=False)
    with pytest.raises(VerificationError, match="not_found"):
        await service(access=access).candidates(TENANT, "bob", CONVERSATION, "c", supervisor=False)
    assert access.refused == [CONVERSATION]
    with pytest.raises(VerificationError, match="directory_unavailable"):
        await service(studio=FakeDirectory(None)).candidates(
            TENANT, "alice", CONVERSATION, "c", supervisor=False
        )
    down = FakeStore()
    down.down = True
    with pytest.raises(VerificationError, match="unavailable"):
        await service(store=down).candidates(TENANT, "alice", CONVERSATION, "c", supervisor=False)


async def test_an_assignment_reaches_the_store_with_the_reviewers_key_and_read_time():
    store = FakeStore()

    row = await service(store).assign(
        TENANT, "alice", CONVERSATION, request(), "c", supervisor=True
    )

    [(assignment, supervisor)] = store.assignments
    assert row.reviewer_sub == "rita" and supervisor is True
    assert assignment.reviewer_fingerprint == RITA.key.fingerprint
    assert (assignment.requester_key_version, assignment.directory_read_at) == (1, NOW)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"studio": FakeDirectory(None)}, "directory_unavailable"),
        ({"reviewer": person("sam", 4)}, "not_a_reviewer"),
        ({"key_version": 2}, "key_changed"),
        ({"reviewer_version": 2}, "reviewer_key_changed"),
        ({"forged": True}, "signature_invalid"),
        ({"other_reviewer": True}, "signature_invalid"),
        ({"bad_blob": True}, "signature_invalid"),
    ],
)
async def test_an_assignment_is_refused_in_order(change, code):
    studio = change.get("studio") or FakeDirectory(
        directory(("rita", SWORN), ("sam", ["ssf.recording.supervise"]))
    )
    wraps = None
    if change.get("forged"):
        wraps = tuple(grant(CONVERSATION, key, RALF, RITA) for key in (KEY_1, KEY_2))
    if change.get("other_reviewer"):
        wraps = tuple(grant(CONVERSATION, key, ALICE, RALF) for key in (KEY_1, KEY_2))
    if change.get("bad_blob"):
        good = grant(CONVERSATION, KEY_1, ALICE, RITA)
        wraps = (dataclasses.replace(good, blob="{" * 3000),)
    store = FakeStore(keys=(ALICE, RITA, RALF, person("sam", 4)))
    args = {k: v for k, v in change.items() if k in {"key_version", "reviewer_version", "reviewer"}}
    with pytest.raises(VerificationError, match=f"^{code}$"):
        await service(store, studio).assign(
            TENANT, "alice", CONVERSATION, request(wraps=wraps, **args), "c", supervisor=False
        )
    assert store.assignments == []


async def test_a_store_refusal_is_answered_and_a_vanished_conversation_audited():
    access = FakeAccess()
    store = FakeStore(assigned=Refused("not_found"))
    with pytest.raises(VerificationError, match="not_found"):
        await service(store, access=access).assign(
            TENANT, "alice", CONVERSATION, request(), "c", supervisor=False
        )
    assert access.refused == [CONVERSATION]
    with pytest.raises(VerificationError, match="reviewer_not_eligible"):
        await service(FakeStore(assigned=Refused("reviewer_not_eligible"))).assign(
            TENANT, "alice", CONVERSATION, request(), "c", supervisor=False
        )


def opened_review(conversation_id=CONVERSATION):
    from services.api_gateway.recording.archive_access_repository import OpenedConversation
    from services.api_gateway.recording.verification_repository import ReviewOpened

    conversation = OpenedConversation(
        conversation_id, "alice", "consent", NOW, NOW, NOW, False, False, (), (), {}, (), ()
    )
    record = VerificationRow(
        verification_id="v-1",
        conversation_id=conversation_id,
        status="in_review",
        requested_by="alice",
        requester_key_version=1,
        requested_at=NOW,
        directory_read_at=NOW,
        reviewer_sub="rita",
        reviewer_key_version=1,
        reviewer_fingerprint=RITA.key.fingerprint,
        overall_note=b"\x01draft",
    )
    return ReviewOpened(conversation, record, (), ALICE.key)


async def test_a_review_open_starts_the_object_window_and_a_refusal_is_not_found():
    store, access = FakeStore(), FakeAccess()
    store.opened = opened_review()

    opened = await service(store, access=access).open_review(TENANT, "rita", "v-1", "c")

    assert opened.record.verification_id == "v-1"
    assert store.review_calls == [("rita", "v-1", True)]
    assert access.opened == ("rita", CONVERSATION)
    store.opened = None
    with pytest.raises(VerificationError, match="verification_not_found"):
        await service(store).open_review(TENANT, "rita", "v-2", "c")
    [row] = await service(store).inbox(TENANT, "rita", "c")
    assert (row.verification_id, row.openable, row.requested_by_name) == (
        "v-1",
        True,
        "Alice Employee",
    )
    assert opened.requester_name == "Alice Employee"


ENVELOPE = b"\x01" + bytes(40)


async def test_starting_snapshots_the_reviewers_permissions_from_the_directory():
    store = FakeStore()
    await service(store).start(TENANT, "rita", "v-1", 7, "c")
    assert store.review_calls == [
        ("start", 7, ("ssf.recording.review", "ssf.recording.review.sworn"))
    ]
    with pytest.raises(VerificationError, match="not_a_reviewer"):
        await service(store).start(TENANT, "sam", "v-1", 7, "c")
    with pytest.raises(VerificationError, match="directory_unavailable"):
        await service(store, FakeDirectory(None)).start(TENANT, "rita", "v-1", 7, "c")
    store.answer = Refused("head_changed")
    with pytest.raises(VerificationError, match="head_changed"):
        await service(store).start(TENANT, "rita", "v-1", 7, "c")


@pytest.mark.parametrize(
    ("overall", "notes"),
    [
        (b"\x02" + bytes(40), []),
        (bytes(10), []),
        (b"\x01" + bytes(40_000), []),
        (None, [("e", "k", b"\x01" + bytes(70_000))]),
        (None, [("e", "k", b"\x00" + bytes(40))]),
        (None, [("e", "k", ENVELOPE), ("e", "k2", ENVELOPE)]),
    ],
)
async def test_a_draft_with_a_malformed_envelope_never_reaches_the_store(overall, notes):
    from services.api_gateway.recording.verification_model import NotePost

    store = FakeStore()
    with pytest.raises(VerificationError, match="bad_notes"):
        await service(store).save_draft(
            TENANT, "rita", "v-1", overall, [NotePost(*n) for n in notes]
        )
    assert store.review_calls == []


async def test_drafts_and_declines_reach_the_store_and_its_refusals_come_back():
    from services.api_gateway.recording.verification_model import NotePost

    store = FakeStore()
    note = NotePost("e", "k", ENVELOPE)
    await service(store).save_draft(TENANT, "rita", "v-1", ENVELOPE, [note])
    await service(store).decline(TENANT, "rita", "v-1")
    assert store.review_calls == [("draft", ENVELOPE, (note,)), ("decline", "v-1")]
    store.answer = Refused("not_started")
    with pytest.raises(VerificationError, match="not_started"):
        await service(store).save_draft(TENANT, "rita", "v-1", None, [])
    store.answer = Refused("verification_closed")
    with pytest.raises(VerificationError, match="verification_closed"):
        await service(store).decline(TENANT, "rita", "v-1")


HEAD = b"\x05" * 32


def _in_review(snapshot=SWORN, status="in_review"):
    return dataclasses.replace(
        opened_review().record,
        status=status,
        reviewed_head=HEAD,
        reviewed_head_seq=2,
        permission_snapshot=tuple(snapshot),
    )


def _signed(outcome="approved", overall=None, notes=(), snapshot=SWORN, signer=RITA):
    from tests.recording_verification_world import decision_signature

    return decision_signature(
        signer, CONVERSATION, "v-1", HEAD, outcome, overall, list(notes), snapshot
    )[0]


async def test_a_decision_checks_the_signature_over_its_digest_and_reaches_the_store():
    from services.api_gateway.recording.verification_model import NotePost

    store = FakeStore()
    store.record = _in_review()
    note = NotePost("e-1", "k-1", ENVELOPE)
    signature = _signed("not_approved", ENVELOPE, [note])

    row = await service(store).decide(
        TENANT, "rita", "v-1", "not_approved", ENVELOPE, [note], signature, "c"
    )

    assert row.outcome == "not_approved"
    [decision] = store.decisions
    assert decision.signature == signature and decision.signer_key_version == 1
    assert len(decision.notes_digest) == 32 and len(decision.signed_digest) == 32


@pytest.mark.parametrize(
    ("record", "studio", "signature_change", "code"),
    [
        (None, None, None, "verification_not_found"),
        (_in_review(status="awaiting"), None, None, "not_started"),
        (_in_review(status="approved"), None, None, "verification_closed"),
        (_in_review(), FakeDirectory(None), None, "directory_unavailable"),
        (
            _in_review(),
            FakeDirectory(directory(("rita", ["ssf.recording.review.sworn"]))),
            None,
            "not_a_reviewer",
        ),
        (_in_review(snapshot=REVIEWER), None, None, "permissions_changed"),
        (_in_review(), None, "outcome", "signature_invalid"),
        (_in_review(), None, "signer", "signature_invalid"),
    ],
)
async def test_a_decision_is_refused_in_order(record, studio, signature_change, code):
    store = FakeStore()
    store.record = record
    signature = _signed(
        "not_approved" if signature_change == "outcome" else "approved",
        signer=RALF if signature_change == "signer" else RITA,
    )
    with pytest.raises(VerificationError, match=f"^{code}$"):
        await service(store, studio).decide(
            TENANT, "rita", "v-1", "approved", None, [], signature, "c"
        )
    assert store.decisions == []


async def test_a_decision_without_an_active_key_or_with_bad_notes_is_refused():
    store = FakeStore(keys=(ALICE,))
    store.record = _in_review()
    with pytest.raises(VerificationError, match="key_changed"):
        await service(store).decide(TENANT, "rita", "v-1", "approved", None, [], _signed(), "c")
    with pytest.raises(VerificationError, match="bad_notes"):
        await service(store).decide(
            TENANT, "rita", "v-1", "approved", b"\x02" + bytes(40), [], _signed(), "c"
        )
    store = FakeStore()
    store.record = _in_review()
    store.answer = Refused("key_changed")
    with pytest.raises(VerificationError, match="key_changed"):
        await service(store).decide(TENANT, "rita", "v-1", "approved", None, [], _signed(), "c")

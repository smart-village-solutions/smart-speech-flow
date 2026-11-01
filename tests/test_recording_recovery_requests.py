"""The recovery request service: what the gateway checks without any secret (spec §9.5)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from services.api_gateway.recording.ceremony_model import RecoveryKeyRecord
from services.api_gateway.recording.crypto import ecies, tags
from services.api_gateway.recording.crypto.curve import point_from_public_key
from services.api_gateway.recording.crypto.ecies import Sealed
from services.api_gateway.recording.crypto.signatures import (
    approval_fields,
    request_fields,
    sign_fields,
    wrap_fields,
)
from services.api_gateway.recording.crypto.transcript import fingerprint
from services.api_gateway.recording.recovery_requests import (
    RecoveryRequestError,
    RecoveryRequests,
)
from services.api_gateway.recording.recovery_requests_model import (
    ApprovalContext,
    ApproverScopeKey,
    NewWrap,
    Refused,
    RequestRow,
    ScopeKey,
)
from services.api_gateway.recording.repository import RecordingStorageUnavailable, UserKeyRecord

TENANT = "tenant-a"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
RECOVERY_KEY_ID = "0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a"
R = point_from_public_key(ec.generate_private_key(ec.SECP256R1()).public_key())


@dataclass
class Call:
    args: tuple[Any, ...]
    verify: Any = None
    keywords: dict[str, Any] = field(default_factory=dict)


@dataclass
class Method:
    result: Any = None
    calls: list[Call] = field(default_factory=list)
    raises: BaseException | None = None

    async def __call__(self, *args: Any, **keywords: Any) -> Any:
        verify = next((a for a in args if callable(a)), None)
        self.calls.append(Call(args, verify, keywords))
        if self.raises is not None:
            raise self.raises
        return self.result


class FakeRequests:
    def __init__(self) -> None:
        for name in (
            "employees",
            "candidates",
            "file",
            "own_candidates",
            "own_requests",
            "approvals",
            "share_stale",
            "approval_context",
            "approve",
            "decline",
            "progress",
            "partials",
            "reject",
            "record_integrity_failure",
            "store_wraps",
            "cancel",
        ):
            setattr(self, name, Method())


class FakeKeys:
    def __init__(self, requester: ec.EllipticCurvePrivateKey | None) -> None:
        self.requester = requester
        self.enc = point_from_public_key(ec.generate_private_key(ec.SECP256R1()).public_key())

    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None:
        return RecoveryKeyRecord(
            TENANT, RECOVERY_KEY_ID, R, 2, 3, "enhanced", bytes(32), "{}", bytes(64), "gw", NOW
        )

    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None:
        if self.requester is None:
            return None
        public = point_from_public_key(self.requester.public_key())
        enc = self.enc
        return UserKeyRecord(
            tenant_id,
            user_sub,
            1,
            enc,
            public,
            fingerprint(tenant_id, user_sub, enc, public),
            None,
            NOW,
        )


class FakeNames:
    async def names(self, tenant_id: str, correlation_id: str) -> dict[str, str]:
        return {"sam": "Sam Supervisor", "alice": "Alice Employee"}


def _service(requester: Any = "fresh") -> tuple[RecoveryRequests, FakeRequests]:
    key = ec.generate_private_key(ec.SECP256R1()) if requester == "fresh" else requester
    fake = FakeRequests()
    keys = FakeKeys(key)
    service = RecoveryRequests(repository=fake, keys=keys, names=FakeNames(), clock=lambda: NOW)
    service.keys = keys  # type: ignore[attr-defined]  # the test reads the fingerprint back
    return service, fake


def _row() -> RequestRow:
    return RequestRow(
        REQUEST_ID, "access", "sam", 1, RECOVERY_KEY_ID, "why", bytes(64), "open", NOW, NOW, None
    )


REQUEST_ID = "5b4a3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d"


def _context(blob: str) -> ApprovalContext:
    return ApprovalContext(
        request=_row(),
        requester_enc_pub=R,
        requester_sig_pub=R,
        signed_scope=(ScopeKey("c1", "k1"),),
        remaining=(ApproverScopeKey("c1", "k1", "alice", NOW, NOW, blob, "gw", bytes(64)),),
        holder_index=2,
        attempt=1,
        encrypted_share="{}",
    )


def _sealed_json(tag: str, ciphertext_bytes: int) -> str:
    return Sealed(tag, R, bytes(12), os.urandom(ciphertext_bytes)).to_json()


def _user_wrap(signer: ec.EllipticCurvePrivateKey, fpr: bytes, key_id: str = "k1") -> NewWrap:
    sealed = ecies.seal(
        tags.CK_WRAP, R, os.urandom(32), ecies.ck_wrap_context(TENANT, "c1", key_id, "user", "sam")
    )
    signature = sign_fields(
        signer,
        tags.WRAP_SIG,
        *wrap_fields(TENANT, "c1", key_id, sealed.ephemeral, "user", "sam", fpr),
    )
    return NewWrap("c1", key_id, sealed.to_json(), signature)


async def test_filing_verifies_the_signature_over_the_scope_the_database_read():
    requester = ec.generate_private_key(ec.SECP256R1())
    service, fake = _service(requester)
    fake.file.result = (ScopeKey("c1", "k1"),)
    signature = sign_fields(
        requester,
        tags.REQUEST_SIG,
        *request_fields(TENANT, "r1", "access", RECOVERY_KEY_ID, "sam", "why", [("c1", "k1")]),
    )

    await service.file(TENANT, "sam", "r1", "access", "why", ("c1",), signature)

    verify = fake.file.calls[0].verify
    assert verify((ScopeKey("c1", "k1"),))
    assert not verify((ScopeKey("c1", "k1"), ScopeKey("c9", "k9")))
    assert fake.file.calls[0].args[0].recovery_key_id == RECOVERY_KEY_ID


async def test_filing_without_an_enrolled_key_is_refused():
    service, fake = _service(None)
    with pytest.raises(RecoveryRequestError, match="key_not_enrolled"):
        await service.file(TENANT, "sam", "r1", "access", "why", ("c1",), bytes(64))
    assert fake.file.calls == []


async def test_an_approver_is_served_r_and_never_the_wraps_ciphertext():
    service, fake = _service()
    blob = _sealed_json(tags.CK_WRAP, 48)
    fake.approval_context.result = _context(blob)

    view = await service.approval(TENANT, "carol", "r1", "corr")

    [key] = view.keys
    assert key.ephemeral == R
    assert key.employee_name == "Alice Employee"
    assert view.requester_name == "Sam Supervisor"
    assert not hasattr(key, "recovery_blob")
    assert Sealed.from_json(blob, expected_type=tags.CK_WRAP).to_json() not in repr(view)


async def test_a_malformed_recovery_wrap_is_unavailable_rather_than_served():
    service, fake = _service()
    fake.approval_context.result = _context("not a sealed payload")
    with pytest.raises(RecoveryRequestError, match="unavailable"):
        await service.approval(TENANT, "carol", "r1", "corr")


@pytest.mark.parametrize(
    "blob",
    [
        '{"v":1}',
        _sealed_json(tags.CK_WRAP, 145),
        _sealed_json(tags.PARTIAL, 144),
        "x" * 1025,
    ],
)
async def test_a_malformed_partial_is_refused_before_the_database(blob):
    service, fake = _service()
    with pytest.raises(RecoveryRequestError, match="bad_partial"):
        await service.approve(TENANT, "carol", "r1", {"k1": blob}, bytes(64))
    assert fake.approve.calls == []


async def test_an_approval_signature_is_checked_with_the_custodians_key():
    custodian = ec.generate_private_key(ec.SECP256R1())
    service, fake = _service()
    partials = {"k1": _sealed_json(tags.PARTIAL, 145)}
    signature = sign_fields(
        custodian, tags.APPROVAL_SIG, *approval_fields(TENANT, "r1", 2, 1, partials)
    )

    await service.approve(TENANT, "carol", "r1", partials, signature)

    verify = fake.approve.calls[0].verify
    public = point_from_public_key(custodian.public_key())
    assert verify(2, 1, public)
    assert not verify(3, 1, public)
    assert not verify(2, 2, public)


async def test_a_stored_wrap_must_be_signed_by_the_requester_for_their_fingerprint():
    requester = ec.generate_private_key(ec.SECP256R1())
    service, fake = _service(requester)
    fake.store_wraps.result = ()
    own = await service.keys.active_user_key(TENANT, "sam")  # type: ignore[attr-defined]

    await service.store(TENANT, "sam", "r1", [], may_supervise=True)

    verify = fake.store_wraps.calls[0].verify
    good = _user_wrap(requester, own.fingerprint)
    assert verify(good)
    assert not verify(replace(good, key_id="k2"))
    assert not verify(_user_wrap(requester, bytes(32)))
    assert not verify(_user_wrap(ec.generate_private_key(ec.SECP256R1()), own.fingerprint))
    assert not verify(replace(good, blob="{}"))


@pytest.mark.parametrize(
    "refused",
    ["not_found", "closed", "requester_cannot_approve", "already_decided", "scope_not_covered"],
)
async def test_each_refusal_of_the_repository_is_raised_with_its_code(refused):
    service, fake = _service()
    fake.decline.result = Refused(refused)
    with pytest.raises(RecoveryRequestError, match=refused):
        await service.decline(TENANT, "carol", "r1", "no")


async def test_a_storage_failure_is_unavailable():
    service, fake = _service()
    fake.cancel.raises = RecordingStorageUnavailable("down")
    with pytest.raises(RecoveryRequestError, match="unavailable"):
        await service.cancel(TENANT, "sam", "r1")


async def test_the_reads_pass_through_with_names():
    service, fake = _service()
    fake.employees.result = ["alice", "bob"]
    fake.progress.result = "progress"
    assert await service.employees(TENANT, "corr") == [
        ("alice", "Alice Employee"),
        ("bob", None),
    ]
    assert await service.progress(TENANT, "sam", "r1", "corr", may_supervise=True) == (
        "progress",
        await FakeNames().names(TENANT, "corr"),
    )
    for name, call in (
        ("candidates", service.candidates(TENANT, "sam", "alice", NOW, NOW)),
        ("own_requests", service.own_requests(TENANT, "sam")),
        ("approvals", service.approvals(TENANT, "carol")),
        ("partials", service.partials(TENANT, "sam", "r1", may_supervise=True)),
        (
            "reject",
            service.reject(TENANT, "sam", "r1", (1, 1), "proof_invalid", may_supervise=True),
        ),
        (
            "record_integrity_failure",
            service.report(TENANT, "sam", "r1", "trust", may_supervise=True),
        ),
    ):
        getattr(fake, name).result = [] if name in {"candidates", "own_requests"} else None
        fake.share_stale.result = True
        await call
        assert getattr(fake, name).calls, name
    fake.approvals.result = []
    assert await service.approvals(TENANT, "carol") == ([], True)


async def test_without_a_recovery_key_nothing_is_listed_or_filed():
    service, fake = _service()

    async def none(tenant_id: str) -> None:
        return None

    service.keys.active_recovery_key = none  # type: ignore[attr-defined]
    with pytest.raises(RecoveryRequestError, match="recovery_key_missing"):
        await service.candidates(TENANT, "sam", "alice", NOW, NOW)
    assert fake.candidates.calls == []


async def test_filing_verifies_the_kind_it_was_given():
    requester = ec.generate_private_key(ec.SECP256R1())
    service, fake = _service(requester)
    fake.file.result = (ScopeKey("c1", "k1"),)
    signed_as_access = sign_fields(
        requester,
        tags.REQUEST_SIG,
        *request_fields(TENANT, "r1", "access", RECOVERY_KEY_ID, "sam", "why", [("c1", "k1")]),
    )

    await service.file(TENANT, "sam", "r1", "key_recovery", "why", ("c1",), signed_as_access)

    assert not fake.file.calls[0].verify((ScopeKey("c1", "k1"),))
    assert fake.file.calls[0].args[0].kind == "key_recovery"


async def test_own_candidates_need_a_key_and_ask_for_the_active_recovery_key():
    service, fake = _service()
    fake.own_candidates.result = ([], 0, 0)

    assert await service.own_candidates(TENANT, "alice") == ([], 0, 0)
    assert fake.own_candidates.calls[0].args[:3] == (TENANT, "alice", RECOVERY_KEY_ID)

    keyless, _ = _service(None)
    with pytest.raises(RecoveryRequestError, match="key_not_enrolled"):
        await keyless.own_candidates(TENANT, "alice")

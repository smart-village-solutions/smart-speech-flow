"""Exceptional access (spec §9.5).

The gateway checks what it can without any secret: the shape of each sealed
payload, the requester's signature over the scope, each custodian's signature
over their partials, and each wrap the requester stores. Approvers are served
a recovery wrap's R and its signature, never its nonce or ciphertext.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from ..clock import utc_now
from .ceremony_model import RecoveryKeyRecord
from .crypto import tags
from .crypto.ecies import Sealed, SealedPayloadError
from .crypto.signatures import approval_fields, request_fields, verify_fields, wrap_fields
from .recovery_requests_model import (
    Approval,
    ApprovalContext,
    ApprovalVerifier,
    Candidate,
    NewRequest,
    NewWrap,
    Progress,
    Refused,
    RequestRow,
    ScopeKey,
    ScopeVerifier,
    ServedPartials,
    WrapVerifier,
)
from .repository import RecordingStorageUnavailable, UserKeyRecord

# P_i ‖ c ‖ s, plus the GCM tag (spec A.4, A.7).
PARTIAL_CIPHERTEXT_BYTES: Final[int] = 65 + 32 + 32 + 16
MAX_SEALED_CHARACTERS: Final[int] = 1024


class RecoveryRequestError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RequestStore(Protocol):
    async def employees(self, tenant_id: str) -> list[str]: ...

    async def candidates(
        self,
        tenant_id: str,
        requester: str,
        employee: str,
        recovery_key_id: str,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> list[Candidate]: ...

    async def file(
        self, request: NewRequest, verify: ScopeVerifier
    ) -> Refused | tuple[ScopeKey, ...]: ...

    async def own_requests(
        self, tenant_id: str, sub: str, now: datetime
    ) -> list[tuple[RequestRow, int]]: ...

    async def approvals(
        self, tenant_id: str, sub: str, recovery_key_id: str, now: datetime
    ) -> list[tuple[RequestRow, int]]: ...

    async def approval_context(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | ApprovalContext: ...

    async def approve(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        approval: Approval,
        verify: ApprovalVerifier,
        now: datetime,
    ) -> Refused | None: ...

    async def decline(
        self, tenant_id: str, sub: str, request_id: str, reason: str, now: datetime
    ) -> Refused | None: ...

    async def progress(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | Progress: ...

    async def partials(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | ServedPartials: ...

    async def reject(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        holder: tuple[int, int],
        fault: str,
        now: datetime,
    ) -> Refused | None: ...

    async def record_integrity_failure(
        self, tenant_id: str, sub: str, request_id: str, stage: str, now: datetime
    ) -> Refused | None: ...

    async def store_wraps(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        wraps: Sequence[NewWrap],
        key_version: int,
        verify: WrapVerifier,
        now: datetime,
    ) -> Refused | tuple[str, ...]: ...

    async def cancel(
        self, tenant_id: str, sub: str, request_id: str, now: datetime
    ) -> Refused | None: ...


class KeySource(Protocol):
    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None: ...

    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None: ...


class NameSource(Protocol):
    async def names(self, tenant_id: str, correlation_id: str) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class ApproverKey:
    conversation_id: str
    key_id: str
    employee_sub: str
    employee_name: str | None
    started_at: datetime
    ended_at: datetime
    ephemeral: bytes
    creator_ref: str
    creator_signature: bytes


@dataclass(frozen=True)
class ApprovalView:
    request: RequestRow
    requester_name: str | None
    requester_enc_pub: bytes
    requester_sig_pub: bytes
    signed_scope: tuple[ScopeKey, ...]
    keys: tuple[ApproverKey, ...]
    holder_index: int
    attempt: int
    encrypted_share: str


async def _guard[T](work: Awaitable[T]) -> T:
    try:
        return await work
    except RecordingStorageUnavailable:
        raise RecoveryRequestError("unavailable") from None


async def _answer[T](work: Awaitable[Refused | T]) -> T:
    result = await _guard(work)
    if isinstance(result, Refused):
        raise RecoveryRequestError(result.code)
    return result


def _sealed(blob: str, expected: str) -> Sealed | None:
    if len(blob) > MAX_SEALED_CHARACTERS:
        return None
    try:
        return Sealed.from_json(blob, expected_type=expected)
    except SealedPayloadError:
        return None


def _approver_keys(context: ApprovalContext, names: Mapping[str, str]) -> tuple[ApproverKey, ...]:
    keys = []
    for item in context.remaining:
        sealed = _sealed(item.recovery_blob, tags.CK_WRAP)
        if sealed is None:
            raise RecoveryRequestError("unavailable")
        keys.append(
            ApproverKey(
                conversation_id=item.conversation_id,
                key_id=item.key_id,
                employee_sub=item.employee_sub,
                employee_name=names.get(item.employee_sub),
                started_at=item.started_at,
                ended_at=item.ended_at,
                ephemeral=sealed.ephemeral,
                creator_ref=item.creator_ref,
                creator_signature=item.creator_signature,
            )
        )
    return tuple(keys)


class RecoveryRequests:
    def __init__(
        self,
        *,
        repository: RequestStore,
        keys: KeySource,
        names: NameSource,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._keys = keys
        self._names = names
        self._clock = clock

    async def _recovery_key(self, tenant_id: str) -> RecoveryKeyRecord:
        key = await _guard(self._keys.active_recovery_key(tenant_id))
        if key is None:
            raise RecoveryRequestError("recovery_key_missing")
        return key

    async def _own_key(self, tenant_id: str, sub: str) -> UserKeyRecord:
        key = await _guard(self._keys.active_user_key(tenant_id, sub))
        if key is None:
            raise RecoveryRequestError("key_not_enrolled")
        return key

    async def employees(self, tenant_id: str, correlation_id: str) -> list[tuple[str, str | None]]:
        subs = await _guard(self._repository.employees(tenant_id))
        names = await self._names.names(tenant_id, correlation_id)
        return [(sub, names.get(sub)) for sub in subs]

    async def candidates(
        self, tenant_id: str, sub: str, employee: str, start: datetime, end: datetime
    ) -> list[Candidate]:
        key = await self._recovery_key(tenant_id)
        return await _guard(
            self._repository.candidates(
                tenant_id, sub, employee, key.key_id, start, end, self._clock()
            )
        )

    async def file(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        reason: str,
        conversation_ids: tuple[str, ...],
        signature: bytes,
    ) -> tuple[ScopeKey, ...]:
        own = await self._own_key(tenant_id, sub)
        recovery = await self._recovery_key(tenant_id)

        def verify(scope: tuple[ScopeKey, ...]) -> bool:
            pairs = [(key.conversation_id, key.key_id) for key in scope]
            fields = request_fields(
                tenant_id, request_id, "access", recovery.key_id, sub, reason, pairs
            )
            return verify_fields(own.sig_pub, signature, tags.REQUEST_SIG, *fields)

        request = NewRequest(
            tenant_id=tenant_id,
            request_id=request_id,
            requester_sub=sub,
            requester_key_version=own.key_version,
            recovery_key_id=recovery.key_id,
            reason=reason,
            conversation_ids=conversation_ids,
            signature=signature,
            created_at=self._clock(),
        )
        return await _answer(self._repository.file(request, verify))

    async def own_requests(self, tenant_id: str, sub: str) -> list[tuple[RequestRow, int]]:
        return await _guard(self._repository.own_requests(tenant_id, sub, self._clock()))

    async def approvals(self, tenant_id: str, sub: str) -> list[tuple[RequestRow, int]]:
        key = await self._recovery_key(tenant_id)
        return await _guard(self._repository.approvals(tenant_id, sub, key.key_id, self._clock()))

    async def approval(
        self, tenant_id: str, sub: str, request_id: str, correlation_id: str
    ) -> ApprovalView:
        context = await _answer(
            self._repository.approval_context(tenant_id, sub, request_id, self._clock())
        )
        names = await self._names.names(tenant_id, correlation_id)
        return ApprovalView(
            request=context.request,
            requester_name=names.get(context.request.requester_sub),
            requester_enc_pub=context.requester_enc_pub,
            requester_sig_pub=context.requester_sig_pub,
            signed_scope=context.signed_scope,
            keys=_approver_keys(context, names),
            holder_index=context.holder_index,
            attempt=context.attempt,
            encrypted_share=context.encrypted_share,
        )

    async def approve(
        self,
        tenant_id: str,
        sub: str,
        request_id: str,
        partials: Mapping[str, str],
        signature: bytes,
    ) -> None:
        for blob in partials.values():
            sealed = _sealed(blob, tags.PARTIAL)
            if sealed is None or len(sealed.ciphertext) != PARTIAL_CIPHERTEXT_BYTES:
                raise RecoveryRequestError("bad_partial")

        def verify(holder_index: int, attempt: int, sig_pub: bytes) -> bool:
            fields = approval_fields(tenant_id, request_id, holder_index, attempt, partials)
            return verify_fields(sig_pub, signature, tags.APPROVAL_SIG, *fields)

        approval = Approval(dict(partials), signature)
        await _answer(
            self._repository.approve(tenant_id, sub, request_id, approval, verify, self._clock())
        )

    async def decline(self, tenant_id: str, sub: str, request_id: str, reason: str) -> None:
        await _answer(self._repository.decline(tenant_id, sub, request_id, reason, self._clock()))

    async def progress(
        self, tenant_id: str, sub: str, request_id: str, correlation_id: str
    ) -> tuple[Progress, Mapping[str, str]]:
        found = await _answer(self._repository.progress(tenant_id, sub, request_id, self._clock()))
        return found, await self._names.names(tenant_id, correlation_id)

    async def partials(self, tenant_id: str, sub: str, request_id: str) -> ServedPartials:
        return await _answer(self._repository.partials(tenant_id, sub, request_id, self._clock()))

    async def reject(
        self, tenant_id: str, sub: str, request_id: str, holder: tuple[int, int], fault: str
    ) -> None:
        await _answer(
            self._repository.reject(tenant_id, sub, request_id, holder, fault, self._clock())
        )

    async def report(self, tenant_id: str, sub: str, request_id: str, stage: str) -> None:
        await _answer(
            self._repository.record_integrity_failure(
                tenant_id, sub, request_id, stage, self._clock()
            )
        )

    async def store(
        self, tenant_id: str, sub: str, request_id: str, wraps: Sequence[NewWrap]
    ) -> tuple[str, ...]:
        own = await self._own_key(tenant_id, sub)

        def verify(wrap: NewWrap) -> bool:
            sealed = _sealed(wrap.blob, tags.CK_WRAP)
            if sealed is None:
                return False
            fields = wrap_fields(
                tenant_id,
                wrap.conversation_id,
                wrap.key_id,
                sealed.ephemeral,
                "user",
                sub,
                own.fingerprint,
            )
            return verify_fields(own.sig_pub, wrap.signature, tags.WRAP_SIG, *fields)

        return await _answer(
            self._repository.store_wraps(
                tenant_id, sub, request_id, wraps, own.key_version, verify, self._clock()
            )
        )

    async def cancel(self, tenant_id: str, sub: str, request_id: str) -> None:
        await _answer(self._repository.cancel(tenant_id, sub, request_id, self._clock()))

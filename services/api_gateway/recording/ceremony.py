"""The recovery-key ceremony as the gateway runs it (spec §9.2).

The gateway names the participants, relays what they publish, checks every
public value, and activates the key once every custodian has signed the
same transcript. It never holds a share, a polynomial or the recovery key:
shares are computed and sealed in the custodians' browsers, and paper
shares on the ceremony device.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .audit import AuditEvent
from .ceremony_model import (
    ABORT_REASONS,
    CEREMONY_LIFETIME,
    CUSTODIAN,
    MAX_CUSTODIANS,
    MAX_K,
    PAPER,
    CeremonyError,
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    ConfirmationRecord,
    DealingRecord,
    DealingSubmission,
    RecoveryKeyRecord,
    RecoveryShareRecord,
    check_dealing,
    check_sealed,
    computed_transcript_hash,
    conflict,
    invalid,
    transcript_input,
)
from .crypto import ecies, tags
from .crypto.curve import InvalidPoint, decode_point
from .crypto.signatures import sign_fields, verify_fields, wrap_fields
from .crypto.transcript import paper_device_fingerprint
from .repository import UserKeyRecord
from .secrets import RecordingSecrets

CANARY_CONVERSATION = "canary"


class CeremonyStore(Protocol):
    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None: ...

    async def user_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, UserKeyRecord]: ...

    async def gateway_keys(self) -> tuple[tuple[str, bytes], ...]: ...

    async def open_ceremony(self, tenant_id: str, now: datetime) -> CeremonySnapshot | None: ...

    async def subshares_for(
        self, tenant_id: str, ceremony_id: str, recipients: Collection[int]
    ) -> dict[int, dict[int, str]]: ...

    async def create_ceremony(
        self,
        ceremony: CeremonyRecord,
        participants: Sequence[CeremonyParticipant],
        audit: Sequence[AuditEvent],
    ) -> None: ...

    async def add_dealing(
        self, tenant_id: str, ceremony_id: str, dealing: DealingRecord, audit: AuditEvent
    ) -> CeremonySnapshot: ...

    async def begin_confirming(
        self, tenant_id: str, ceremony_id: str, transcript_hash: bytes, audit: AuditEvent
    ) -> None: ...

    async def add_confirmation(
        self,
        tenant_id: str,
        ceremony_id: str,
        confirmation: ConfirmationRecord,
        audit: AuditEvent,
    ) -> None: ...

    async def confirm_paper(self, tenant_id: str, ceremony_id: str, audit: AuditEvent) -> None: ...

    async def abort(
        self, tenant_id: str, ceremony_id: str, reason: str, audit: AuditEvent
    ) -> None: ...

    async def activate(
        self,
        tenant_id: str,
        key: RecoveryKeyRecord,
        shares: Sequence[RecoveryShareRecord],
        audit: AuditEvent,
    ) -> bool: ...


class CustodianDirectory(Protocol):
    """Who holds the custodian permission right now; None when Studio cannot say."""

    async def custodians(self, tenant_id: str, correlation_id: str) -> Mapping[str, str] | None: ...


@dataclass(frozen=True)
class StartRequest:
    k: int
    custodians: tuple[str, ...]
    # The ceremony device's encryption key; present when paper shares are wanted.
    paper_device_pub: bytes | None


@dataclass(frozen=True)
class Candidate:
    sub: str
    display_name: str
    fingerprint: bytes | None


@dataclass(frozen=True)
class CeremonyState:
    recovery_key: RecoveryKeyRecord | None
    ceremony: CeremonySnapshot | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_shape(request: StartRequest, starter: str) -> None:
    if not 1 <= request.k <= MAX_K:
        raise invalid("INVALID_CEREMONY", f"k must be between 1 and {MAX_K}")
    custodians = request.custodians
    if len(set(custodians)) != len(custodians):
        raise invalid("INVALID_CEREMONY", "Each custodian is named once")
    # The requester of a recovery may not approve it, so k others must remain.
    if not request.k + 1 <= len(custodians) <= MAX_CUSTODIANS:
        raise invalid("INVALID_CEREMONY", f"Name between k+1 and {MAX_CUSTODIANS} custodians")
    if request.paper_device_pub is None:
        return
    if starter in custodians:
        raise invalid("INVALID_CEREMONY", "The ceremony device may not belong to a custodian")
    try:
        decode_point(request.paper_device_pub)
    except InvalidPoint:
        raise invalid("INVALID_CEREMONY", "The device key is not a P-256 point") from None


class CeremonyService:
    def __init__(
        self,
        *,
        repository: CeremonyStore,
        directory: CustodianDirectory,
        secrets: RecordingSecrets,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._directory = directory
        self._secrets = secrets
        self._clock = clock
        self._new_id = new_id

    async def state(self, tenant_id: str) -> CeremonyState:
        return CeremonyState(
            await self._repository.active_recovery_key(tenant_id),
            await self._repository.open_ceremony(tenant_id, self._clock()),
        )

    async def _custodian_names(self, tenant_id: str, correlation_id: str) -> Mapping[str, str]:
        names = await self._directory.custodians(tenant_id, correlation_id)
        if names is None:
            raise CeremonyError(503, "DIRECTORY_UNAVAILABLE", "The staff directory is unavailable")
        return names

    async def candidates(self, tenant_id: str, correlation_id: str) -> list[Candidate]:
        names = await self._custodian_names(tenant_id, correlation_id)
        keys = await self._repository.user_keys(tenant_id, list(names))
        return sorted(
            (
                Candidate(sub, name, keys[sub].fingerprint if sub in keys else None)
                for sub, name in names.items()
            ),
            key=lambda candidate: (candidate.display_name, candidate.sub),
        )

    async def start(
        self, tenant_id: str, starter: str, request: StartRequest, correlation_id: str
    ) -> CeremonySnapshot:
        _validate_shape(request, starter)
        if await self._repository.active_recovery_key(tenant_id) is not None:
            raise conflict("RECOVERY_KEY_EXISTS", "The tenant already has a recovery key")
        names = await self._custodian_names(tenant_id, correlation_id)
        missing = [sub for sub in request.custodians if sub not in names]
        if missing:
            raise invalid("NOT_A_CUSTODIAN", "A named user lacks the custodian permission")
        keys = await self._repository.user_keys(tenant_id, list(request.custodians))
        if any(sub not in keys for sub in request.custodians):
            raise invalid("CUSTODIAN_NOT_ENROLLED", "A named custodian has no personal key")
        now = self._clock()
        ceremony = CeremonyRecord(
            tenant_id=tenant_id,
            ceremony_id=self._new_id(),
            k=request.k,
            started_by=starter,
            started_at=now,
            expires_at=now + CEREMONY_LIFETIME,
            status="dealing",
            gateway_keys=await self._repository.gateway_keys(),
        )
        participants = _participants(tenant_id, request, names, keys)
        event = AuditEvent(
            tenant_id, starter, "ceremony_started", f"ceremony:{ceremony.ceremony_id}", now
        )
        await self._repository.create_ceremony(ceremony, participants, [event])
        return CeremonySnapshot(ceremony, participants, (), ())

    async def _open(self, tenant_id: str, ceremony_id: str) -> CeremonySnapshot:
        snapshot = await self._repository.open_ceremony(tenant_id, self._clock())
        if snapshot is None or snapshot.ceremony.ceremony_id != ceremony_id:
            raise CeremonyError(404, "NO_CEREMONY", "No such ceremony in progress")
        return snapshot

    async def _custodian(
        self, tenant_id: str, ceremony_id: str, user_sub: str
    ) -> tuple[CeremonySnapshot, CeremonyParticipant]:
        snapshot = await self._open(tenant_id, ceremony_id)
        participant = snapshot.custodian(user_sub)
        if participant is None:
            raise CeremonyError(403, "NOT_A_PARTICIPANT", "Not a custodian of this ceremony")
        return snapshot, participant

    async def deal(
        self, tenant_id: str, dealer_sub: str, ceremony_id: str, dealing: DealingSubmission
    ) -> CeremonySnapshot:
        snapshot, dealer = await self._custodian(tenant_id, ceremony_id, dealer_sub)
        if snapshot.ceremony.status != "dealing":
            raise conflict("CEREMONY_STATE", "Dealing is over")
        if snapshot.has_dealt(dealer.holder_index):
            raise conflict("ALREADY_SUBMITTED", "This custodian has already dealt")
        check_dealing(snapshot, dealer, dealing)
        now = self._clock()
        record = DealingRecord(
            dealer.holder_index,
            dealing.commitments,
            dealing.proof_c,
            dealing.proof_s,
            dealing.signature,
            now,
            dealing.subshares,
        )
        after = await self._repository.add_dealing(
            tenant_id,
            ceremony_id,
            record,
            AuditEvent(tenant_id, dealer_sub, "ceremony_dealt", f"ceremony:{ceremony_id}", now),
        )
        if after.all_dealt():
            await self._repository.begin_confirming(
                tenant_id,
                ceremony_id,
                computed_transcript_hash(after),
                AuditEvent(
                    tenant_id, dealer_sub, "ceremony_dealt_all", f"ceremony:{ceremony_id}", now
                ),
            )
        return after

    async def subshares(
        self, tenant_id: str, user_sub: str, ceremony_id: str
    ) -> dict[int, dict[int, str]]:
        """What the caller receives: its own holder index, or the paper indices for the starter."""
        snapshot = await self._open(tenant_id, ceremony_id)
        custodian = snapshot.custodian(user_sub)
        if custodian is not None:
            recipients = [custodian.holder_index]
        elif user_sub == snapshot.ceremony.started_by and snapshot.paper_holders:
            recipients = [p.holder_index for p in snapshot.paper_holders]
        else:
            raise CeremonyError(403, "NOT_A_PARTICIPANT", "Nothing in this ceremony is yours")
        if snapshot.ceremony.status != "confirming":
            raise conflict("CEREMONY_STATE", "Sub-shares are released once everyone has dealt")
        return await self._repository.subshares_for(tenant_id, ceremony_id, recipients)

    async def confirm(
        self,
        tenant_id: str,
        user_sub: str,
        ceremony_id: str,
        transcript_signature: bytes,
        encrypted_share: str,
    ) -> str:
        """Returns the ceremony's status afterwards: 'confirming' or 'active'."""
        snapshot, holder = await self._custodian(tenant_id, ceremony_id, user_sub)
        transcript = snapshot.ceremony.transcript_hash
        if snapshot.ceremony.status != "confirming" or transcript is None:
            raise conflict("CEREMONY_STATE", "The ceremony is not ready for signatures")
        if holder.sig_pub is None or not verify_fields(
            holder.sig_pub, transcript_signature, tags.TRANSCRIPT, transcript
        ):
            raise invalid("INVALID_CONFIRMATION", "The transcript signature does not verify")
        check_sealed(encrypted_share, tags.SHARE)
        now = self._clock()
        await self._repository.add_confirmation(
            tenant_id,
            ceremony_id,
            ConfirmationRecord(holder.holder_index, transcript_signature, encrypted_share, now),
            AuditEvent(tenant_id, user_sub, "ceremony_confirmed", f"ceremony:{ceremony_id}", now),
        )
        return await self._activate_if_complete(tenant_id, ceremony_id, user_sub)

    async def confirm_paper(
        self, tenant_id: str, user_sub: str, ceremony_id: str, transcript: bytes
    ) -> str:
        """The ceremony device has printed every paper share of this exact transcript."""
        snapshot = await self._open(tenant_id, ceremony_id)
        ceremony = snapshot.ceremony
        if user_sub != ceremony.started_by or not snapshot.paper_holders:
            raise CeremonyError(403, "NOT_A_PARTICIPANT", "Not this ceremony's device")
        if ceremony.status != "confirming" or ceremony.paper_confirmed_at is not None:
            raise conflict("CEREMONY_STATE", "The ceremony is not waiting for paper shares")
        if transcript != ceremony.transcript_hash:
            raise invalid("TRANSCRIPT_MISMATCH", "The device computed a different transcript")
        await self._repository.confirm_paper(
            tenant_id,
            ceremony_id,
            AuditEvent(
                tenant_id,
                user_sub,
                "ceremony_paper_printed",
                f"ceremony:{ceremony_id}",
                self._clock(),
            ),
        )
        return await self._activate_if_complete(tenant_id, ceremony_id, user_sub)

    async def abort(self, tenant_id: str, user_sub: str, ceremony_id: str, reason: str) -> None:
        if reason not in ABORT_REASONS:
            raise invalid("INVALID_REASON", "Unknown abort reason")
        snapshot = await self._open(tenant_id, ceremony_id)
        if user_sub != snapshot.ceremony.started_by and snapshot.custodian(user_sub) is None:
            raise CeremonyError(403, "NOT_A_PARTICIPANT", "Not a participant of this ceremony")
        await self._repository.abort(
            tenant_id,
            ceremony_id,
            reason,
            AuditEvent(
                tenant_id,
                user_sub,
                "ceremony_aborted",
                f"ceremony:{ceremony_id}:{reason}",
                self._clock(),
            ),
        )

    async def _activate_if_complete(self, tenant_id: str, ceremony_id: str, actor: str) -> str:
        snapshot = await self._repository.open_ceremony(tenant_id, self._clock())
        if snapshot is None or snapshot.ceremony.ceremony_id != ceremony_id:
            return "active"
        if not snapshot.ready_to_activate():
            return snapshot.ceremony.status
        key, shares = self._recovery_key(snapshot)
        await self._repository.activate(
            tenant_id,
            key,
            shares,
            AuditEvent(
                tenant_id,
                actor,
                "recovery_key_activated",
                f"recovery-key:{key.key_id}",
                key.activated_at,
            ),
        )
        return "active"

    def _recovery_key(
        self, snapshot: CeremonySnapshot
    ) -> tuple[RecoveryKeyRecord, list[RecoveryShareRecord]]:
        transcript = transcript_input(snapshot)
        ceremony = snapshot.ceremony
        key_id = ceremony.ceremony_id
        transcript_hash = computed_transcript_hash(snapshot)
        canary, signature = self._canary(
            ceremony.tenant_id, key_id, transcript.recovery_public_key, transcript_hash
        )
        key = RecoveryKeyRecord(
            tenant_id=ceremony.tenant_id,
            key_id=key_id,
            recovery_public_key=transcript.recovery_public_key,
            k=ceremony.k,
            n=len(snapshot.participants),
            mode="standard" if ceremony.k == 1 else "enhanced",
            transcript_hash=transcript_hash,
            canary_wrap=canary,
            canary_signature=signature,
            canary_signer_key_id=self._secrets.signing_key_id,
            activated_at=self._clock(),
        )
        confirmations = {c.holder_index: c.encrypted_share for c in snapshot.confirmations}
        shares = [
            RecoveryShareRecord(
                p.holder_index,
                p.holder_ref,
                transcript.holder_shares[p.holder_index - 1],
                confirmations.get(p.holder_index),
            )
            for p in snapshot.participants
        ]
        return key, shares

    def _canary(
        self, tenant_id: str, key_id: str, recovery_key: bytes, transcript_hash: bytes
    ) -> tuple[str, bytes]:
        """A throwaway conversation key wrapped to X: opening it later proves the shares work."""
        context = ecies.ck_wrap_context(tenant_id, CANARY_CONVERSATION, key_id, "recovery", key_id)
        sealed = ecies.seal(tags.CK_WRAP, recovery_key, os.urandom(32), context)
        # A recovery wrap names the transcript where a user wrap names a fingerprint.
        signed = wrap_fields(
            tenant_id,
            CANARY_CONVERSATION,
            key_id,
            sealed.ephemeral,
            "recovery",
            key_id,
            transcript_hash,
        )
        signature = sign_fields(self._secrets.signing_key, tags.WRAP_SIG, *signed)
        return sealed.to_json(), signature


def _participants(
    tenant_id: str,
    request: StartRequest,
    names: Mapping[str, str],
    keys: Mapping[str, UserKeyRecord],
) -> tuple[CeremonyParticipant, ...]:
    """Custodians in code-point order of their subject, then the paper holders."""
    custodians = [
        CeremonyParticipant(
            holder_index=index,
            holder_ref=sub,
            kind=CUSTODIAN,
            display_name=names[sub],
            enc_pub=keys[sub].enc_pub,
            sig_pub=keys[sub].sig_pub,
            fingerprint=keys[sub].fingerprint,
        )
        for index, sub in enumerate(sorted(request.custodians), start=1)
    ]
    device = request.paper_device_pub
    if device is None:
        return tuple(custodians)
    paper = [
        CeremonyParticipant(
            holder_index=len(custodians) + number,
            holder_ref=f"paper-{number}",
            kind=PAPER,
            display_name=None,
            enc_pub=device,
            sig_pub=None,
            fingerprint=paper_device_fingerprint(tenant_id, device),
        )
        for number in range(1, request.k + 1)
    ]
    return tuple(custodians + paper)

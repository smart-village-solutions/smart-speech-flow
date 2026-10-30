"""Changing the custodians without touching the archive (spec §9.7).

An org admin names a new holder set and k current holders to deal. The
dealers' Lagrange-weighted shares sum to the same x, so X, the key ID and
every recovery wrap stay. Custodian dealers deal through the ceremony's own
dealing route; paper sheets are typed in on the ceremony device and dealt here.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .audit import AuditEvent
from .ceremony import CustodianDirectory, StartRequest, participants_for
from .ceremony_model import (
    CEREMONY_LIFETIME,
    CUSTODIAN,
    PAPER,
    RESHARING,
    CeremonyDealer,
    CeremonyError,
    CeremonyParticipant,
    CeremonyRecord,
    CeremonySnapshot,
    DealingRecord,
    DealingSubmission,
    RecoveryKeyRecord,
    conflict,
    dealing_record,
    invalid,
)
from .crypto.aead import EnvelopeError
from .keys import KeyUnreadableError
from .repository import UserKeyRecord
from .resharing_model import (
    HolderGeneration,
    ResharingStart,
    check_last_dealing,
    check_resharing_dealing,
    dealers_of,
    validate_start,
)
from .secrets import ServerLayer

# A holder whose share a key on the server still opens: its active one, or one kept (§9.6).
USABLE_STATES = frozenset({"fresh", "kept"})


class ResharingStore(Protocol):
    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None: ...

    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None: ...

    async def holder_generation(self, tenant_id: str) -> HolderGeneration | None: ...

    async def holder_states(self, tenant_id: str) -> dict[str, str]: ...

    async def user_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, UserKeyRecord]: ...

    async def gateway_keys(self) -> tuple[tuple[str, bytes], ...]: ...

    async def open_ceremony(self, tenant_id: str, now: datetime) -> CeremonySnapshot | None: ...

    async def create_resharing(
        self,
        ceremony: CeremonyRecord,
        participants: Sequence[CeremonyParticipant],
        dealers: Sequence[CeremonyDealer],
        audit: Sequence[AuditEvent],
    ) -> None: ...

    async def dealer_material(
        self, tenant_id: str, dealer_index: int, holder_ref: str
    ) -> tuple[str, UserKeyRecord] | None:
        """The dealer's sealed share and the key the current generation lists for it."""
        ...

    async def add_dealing(
        self, tenant_id: str, ceremony_id: str, dealing: DealingRecord, audit: AuditEvent
    ) -> CeremonySnapshot: ...

    async def record_audit(self, event: AuditEvent) -> None: ...


@dataclass(frozen=True)
class DealerKey:
    """A dealer's share and the key that opens it, its blob out of the server layer."""

    dealer_index: int
    encrypted_share: str
    key: UserKeyRecord
    blob: str
    # False for a custodian who left: there is no vault to unlock, only this key (§9.8).
    has_active_key: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _custodian_dealers(start: ResharingStart, current: HolderGeneration) -> list[str]:
    return [
        holder.holder_ref
        for holder in (current.holder(index) for index in start.dealers)
        if holder is not None and holder.kind == CUSTODIAN
    ]


class ResharingService:
    def __init__(
        self,
        *,
        repository: ResharingStore,
        directory: CustodianDirectory,
        server_layer: ServerLayer,
        clock: Callable[[], datetime] = _now,
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._repository = repository
        self._directory = directory
        self._server_layer = server_layer
        self._clock = clock
        self._new_id = new_id

    async def _current(self, tenant_id: str) -> tuple[RecoveryKeyRecord, HolderGeneration]:
        key = await self._repository.active_recovery_key(tenant_id)
        current = await self._repository.holder_generation(tenant_id)
        if key is None or current is None:
            raise conflict("NO_RECOVERY_KEY", "The tenant has no recovery key to reshare")
        return key, current

    async def _new_set(
        self, tenant_id: str, start: ResharingStart, correlation_id: str
    ) -> tuple[Mapping[str, str], dict[str, UserKeyRecord]]:
        names = await self._directory.custodians(tenant_id, correlation_id)
        if names is None:
            raise CeremonyError(503, "DIRECTORY_UNAVAILABLE", "The staff directory is unavailable")
        if any(sub not in names for sub in start.custodians):
            raise invalid("NOT_A_CUSTODIAN", "A named user lacks the custodian permission")
        keys = await self._repository.user_keys(tenant_id, list(start.custodians))
        if any(sub not in keys for sub in start.custodians):
            raise invalid("CUSTODIAN_NOT_ENROLLED", "A named custodian has no personal key")
        return names, keys

    async def start(
        self, tenant_id: str, starter: str, start: ResharingStart, correlation_id: str
    ) -> CeremonySnapshot:
        key, current = await self._current(tenant_id)
        if start.holders_ceremony_id != current.ceremony_id:
            raise conflict("HOLDERS_CHANGED", "The custodians changed; start again")
        states = await self._repository.holder_states(tenant_id)
        usable = {
            ref: states.get(ref) in USABLE_STATES for ref in _custodian_dealers(start, current)
        }
        validate_start(start, starter, current, usable)
        names, keys = await self._new_set(tenant_id, start, correlation_id)
        now = self._clock()
        ceremony = CeremonyRecord(
            tenant_id=tenant_id,
            ceremony_id=self._new_id(),
            k=start.k,
            started_by=starter,
            started_at=now,
            expires_at=now + CEREMONY_LIFETIME,
            status="dealing",
            gateway_keys=await self._repository.gateway_keys(),
            kind=RESHARING,
            recovery_key_id=key.key_id,
            previous_transcript_hash=current.transcript_hash,
        )
        request = StartRequest(start.k, start.custodians, start.paper_device_pub)
        participants = participants_for(tenant_id, request, names, keys)
        dealers = dealers_of(start, current)
        event = AuditEvent(
            tenant_id, starter, "ceremony_started", f"ceremony:{ceremony.ceremony_id}", now
        )
        await self._repository.create_resharing(ceremony, participants, dealers, [event])
        return CeremonySnapshot(ceremony, participants, (), (), dealers)

    async def _open(self, tenant_id: str, ceremony_id: str) -> CeremonySnapshot:
        snapshot = await self._repository.open_ceremony(tenant_id, self._clock())
        if snapshot is None or snapshot.ceremony.ceremony_id != ceremony_id:
            raise CeremonyError(404, "NO_CEREMONY", "No such ceremony in progress")
        if snapshot.ceremony.kind != RESHARING:
            raise conflict("CEREMONY_STATE", "This ceremony is not a resharing")
        return snapshot

    async def dealer(self, tenant_id: str, user_sub: str, ceremony_id: str) -> DealerKey:
        """Like the key download, each read is audited: it is a chance to guess offline."""
        snapshot = await self._open(tenant_id, ceremony_id)
        dealer = snapshot.custodian_dealer(user_sub)
        if dealer is None:
            raise CeremonyError(403, "NOT_A_PARTICIPANT", "Not a dealer of this resharing")
        # Each read is a chance to guess the blob offline: only while it still has to deal.
        if snapshot.ceremony.status != "dealing" or snapshot.has_dealt(dealer.dealer_index):
            raise conflict("CEREMONY_STATE", "This dealer has nothing left to deal")
        material = await self._repository.dealer_material(tenant_id, dealer.dealer_index, user_sub)
        if material is None:
            raise conflict("DEALER_UNUSABLE", "This dealer's share can no longer be opened")
        encrypted_share, key = material
        sealed = key.encrypted_private
        if sealed is None:
            raise conflict("DEALER_UNUSABLE", "This dealer's share can no longer be opened")
        try:
            blob = self._server_layer.open(sealed, tenant_id=tenant_id, user_sub=user_sub).decode(
                "utf-8"
            )
        except EnvelopeError:
            raise KeyUnreadableError() from None
        await self._repository.record_audit(
            AuditEvent(
                tenant_id, user_sub, "key_blob_read", f"user-key:{key.key_version}", self._clock()
            )
        )
        # A row read, not a blob download: it is not audited and needs no step-up of its own.
        active = await self._repository.active_user_key(tenant_id, user_sub)
        return DealerKey(dealer.dealer_index, encrypted_share, key, blob, active is not None)

    async def paper_deal(
        self,
        tenant_id: str,
        user_sub: str,
        ceremony_id: str,
        dealer_index: int,
        dealing: DealingSubmission,
    ) -> CeremonySnapshot:
        """A sheet typed in on the ceremony device, which only the starter runs."""
        snapshot = await self._open(tenant_id, ceremony_id)
        if user_sub != snapshot.ceremony.started_by:
            raise CeremonyError(403, "NOT_A_PARTICIPANT", "Not this resharing's device")
        dealer = snapshot.dealer(dealer_index)
        if dealer is None or dealer.kind != PAPER:
            raise invalid("INVALID_DEALING", "This index is not a paper sheet that deals")
        if snapshot.ceremony.status != "dealing":
            raise conflict("CEREMONY_STATE", "Dealing is over")
        if snapshot.has_dealt(dealer_index):
            raise conflict("ALREADY_SUBMITTED", "This sheet has already dealt")
        key, current = await self._current(tenant_id)
        check_resharing_dealing(snapshot, dealer, current, dealing)
        now = self._clock()
        record = dealing_record(dealer_index, dealing, now)
        check_last_dealing(snapshot, record, key.recovery_public_key)
        return await self._repository.add_dealing(
            tenant_id,
            ceremony_id,
            record,
            AuditEvent(tenant_id, user_sub, "ceremony_dealt", f"ceremony:{ceremony_id}", now),
        )

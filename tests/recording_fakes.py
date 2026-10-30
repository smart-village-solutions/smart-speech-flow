"""In-memory stand-ins for the recording database, shared by the recording tests."""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.ceremony_model import (
    Activation,
    CeremonySnapshot,
    FailedCeremony,
    RecoveryKeyRecord,
    RecoveryShareRecord,
    computed_transcript_hash,
    mode_of,
    conflict,
)
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.repository import KeyAlreadyEnrolledError, UserKeyRecord
from services.api_gateway.recording.resharing_model import (
    HolderGeneration,
    new_public_shares,
)
from tests import recording_crypto_reference as ref


@dataclass
class FakeRecordingRepository:
    keys: dict[tuple[str, str], UserKeyRecord] = field(default_factory=dict)
    audit: list[AuditEvent] = field(default_factory=list)

    async def active_user_key(self, tenant_id: str, user_sub: str) -> UserKeyRecord | None:
        return self.keys.get((tenant_id, user_sub))

    async def enrol_user_key(self, record: UserKeyRecord, audit: AuditEvent) -> None:
        if (record.tenant_id, record.user_sub) in self.keys:
            raise KeyAlreadyEnrolledError()
        self.keys[(record.tenant_id, record.user_sub)] = record
        self.audit.append(audit)

    async def record_audit(self, event: AuditEvent) -> None:
        self.audit.append(event)


def sealed_blob(tenant_id: str = "tenant-test", user_sub: str = "alice") -> str:
    """A blob with the enrolment work factor; the gateway checks only its shape."""
    return ref.seal_private_keys(
        "Kanne Wolke Ferne Tisch 42",
        tenant_id,
        user_sub,
        {"enc": ref.pkcs8(11), "sig": ref.pkcs8(12)},
        salt=os.urandom(16),
        nonces={"enc": os.urandom(12), "sig": os.urandom(12)},
        params=(65536, 3, 1),
    )


def enrolment_body(tenant_id: str = "tenant-test", user_sub: str = "alice") -> dict[str, str]:
    return {
        "enc_pub": b64url(ref.public_point(11)),
        "sig_pub": b64url(ref.public_point(12)),
        "blob": sealed_blob(tenant_id, user_sub),
    }


def with_kdf(blob: str, **overrides: object) -> str:
    body = json.loads(blob)
    body["kdf"].update(overrides)
    return json.dumps(body)


@dataclass
class FakeCeremonyRepository:
    """The ceremony tables in memory, with the status rules the Postgres repository enforces."""

    keys: dict[str, UserKeyRecord] = field(default_factory=dict)
    gateway: tuple[tuple[str, bytes], ...] = (("gk-test", ref.public_point(99)),)
    ceremonies: dict[str, CeremonySnapshot] = field(default_factory=dict)
    subshares: dict[str, dict[int, Mapping[int, str]]] = field(default_factory=dict)
    recovery_key: RecoveryKeyRecord | None = None
    shares: list[RecoveryShareRecord] = field(default_factory=list)
    audit: list[AuditEvent] = field(default_factory=list)
    aborted: dict[str, FailedCeremony] = field(default_factory=dict)
    usable: int = 0
    # Custodian holders whose share can no longer be opened (§9.6's lost blob).
    unusable: set[str] = field(default_factory=set)

    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None:
        return self.recovery_key

    async def usable_shares(self, tenant_id: str) -> int | None:
        return None if self.recovery_key is None else self.usable

    async def user_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, UserKeyRecord]:
        return {sub: self.keys[sub] for sub in subs if sub in self.keys}

    async def holder_generation(self, tenant_id: str) -> HolderGeneration | None:
        if self.recovery_key is None:
            return None
        holders, transcript = self.recovery_key.current_holders
        snapshot = self.ceremonies.get(holders)
        if snapshot is None:
            return None
        return HolderGeneration(
            holders,
            snapshot.ceremony.k,
            transcript,
            snapshot.participants,
            {share.holder_index: share.holder_public_share for share in self.shares},
        )

    async def previous_had_paper(self, tenant_id: str) -> bool:
        key = self.recovery_key
        holders = None if key is None else self.ceremonies.get(key.current_holders[0])
        if holders is None or holders.ceremony.previous_transcript_hash is None:
            return False
        return any(
            s.paper_holders
            for s in self.ceremonies.values()
            if s.ceremony.transcript_hash == holders.ceremony.previous_transcript_hash
        )

    async def chain(self, tenant_id: str, key_id: str) -> list[CeremonySnapshot]:
        return [
            s
            for s in self.ceremonies.values()
            if s.ceremony.status == "active"
            and key_id in (s.ceremony.ceremony_id, s.ceremony.recovery_key_id)
        ]

    async def record_audit(self, event: AuditEvent) -> None:
        self.audit.append(event)

    async def holder_states(self, tenant_id: str) -> dict[str, str]:
        generation = await self.holder_generation(tenant_id)
        if generation is None:
            return {}
        return {
            p.holder_ref: "lost" if p.holder_ref in self.unusable else "fresh"
            for p in generation.participants
            if p.kind == "custodian"
        }

    async def dealer_material(
        self, tenant_id: str, dealer_index: int, holder_ref: str
    ) -> tuple[str, UserKeyRecord] | None:
        share = next(s for s in self.shares if s.holder_index == dealer_index)
        if holder_ref in self.unusable or share.encrypted_share is None:
            return None
        return share.encrypted_share, self.keys[holder_ref]

    async def create_resharing(self, ceremony, participants, dealers, audit) -> None:
        if await self.open_ceremony(ceremony.tenant_id, ceremony.started_at) is not None:
            raise conflict("CEREMONY_IN_PROGRESS", "in progress")
        self.ceremonies[ceremony.ceremony_id] = CeremonySnapshot(
            ceremony, tuple(participants), (), (), tuple(dealers)
        )
        self.subshares[ceremony.ceremony_id] = {}
        self.audit.extend(audit)

    async def gateway_keys(self) -> tuple[tuple[str, bytes], ...]:
        return self.gateway

    async def open_ceremony(self, tenant_id: str, now: datetime) -> CeremonySnapshot | None:
        for snapshot in self.ceremonies.values():
            ceremony = snapshot.ceremony
            if ceremony.status in ("dealing", "confirming") and ceremony.expires_at > now:
                return snapshot
        return None

    async def last_failed_ceremony(self, tenant_id: str, now: datetime) -> FailedCeremony | None:
        if not self.ceremonies:
            return None
        latest = max(self.ceremonies.values(), key=lambda s: s.ceremony.started_at).ceremony
        if latest.status == "aborted":
            return self.aborted[latest.ceremony_id]
        if latest.status in ("dealing", "confirming") and latest.expires_at <= now:
            return FailedCeremony(latest.ceremony_id, "expired", latest.expires_at)
        return None

    async def subshares_for(
        self, tenant_id: str, ceremony_id: str, recipients: Collection[int]
    ) -> dict[int, dict[int, str]]:
        dealt = self.subshares[ceremony_id]
        return {i: {j: sealed[i] for j, sealed in dealt.items()} for i in recipients}

    async def create_ceremony(self, ceremony, participants, audit) -> None:
        if self.recovery_key is not None:
            raise conflict("RECOVERY_KEY_EXISTS", "exists")
        if await self.open_ceremony(ceremony.tenant_id, ceremony.started_at) is not None:
            raise conflict("CEREMONY_IN_PROGRESS", "in progress")
        self.ceremonies[ceremony.ceremony_id] = CeremonySnapshot(
            ceremony, tuple(participants), (), ()
        )
        self.subshares[ceremony.ceremony_id] = {}
        self.audit.extend(audit)

    def _locked(self, ceremony_id: str, now: datetime, statuses: tuple[str, ...]):
        snapshot = self.ceremonies.get(ceremony_id)
        if snapshot is None:
            raise conflict("NO_CEREMONY", "none")
        ceremony = snapshot.ceremony
        if ceremony.status not in statuses or ceremony.expires_at <= now:
            raise conflict("CEREMONY_STATE", "state")
        return snapshot

    def _set(self, ceremony_id: str, **changes) -> None:
        snapshot = self.ceremonies[ceremony_id]
        self.ceremonies[ceremony_id] = replace(
            snapshot, ceremony=replace(snapshot.ceremony, **changes)
        )

    async def add_dealing(self, tenant_id, ceremony_id, dealing, audit) -> CeremonySnapshot:
        snapshot = self._locked(ceremony_id, dealing.dealt_at, ("dealing",))
        if snapshot.has_dealt(dealing.dealer_index):
            raise conflict("ALREADY_SUBMITTED", "dealt")
        public = replace(dealing, subshares={})
        after = replace(snapshot, dealings=(*snapshot.dealings, public))
        events = [audit]
        if after.all_dealt():
            # Computed before anything is stored: a failure here stores nothing, as in Postgres.
            transcript = computed_transcript_hash(after)
            ceremony = replace(after.ceremony, status="confirming", transcript_hash=transcript)
            after = replace(after, ceremony=ceremony)
            events.append(replace(audit, event_type="ceremony_dealt_all"))
        self.subshares[ceremony_id][dealing.dealer_index] = dealing.subshares
        self.ceremonies[ceremony_id] = after
        self.audit.extend(events)
        return after

    async def add_confirmation(
        self, tenant_id, ceremony_id, confirmation, audit, activation: Activation
    ) -> str:
        snapshot = self._locked(ceremony_id, confirmation.confirmed_at, ("confirming",))
        if snapshot.has_confirmed(confirmation.holder_index):
            raise conflict("ALREADY_SUBMITTED", "confirmed")
        after = replace(snapshot, confirmations=(*snapshot.confirmations, confirmation))
        return self._commit(after, audit, activation)

    async def confirm_paper(self, tenant_id, ceremony_id, audit, activation: Activation) -> str:
        snapshot = self._locked(ceremony_id, audit.at, ("confirming",))
        if snapshot.ceremony.paper_confirmed_at is not None:
            raise conflict("CEREMONY_STATE", "printed")
        after = replace(snapshot, ceremony=replace(snapshot.ceremony, paper_confirmed_at=audit.at))
        return self._commit(after, audit, activation)

    def _commit(self, after: CeremonySnapshot, audit: AuditEvent, activation: Activation) -> str:
        """Stores `after`, activating it if ready; an activation failure stores nothing."""
        ceremony_id = after.ceremony.ceremony_id
        if not after.ready_to_activate():
            self.ceremonies[ceremony_id] = after
            self.audit.append(audit)
            return after.ceremony.status
        if after.ceremony.kind == "resharing":
            return self._reshare(after, audit)
        key, shares, activated = activation(after)
        self.ceremonies[ceremony_id] = replace(
            after, ceremony=replace(after.ceremony, status="active")
        )
        self.recovery_key, self.shares = key, list(shares)
        self.audit.extend([audit, activated])
        return "active"

    def _reshare(self, after: CeremonySnapshot, audit: AuditEvent) -> str:
        """The Postgres activation's outcome: the holders must not have moved on meanwhile."""
        ceremony = after.ceremony
        key = self.recovery_key
        assert key is not None
        if key.current_holders[1] != ceremony.previous_transcript_hash:
            self.ceremonies[ceremony.ceremony_id] = replace(
                after, ceremony=replace(ceremony, status="aborted")
            )
            self.aborted[ceremony.ceremony_id] = FailedCeremony(
                ceremony.ceremony_id, "chain_invalid", audit.at
            )
            self.audit.append(audit)
            return "aborted"
        public = new_public_shares(after)
        sealed = {c.holder_index: c.encrypted_share for c in after.confirmations}
        self.shares = [
            RecoveryShareRecord(
                p.holder_index, p.holder_ref, public[p.holder_index], sealed.get(p.holder_index)
            )
            for p in after.participants
        ]
        self.recovery_key = replace(
            key,
            holders_ceremony_id=ceremony.ceremony_id,
            holders_transcript_hash=ceremony.transcript_hash,
            k=ceremony.k,
            n=len(after.participants),
            mode=mode_of(ceremony.k),
        )
        self.ceremonies[ceremony.ceremony_id] = replace(
            after, ceremony=replace(ceremony, status="active")
        )
        self.audit.extend(
            [audit, replace(audit, event_type="recovery_key_reshared", object_ref=key.key_id)]
        )
        return "active"

    async def abort(self, tenant_id, ceremony_id, reason, audit) -> None:
        self._locked(ceremony_id, audit.at, ("dealing", "confirming"))
        self._set(ceremony_id, status="aborted")
        self.aborted[ceremony_id] = FailedCeremony(ceremony_id, reason, audit.at)
        self.audit.append(audit)


@dataclass
class FakeCustodianDirectory:
    """None stands for Studio being unreachable."""

    names: dict[str, str] | None = field(default_factory=dict)

    async def custodians(self, tenant_id: str, correlation_id: str) -> dict[str, str] | None:
        return self.names

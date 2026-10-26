"""In-memory stand-ins for the recording database, shared by the recording tests."""

from __future__ import annotations

import json
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.ceremony_model import (
    CeremonySnapshot,
    FailedCeremony,
    RecoveryKeyRecord,
    RecoveryShareRecord,
    conflict,
)
from services.api_gateway.recording.crypto.encoding import b64url
from services.api_gateway.recording.repository import KeyAlreadyEnrolledError, UserKeyRecord
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

    async def active_recovery_key(self, tenant_id: str) -> RecoveryKeyRecord | None:
        return self.recovery_key

    async def user_keys(self, tenant_id: str, subs: Sequence[str]) -> dict[str, UserKeyRecord]:
        return {sub: self.keys[sub] for sub in subs if sub in self.keys}

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
        self.subshares[ceremony_id][dealing.dealer_index] = dealing.subshares
        public = replace(dealing, subshares={})
        snapshot = replace(snapshot, dealings=(*snapshot.dealings, public))
        self.ceremonies[ceremony_id] = snapshot
        self.audit.append(audit)
        return snapshot

    async def begin_confirming(self, tenant_id, ceremony_id, transcript_hash, audit) -> None:
        if self.ceremonies[ceremony_id].ceremony.status == "dealing":
            self._set(ceremony_id, status="confirming", transcript_hash=transcript_hash)
            self.audit.append(audit)

    async def add_confirmation(self, tenant_id, ceremony_id, confirmation, audit) -> None:
        snapshot = self._locked(ceremony_id, confirmation.confirmed_at, ("confirming",))
        if snapshot.has_confirmed(confirmation.holder_index):
            raise conflict("ALREADY_SUBMITTED", "confirmed")
        self.ceremonies[ceremony_id] = replace(
            snapshot, confirmations=(*snapshot.confirmations, confirmation)
        )
        self.audit.append(audit)

    async def confirm_paper(self, tenant_id, ceremony_id, audit) -> None:
        self._locked(ceremony_id, audit.at, ("confirming",))
        self._set(ceremony_id, paper_confirmed_at=audit.at)
        self.audit.append(audit)

    async def abort(self, tenant_id, ceremony_id, reason, audit) -> None:
        self._locked(ceremony_id, audit.at, ("dealing", "confirming"))
        self._set(ceremony_id, status="aborted")
        self.aborted[ceremony_id] = FailedCeremony(ceremony_id, reason, audit.at)
        self.audit.append(audit)

    async def activate(self, tenant_id, key, shares, audit) -> bool:
        if self.ceremonies[key.key_id].ceremony.status != "confirming":
            return False
        self._set(key.key_id, status="active")
        self.recovery_key, self.shares = key, list(shares)
        self.audit.append(audit)
        return True


@dataclass
class FakeCustodianDirectory:
    """None stands for Studio being unreachable."""

    names: dict[str, str] | None = field(default_factory=dict)

    async def custodians(self, tenant_id: str, correlation_id: str) -> dict[str, str] | None:
        return self.names

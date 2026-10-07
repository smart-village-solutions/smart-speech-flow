"""Tenant-bound conversation identity and the session record's configuration revision."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from services.api_gateway.session_models import Session
from services.api_gateway.tenant_session import TenantSessionKey

REVISION = f"sha256:{'a' * 64}"
# Real records, written by Session.to_dict(include_messages=True) before the v2 cutover
# (d2837b5), so they carry the v1 runtime-configuration snapshot.
FIXTURES = Path(__file__).parent / "fixtures" / "session_records"
V1_REVISION = "sha256:fa5df6f4e2b0c4abcbda2f3c96981f1a5aa2475b0bf8a88f092d1ee99e241dbb"


def _v1_record(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_tenant_session_key_uses_unpadded_urlsafe_redis_component() -> None:
    key = TenantSessionKey("stadt:kassel/ä", "ABC12345")

    assert key.redis_tenant_component == "c3RhZHQ6a2Fzc2VsL8Ok"
    assert key.tenant_ref == sha256("stadt:kassel/ä".encode()).hexdigest()[:12]


@pytest.mark.parametrize(
    ("tenant_id", "session_id"),
    [("", "ABC12345"), ("x" * 129, "ABC12345"), ("tenant-a", "../escape")],
)
def test_tenant_session_key_rejects_invalid_identifiers(tenant_id: str, session_id: str) -> None:
    with pytest.raises(ValueError):
        TenantSessionKey(tenant_id, session_id)


@pytest.mark.parametrize("name", ["v1-active", "v1-terminated"])
def test_a_v1_record_loads_with_its_configuration_revision(name: str) -> None:
    record = _v1_record(name)
    assert "configuration_revision" not in record

    session = Session.from_dict(record)

    assert session.configuration_revision == V1_REVISION
    assert session.key == TenantSessionKey("tenant-kassel", record["id"])
    assert session.status.value == record["status"]
    assert session.consent_status.value == record["consent_status"]
    assert session.owner_ref == record["owner_ref"]


def test_a_v1_active_record_keeps_its_messages_and_their_decisions() -> None:
    session = Session.from_dict(_v1_record("v1-active"))

    [message] = session.messages
    assert message.original_text == "Hello"
    assert (
        message.record_authorized,
        message.original_audio_authorized,
        message.translated_audio_authorized,
    ) == (True, True, True)


def test_a_v1_record_is_rewritten_with_its_revision() -> None:
    restored = Session.from_dict(_v1_record("v1-active"))

    payload = restored.to_dict(include_messages=True)

    assert payload["configuration_revision"] == V1_REVISION
    assert Session.from_dict(payload).configuration_revision == V1_REVISION


def test_a_record_still_carries_the_key_the_previous_gateway_requires() -> None:
    # Rollback safety for one release: the v1 gateway's from_dict reads these three
    # keys unconditionally and quarantines the record without them. It never parses
    # canonical_json outside tests. Remove with the v1 compatibility in PR 14.
    payload = Session(
        id="ABC12345", tenant_id="tenant-a", configuration_revision=REVISION
    ).to_dict(include_messages=True)

    assert payload["runtime_configuration"] == {
        "configuration_revision": REVISION,
        "authorization_revision": REVISION,
        "canonical_json": "{}",
    }


def test_session_round_trip_preserves_tenant_and_revision() -> None:
    session = Session(id="ABC12345", tenant_id="tenant-a", configuration_revision=REVISION)

    restored = Session.from_dict(session.to_dict(include_messages=True))

    assert restored.key == TenantSessionKey("tenant-a", "ABC12345")
    assert restored.configuration_revision == REVISION


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.pop("configuration_revision"),
        lambda record: record.update(configuration_revision=None),
        lambda record: record.update(configuration_revision=7),
        lambda record: record.update(configuration_revision=""),
        lambda record: record.update(configuration_revision="sha256:x"),
        lambda record: record.update(configuration_revision=f"sha256:{'A' * 64}"),
    ],
)
def test_a_record_without_a_valid_revision_is_rejected(mutate) -> None:
    payload = Session(id="ABC12345", tenant_id="tenant-a", configuration_revision=REVISION).to_dict(
        include_messages=True
    )
    del payload["runtime_configuration"]
    mutate(payload)

    with pytest.raises(ValueError):
        Session.from_dict(payload)


@pytest.mark.parametrize(
    "snapshot",
    [None, "sha256:x", {"canonical_json": "{}"}, {"configuration_revision": "revision-a"}],
)
def test_a_v1_record_with_a_broken_snapshot_is_rejected(snapshot) -> None:
    record = _v1_record("v1-active")
    record["runtime_configuration"] = snapshot

    with pytest.raises(ValueError):
        Session.from_dict(record)


def test_the_public_dict_carries_no_revision() -> None:
    session = Session(id="ABC12345", tenant_id="tenant-a", configuration_revision=REVISION)

    public = session.to_public_dict()

    assert "configuration_revision" not in public
    assert "runtime_configuration" not in public


def test_session_payload_without_tenant_scope_is_rejected() -> None:
    session = Session(id="ABC12345", tenant_id="tenant-a", configuration_revision=REVISION)
    payload = session.to_dict(include_messages=True)
    del payload["tenant_id"]

    with pytest.raises((KeyError, TypeError, ValueError)):
        Session.from_dict(payload)

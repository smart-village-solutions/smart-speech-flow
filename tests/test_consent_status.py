"""The consent status is server-side session state and defaults to pending."""

from services.api_gateway.consent import ConsentStatus
from services.api_gateway.session_manager import Session
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = "sha256:" + "a" * 64
SNAPSHOT = RuntimeConfigurationSnapshot(REVISION, REVISION, "{}")


def _session() -> Session:
    return Session(id="s1", tenant_id="tenant-kassel", runtime_configuration=SNAPSHOT)


def test_the_four_contract_states_are_the_only_states():
    assert {status.value for status in ConsentStatus} == {
        "pending",
        "granted",
        "declined",
        "policy_disabled",
    }


def test_a_new_session_starts_pending():
    assert _session().consent_status is ConsentStatus.PENDING


def test_the_consent_status_survives_a_serialisation_round_trip():
    session = _session()
    session.consent_status = ConsentStatus.GRANTED

    restored = Session.from_dict(session.to_dict())

    assert restored.consent_status is ConsentStatus.GRANTED


def test_an_unknown_stored_status_restores_as_pending():
    payload = _session().to_dict()
    payload["consent_status"] = "granted_probably"

    assert Session.from_dict(payload).consent_status is ConsentStatus.PENDING


def test_a_record_written_before_consent_existed_restores_as_pending():
    payload = _session().to_dict()
    del payload["consent_status"]

    assert Session.from_dict(payload).consent_status is ConsentStatus.PENDING

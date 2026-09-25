"""Consent-gated persistence, observed through what survives a session's end.

Content is delivered either way; the gate decides only what an administrator
can still read once the conversation has been terminated.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("speech_services")


def _retained_after_termination(client, conversations, session_id: str) -> list[str]:
    conversations.terminate(session_id)
    listing = client.get(f"/api/admin/session/{session_id}/messages")
    assert listing.status_code == 200
    return [message["id"] for message in listing.json()["messages"]]


def _deliver_one_message(conversations, session_id: str) -> str:
    response = conversations.send_text(session_id)
    assert response.status_code == 200
    return response.json()["message_id"]


@pytest.mark.usefixtures("studio")
def test_granted_consent_under_ask_mode_retains_the_message(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "en", consent=True)
    message_id = _deliver_one_message(conversations, session_id)

    assert _retained_after_termination(client, conversations, session_id) == [message_id]


@pytest.mark.usefixtures("studio")
@pytest.mark.parametrize("consent", [False, None])
def test_declined_or_unanswered_consent_discards_the_message(client, conversations, consent):
    session_id = conversations.create()
    conversations.activate(session_id, "en", consent=consent)
    _deliver_one_message(conversations, session_id)

    assert _retained_after_termination(client, conversations, session_id) == []


def test_a_tenant_that_disabled_storage_discards_the_message(client, conversations, studio):
    studio.storage_mode = "disabled"
    session_id = conversations.create()
    conversations.activate(session_id, "en", consent=True)
    _deliver_one_message(conversations, session_id)

    assert _retained_after_termination(client, conversations, session_id) == []


def test_a_studio_failure_at_write_time_discards_the_message(client, conversations, studio):
    session_id = conversations.create()
    conversations.activate(session_id, "en", consent=True)
    studio.fail("runtime_configuration_unavailable", retryable=True)
    _deliver_one_message(conversations, session_id)

    assert _retained_after_termination(client, conversations, session_id) == []


@pytest.mark.usefixtures("unbound_persistence_gate")
def test_an_unbound_persistence_gate_discards_the_message(client, conversations):
    session_id = conversations.create()
    conversations.activate(session_id, "en", consent=True)
    _deliver_one_message(conversations, session_id)

    assert _retained_after_termination(client, conversations, session_id) == []


@pytest.mark.usefixtures("studio")
def test_consent_and_authorization_state_never_reach_a_client(client, conversations):
    session_id = conversations.create()
    activated = conversations.activate(session_id, "en", consent=True)
    _deliver_one_message(conversations, session_id)

    assert not [field for field in activated if "consent" in field]
    for role in ("admin", "customer"):
        [message] = client.get(f"/api/{role}/session/{session_id}/messages").json()["messages"]
        assert not [field for field in message if "authoriz" in field or "consent" in field]

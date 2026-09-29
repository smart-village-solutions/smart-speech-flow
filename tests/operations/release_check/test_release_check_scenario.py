from scripts.release_check.config import Operator, Tenant
from scripts.release_check.evidence import Evidence
from scripts.release_check.scenario import Conversation, next_frame, run_conversation
from tests.operations.release_check.release_check_fakes import FakeGateway, FakeSocket

TENANT = Tenant("A", "tenant-a", "en", "ask", (Operator("u1", "p1"), Operator("u2", "p2")))


def _conversation() -> Conversation:
    return Conversation(tenant=TENANT, index=1, token="token-A1", consent=True)


def _failed(evidence: Evidence) -> list[str]:
    return [check.name for check in evidence.checks if not check.passed]


async def test_a_healthy_conversation_passes_every_step():
    gateway, evidence, conversation = FakeGateway(), Evidence(), _conversation()

    await run_conversation(gateway, evidence, conversation)

    assert _failed(evidence) == []
    assert conversation.completed
    assert len(conversation.message_ids) == 4
    assert gateway.sessions[conversation.session_id].consent is True
    assert [check.name for check in evidence.checks][:3] == [
        "A1 create session",
        "A1 guest reads pending session",
        "A1 realtime ticket",
    ]


async def test_an_undelivered_message_fails_the_conversation(monkeypatch):
    monkeypatch.setattr("scripts.release_check.scenario.DELIVERY_TIMEOUT", 0.05)
    gateway, evidence, conversation = FakeGateway(), Evidence(), _conversation()
    gateway.drop_delivery = True

    await run_conversation(gateway, evidence, conversation)

    assert _failed(evidence) == ["A1 admin message 1 delivered"]
    assert not conversation.completed


async def test_a_failed_creation_stops_the_conversation():
    gateway, evidence, conversation = FakeGateway(), Evidence(), _conversation()
    gateway.fail_create_for = {"token-A1"}

    await run_conversation(gateway, evidence, conversation)

    assert [check.name for check in evidence.checks] == ["A1 create session"]
    assert conversation.session_id is None


async def test_heartbeats_are_answered_while_waiting():
    gateway, evidence, conversation = FakeGateway(), Evidence(), _conversation()
    gateway.ping_before_ack = True

    await run_conversation(gateway, evidence, conversation)

    session = gateway.sessions[conversation.session_id]
    assert {"type": "heartbeat_pong", "ping_id": "p1"} in session.admin.sent
    assert conversation.completed


async def test_no_session_id_reaches_the_report():
    gateway, evidence, conversation = FakeGateway(), Evidence(), _conversation()

    await run_conversation(gateway, evidence, conversation)

    assert conversation.session_id not in evidence.to_markdown()


async def test_frames_that_are_not_json_objects_are_skipped():
    socket = FakeSocket()
    socket.inbox.put_nowait("42")
    socket.inbox.put_nowait("not json")
    socket.push({"type": "connection_ack"})

    frame = await next_frame(socket, lambda f: f.get("type") == "connection_ack", 1.0)

    assert frame == {"type": "connection_ack"}

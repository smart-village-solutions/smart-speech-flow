import pytest

from scripts.release_check.config import Operator, Tenant
from scripts.release_check.evidence import Evidence
from scripts.release_check.isolation import check_colleague_denial, check_isolation
from scripts.release_check.scenario import Conversation, run_conversation
from tests.operations.release_check.release_check_fakes import FakeGateway

OPERATORS = (Operator("u1", "p1"), Operator("u2", "p2"))
TENANT_A = Tenant("A", "tenant-a", "en", "ask", OPERATORS)
TENANT_B = Tenant("B", "tenant-b", "tr", "ask", OPERATORS)


async def _live_pair(gateway: FakeGateway) -> tuple[Conversation, Conversation]:
    first = Conversation(tenant=TENANT_A, index=1, token="token-A1", consent=True)
    second = Conversation(tenant=TENANT_B, index=1, token="token-B1", consent=True)
    for conversation in (first, second):
        await run_conversation(gateway, Evidence(), conversation)
    return first, second


async def _colleagues(gateway: FakeGateway) -> tuple[Conversation, Conversation]:
    first = Conversation(tenant=TENANT_A, index=1, token="token-A1", consent=True)
    second = Conversation(tenant=TENANT_A, index=2, token="token-A2", consent=False)
    for conversation in (first, second):
        await run_conversation(gateway, Evidence(), conversation)
    return first, second


async def _colleague_failures(gateway: FakeGateway) -> list[str]:
    first, second = await _colleagues(gateway)
    evidence = Evidence()
    await check_colleague_denial(gateway, evidence, first, second)
    return [check.name for check in evidence.checks if not check.passed]


async def _failures(gateway: FakeGateway) -> list[str]:
    first, second = await _live_pair(gateway)
    evidence = Evidence()
    await check_isolation(gateway, evidence, first, second)
    return [check.name for check in evidence.checks if not check.passed]


async def test_a_correct_gateway_passes_every_denial():
    gateway = FakeGateway()
    first, second = await _live_pair(gateway)
    evidence = Evidence()

    await check_isolation(gateway, evidence, first, second)

    assert [check.name for check in evidence.checks if not check.passed] == []
    # 2 directions x (7 foreign routes + foreign socket + target unaffected) + 6 selectors
    assert len(evidence.checks) == 24


@pytest.mark.parametrize(
    ("knob", "expected"),
    [
        ("leak_cross_tenant", "A1 → B1 status is not found"),
        ("accept_selectors", "A1 selector in query is rejected"),
        ("accept_foreign_ticket", "A1 → B1 own ticket refused on foreign socket"),
    ],
)
async def test_each_leak_turns_the_check_red(knob, expected):
    gateway = FakeGateway()
    setattr(gateway, knob, True)

    assert expected in await _failures(gateway)


async def test_colleagues_in_one_tenant_are_denied_each_others_sessions():
    gateway = FakeGateway()
    first, second = await _colleagues(gateway)
    evidence = Evidence()

    await check_colleague_denial(gateway, evidence, first, second)

    assert [check.name for check in evidence.checks if not check.passed] == []
    # 2 directions x (7 colleague routes + colleague socket + target unaffected)
    assert len(evidence.checks) == 18
    assert "A2 → A1 terminate is not found" in [check.name for check in evidence.checks]


async def test_a_gateway_that_lets_colleagues_in_turns_the_check_red():
    gateway = FakeGateway()
    gateway.leak_to_colleague = True

    failures = await _colleague_failures(gateway)

    assert "A1 → A2 status is not found" in failures
    assert "A2 → A1 realtime ticket is not found" in failures

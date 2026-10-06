"""The public WebSocket monitoring surface: one health route with aggregate counts (#348).

Connection metadata is served only by the authenticated admin listings, which
test_contract_websocket.py and test_contract_admin_rest.py cover.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.gateway_contract.contract_support import ALLOWED_ORIGIN, TENANT_A, TENANT_B

MONITORING_PREFIX = "/api/websocket/monitoring"
ORIGIN = {"Origin": ALLOWED_ORIGIN}
HEALTH_FIELDS = {
    "status",
    "active_connections",
    "healthy_connections",
    "stale_connections",
    "sessions_with_connections",
    "monitoring_active",
    "last_check",
}


def _mounted_paths(routes) -> Iterator[str]:
    """Every served path, including routes left out of the OpenAPI document.

    FastAPI 0.139 wraps an included router in one object whose effective
    contexts carry the prefixed paths.
    """
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            yield route.path
            continue
        for context in contexts():
            yield context.path or context.original_route.path


def test_health_is_the_only_monitoring_route(gateway):
    monitoring = {path for path in _mounted_paths(gateway.routes) if MONITORING_PREFIX in path}

    assert monitoring == {f"{MONITORING_PREFIX}/health"}


@pytest.mark.parametrize("path", ["/stats", "/connections"])
def test_the_former_global_listings_are_not_served(client, identity, path):
    identity.unauthenticated()

    response = client.get(f"{MONITORING_PREFIX}{path}")

    assert response.status_code == 404


def test_health_reports_only_aggregate_counts_across_tenants(
    client, conversations, identity, gateway_dependencies
):
    own = conversations.create(TENANT_A)
    foreign = conversations.create(TENANT_B)
    identity.act_as(TENANT_A)
    admin_url = f"/ws/admin/{own}?ticket={conversations.ticket(own)}"

    with client.websocket_connect(admin_url, headers=ORIGIN) as admin_socket:
        admin_socket.receive_json()
        with client.websocket_connect(f"/ws/customer/{foreign}", headers=ORIGIN) as customer:
            customer.receive_json()
            connection_ids = set(gateway_dependencies.websocket_monitor.get_active_connections())
            identity.unauthenticated()
            response = client.get(f"{MONITORING_PREFIX}/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "data", "timestamp"}
    assert set(body["data"]) == HEALTH_FIELDS
    assert body["data"]["active_connections"] == 2
    assert body["data"]["sessions_with_connections"] == 2
    assert len(connection_ids) == 2
    for identifier in {own, foreign, TENANT_A, TENANT_B, "admin", "customer", *connection_ids}:
        assert identifier not in response.text

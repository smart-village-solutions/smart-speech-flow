"""Overflow on the polling fallback must be counted, never silent.

This is the path a client uses when WebSockets fail -- the worst networks. It
dropped the oldest queued translation past 100 and returned True, so Q3
(delivery success) and Q7 (ordering) could not be measured and the user simply
lost a message.
"""

import logging

import pytest

from services.api_gateway.websocket_fallback import (
    FallbackConfig,
    FallbackReason,
    POLLING_MAX_CLIENTS_PER_SESSION_CLIENT_TYPE,
    POLLING_QUEUE_MAX_MESSAGES,
    WebSocketFallbackManager,
)


@pytest.fixture
async def polling_client():
    manager = WebSocketFallbackManager(
        FallbackConfig(enable_jitter=False, enable_user_notifications=False)
    )
    polling_id = await manager.activate_polling_fallback(
        "session-1",
        "customer",
        "https://console.example",
        FallbackReason.NETWORK_ERROR,
    )
    return manager, polling_id


def _dropped(
    manager: WebSocketFallbackManager, client_type: str = "customer"
) -> float:
    return manager.messages_dropped.labels(client_type=client_type)._value.get()


class TestTheBoundIsStillEnforced:
    def test_the_queue_does_not_grow_without_limit(self, polling_client):
        manager, polling_id = polling_client

        for index in range(POLLING_QUEUE_MAX_MESSAGES + 50):
            manager.send_message_to_polling_client(
                polling_id, {"type": "translation", "seq": index}
            )

        assert (
            len(manager.polling_clients[polling_id].message_queue)
            == POLLING_QUEUE_MAX_MESSAGES
        )


class TestOverflowIsVisible:
    def test_a_dropped_message_increments_the_counter(self, polling_client):
        manager, polling_id = polling_client
        before = _dropped(manager)

        for index in range(POLLING_QUEUE_MAX_MESSAGES + 5):
            manager.send_message_to_polling_client(
                polling_id, {"type": "translation", "seq": index}
            )

        assert _dropped(manager) - before == 5

    def test_no_drop_means_no_increment(self, polling_client):
        manager, polling_id = polling_client
        before = _dropped(manager)

        manager.send_message_to_polling_client(
            polling_id, {"type": "translation", "seq": 0}
        )

        assert _dropped(manager) == before

    def test_the_send_reports_failure_when_it_dropped_something(self, polling_client):
        manager, polling_id = polling_client

        for index in range(POLLING_QUEUE_MAX_MESSAGES):
            assert (
                manager.send_message_to_polling_client(polling_id, {"seq": index})
                is True
            )

        assert (
            manager.send_message_to_polling_client(
                polling_id, {"seq": POLLING_QUEUE_MAX_MESSAGES}
            )
            is False
        )


class TestTheCounterSurvivesTheRegistryBoundary:
    """A counter is not a signal until Prometheus can scrape it.

    /metrics serves app.state.prometheus_registry. A series left on
    prometheus_client's global default registry is counted in-process, appears
    in no scrape, and can carry no alert — which is the same "signal that looks
    present but cannot fire" defect this branch exists to remove. Reading the
    counter object directly cannot catch that; only the endpoint body can.
    """

    async def test_a_real_drop_reaches_the_metrics_endpoint(self):
        import services.api_gateway.app  # noqa: F401  binds the gateway registry
        from services.api_gateway.routes.metrics import metrics
        from services.api_gateway.websocket_fallback import fallback_manager

        polling_id = await fallback_manager.activate_polling_fallback(
            "session-metrics", "customer", None, FallbackReason.NETWORK_ERROR
        )
        try:
            for index in range(POLLING_QUEUE_MAX_MESSAGES + 2):
                fallback_manager.send_message_to_polling_client(
                    polling_id, {"type": "translation", "seq": index}
                )
            body = metrics().body.decode("utf-8")
        finally:
            fallback_manager.deactivate_polling_fallback(polling_id)

        assert "websocket_polling_messages_dropped_total" in body, (
            "the drop counter is not in the scraped registry; overflow is "
            "counted only inside the process"
        )
        sample = next(
            line
            for line in body.splitlines()
            if line.startswith(
                'websocket_polling_messages_dropped_total{client_type="customer"}'
            )
        )
        assert float(sample.rsplit(" ", 1)[1]) > 0


class TestTheLabelCannotBeMintedByAClient:
    """client_type arrives unvalidated from POST /api/websocket/polling/activate,
    which has no auth dependency. An unbounded label value is a cardinality
    blowup."""

    async def test_an_unrecognised_client_type_is_folded_into_unknown(self):
        manager = WebSocketFallbackManager(
            FallbackConfig(enable_jitter=False, enable_user_notifications=False)
        )
        attacker_value = "attacker-" + "x" * 100
        polling_id = await manager.activate_polling_fallback(
            "session-1", attacker_value, None, FallbackReason.NETWORK_ERROR
        )

        for index in range(POLLING_QUEUE_MAX_MESSAGES + 1):
            manager.send_message_to_polling_client(polling_id, {"seq": index})

        assert _dropped(manager, "unknown") == 1
        assert (attacker_value,) not in manager.messages_dropped._metrics


class TestTheOverflowWarningIsSafeToLog:
    """The dropped message's `type` is an unconstrained client string (CWE-117),
    and a log line about a lost message must not leak who lost it."""

    def test_it_names_the_sanitized_type_and_no_identifiers(
        self, polling_client, caplog
    ):
        manager, polling_id = polling_client
        session_id = manager.polling_clients[polling_id].session_id
        forged = "translation\nWARNING: admin session terminated"

        with caplog.at_level(
            logging.WARNING, logger="services.api_gateway.websocket_fallback"
        ):
            for _ in range(POLLING_QUEUE_MAX_MESSAGES + 1):
                manager.send_message_to_polling_client(polling_id, {"type": forged})

        warning = next(m for m in caplog.messages if "Polling queue full" in m)

        assert "translation\\nWARNING: admin session terminated" in warning
        assert "\n" not in warning, "an unescaped newline can forge a log record"
        assert session_id not in warning
        assert polling_id not in warning


class TestThePollingClientMapIsBounded:
    """`/api/websocket/polling/activate` has no authentication -- it checks
    only that the session exists. While polling ids ended in a timestamp,
    repeat activations inside one second collided and overwrote each other,
    which accidentally capped the map. Unique ids removed that accident, so the
    bound has to be explicit."""

    async def test_repeat_activations_do_not_grow_the_map_without_limit(self):
        manager = WebSocketFallbackManager(
            FallbackConfig(enable_jitter=False, enable_user_notifications=False)
        )

        for _ in range(50):
            await manager.activate_polling_fallback(
                "session-1", "customer", None, FallbackReason.NETWORK_ERROR
            )

        assert (
            len(manager.polling_clients)
            == POLLING_MAX_CLIENTS_PER_SESSION_CLIENT_TYPE
        )
        assert (
            len(manager.session_polling_clients["session-1"])
            == POLLING_MAX_CLIENTS_PER_SESSION_CLIENT_TYPE
        )

    async def test_the_newest_activation_survives(self):
        """The client repairing its connection keeps the queue it will poll."""
        manager = WebSocketFallbackManager(
            FallbackConfig(enable_jitter=False, enable_user_notifications=False)
        )

        ids = [
            await manager.activate_polling_fallback(
                "session-1", "customer", None, FallbackReason.NETWORK_ERROR
            )
            for _ in range(POLLING_MAX_CLIENTS_PER_SESSION_CLIENT_TYPE + 2)
        ]

        assert ids[-1] in manager.polling_clients
        assert ids[0] not in manager.polling_clients

    async def test_the_cap_is_per_client_type_not_per_process(self):
        """An admin activating must not evict the customer on the same session."""
        manager = WebSocketFallbackManager(
            FallbackConfig(enable_jitter=False, enable_user_notifications=False)
        )

        customer = await manager.activate_polling_fallback(
            "session-1", "customer", None, FallbackReason.NETWORK_ERROR
        )
        for _ in range(POLLING_MAX_CLIENTS_PER_SESSION_CLIENT_TYPE + 2):
            await manager.activate_polling_fallback(
                "session-1", "admin", None, FallbackReason.NETWORK_ERROR
            )

        assert customer in manager.polling_clients


class TestTheDropLogDoesNotFlood:
    """A wedged client -- queue full, not yet 30-minute-stale -- drops every
    subsequent message. One WARNING per drop meant a line per translation for
    up to half an hour, for exactly the client this code exists to report."""

    def test_a_saturated_queue_warns_once_not_per_message(
        self, polling_client, caplog
    ):
        manager, polling_id = polling_client

        with caplog.at_level(logging.WARNING):
            for index in range(POLLING_QUEUE_MAX_MESSAGES + 200):
                manager.send_message_to_polling_client(
                    polling_id, {"type": "translation", "seq": index}
                )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, (
            f"{len(warnings)} warnings for 200 drops -- the log floods for a "
            "single wedged client"
        )

    def test_the_counter_still_records_every_drop(self, polling_client):
        """Bounding the log must not bound the metric."""
        manager, polling_id = polling_client
        before = _dropped(manager)

        for index in range(POLLING_QUEUE_MAX_MESSAGES + 200):
            manager.send_message_to_polling_client(
                polling_id, {"type": "translation", "seq": index}
            )

        assert _dropped(manager) - before == 200

    def test_a_client_that_recovers_and_saturates_again_warns_again(
        self, polling_client, caplog
    ):
        manager, polling_id = polling_client

        with caplog.at_level(logging.WARNING):
            for index in range(POLLING_QUEUE_MAX_MESSAGES + 5):
                manager.send_message_to_polling_client(
                    polling_id, {"type": "translation", "seq": index}
                )
            manager.poll_messages(polling_id)
            for index in range(POLLING_QUEUE_MAX_MESSAGES + 5):
                manager.send_message_to_polling_client(
                    polling_id, {"type": "translation", "seq": index}
                )

        # One per episode, plus the drain summary between them.
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3

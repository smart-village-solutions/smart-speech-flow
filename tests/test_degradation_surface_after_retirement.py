"""What is left of the degradation layer once the dead paths are gone.

After #219 the only thing that reads or writes the degradation layer is the
service-mode tracking driven by live breaker transitions. The response cache,
the request queue and the fallback strategies were reachable only from
``handle_service_failure``, whose last caller went with the async service-call
client -- and everything it could have returned was either a cached reply
nothing ever cached or an invented one.

This test pins the surface that survives, so a later reader can tell what the
module is for without reconstructing which halves are live.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from services.api_gateway import graceful_degradation
from services.api_gateway.app import app
from services.api_gateway.graceful_degradation import ServiceMode, graceful_degradation_manager

RETIRED_NAMES = [
    # Fallback machinery: reachable only from handle_service_failure.
    "handle_service_failure",
    "_apply_fallback_strategy",
    "_try_cached_response",
    "_generate_error_response",
    # The response cache: written only by the deleted client's call paths.
    "cache_response",
    "_generate_cache_key",
    "_evict_oldest_cache_entries",
    "cleanup_expired_cache",
    "response_cache",
    "cache_stats",
    # The request queue: enable_queuing was never turned on.
    "_queue_request",
    "process_pending_requests",
    "pending_requests",
    # Superseded by apply_service_states, which can also recover.
    "_update_service_mode",
]

RETIRED_TYPES = ["CacheEntry", "FallbackConfig", "FallbackStrategy"]


class TestTheDeadPathsAreGone:
    def test_no_retired_member_remains(self):
        present = [name for name in RETIRED_NAMES if hasattr(graceful_degradation_manager, name)]
        assert present == [], f"still reachable: {present}"

    def test_no_retired_type_remains(self):
        present = [name for name in RETIRED_TYPES if hasattr(graceful_degradation, name)]
        assert present == [], f"still defined: {present}"


class TestWhatSurvives:
    def test_the_mode_still_tracks_and_recovers(self):
        graceful_degradation_manager.apply_service_states(
            {"asr": True, "translation": True, "tts": False}
        )
        assert graceful_degradation_manager.current_mode is ServiceMode.DEGRADED

        graceful_degradation_manager.apply_service_states(
            {"asr": True, "translation": True, "tts": True}
        )
        assert graceful_degradation_manager.current_mode is ServiceMode.FULL

    def test_the_status_payload_keeps_only_fields_it_can_fill(self):
        status = graceful_degradation_manager.get_degradation_status()

        assert set(status) == {
            "current_mode",
            "mode_history",
        }, "the payload still advertises something the module no longer tracks"


class TestTheRoutesStillAnswer:
    def test_the_degradation_endpoint_works(self):
        with TestClient(app) as client:
            response = client.get("/api/health/degradation")

        assert response.status_code == 200
        assert "current_mode" in response.json()["data"]

    def test_the_other_health_endpoints_work(self):
        with TestClient(app) as client:
            for path in (
                "/api/health/services",
                "/api/health/circuit-breakers",
                "/api/health/summary",
            ):
                assert client.get(path).status_code == 200, path

    def test_the_cache_endpoint_is_gone(self):
        """It reported on a cache nothing wrote to; zeroes forever is a lie."""
        with TestClient(app) as client:
            assert client.get("/api/health/cache").status_code == 404

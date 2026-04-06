"""
Integration Tests für Circuit Breaker Pattern - Echtes System Testing
====================================================================

Diese Tests verwenden echte HTTP-Services und testen die tatsächliche
Circuit Breaker Funktionalität ohne Mocks.

Autor: Smart Village Solutions
Datum: November 2025
Version: 1.0
"""

import pytest
import asyncio
import aiohttp
import time
import logging
import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler


from services.api_gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    CircuitBreakerOpenError
)
from services.api_gateway.service_health import ServiceHealthManager, ServiceEndpoint
from services.api_gateway.graceful_degradation import GracefulDegradationManager
from services.api_gateway.circuit_breaker_client import CircuitBreakerServiceClient

logger = logging.getLogger(__name__)


class TestHTTPHandler(BaseHTTPRequestHandler):
    """Simpler HTTP Handler für echte Integration Tests"""

    # Klassen-Variablen für Test-Kontrolle
    is_healthy = True
    response_delay = 0.0
    call_count = 0

    def log_message(self, format, *args):
        """Unterdrücke Server Logs"""
        pass

    def do_GET(self):
        """Handle GET Requests"""
        TestHTTPHandler.call_count += 1

        if self.path == '/health':
            self._handle_health()
        else:
            self.send_error(404)

    def do_POST(self):
        """Handle POST Requests"""
        TestHTTPHandler.call_count += 1

        if self.path == '/transcribe':
            self._handle_transcribe()
        elif self.path == '/translate':
            self._handle_translate()
        elif self.path == '/synthesize':
            self._handle_synthesize()
        else:
            self.send_error(404)

    def _handle_health(self):
        """Health Check Handler"""
        if self.response_delay > 0:
            time.sleep(self.response_delay)

        if not TestHTTPHandler.is_healthy:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'Service Unavailable')
            return

        response_data = {"status": "healthy", "service": "test", "call_count": TestHTTPHandler.call_count}
        self._send_json_response(response_data)

    def _handle_transcribe(self):
        """ASR Handler"""
        if TestHTTPHandler.response_delay > 0:
            time.sleep(TestHTTPHandler.response_delay)

        if not TestHTTPHandler.is_healthy:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'ASR Service Down')
            return

        response_data = {
            "success": True,
            "text": "Test transcription",
            "confidence": 0.95
        }
        self._send_json_response(response_data)

    def _handle_translate(self):
        """Translation Handler"""
        if TestHTTPHandler.response_delay > 0:
            time.sleep(TestHTTPHandler.response_delay)

        if not TestHTTPHandler.is_healthy:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'Translation Service Down')
            return

        response_data = {
            "success": True,
            "translated_text": "Test translation",
            "confidence": 0.9
        }
        self._send_json_response(response_data)

    def _handle_synthesize(self):
        """TTS Handler"""
        if TestHTTPHandler.response_delay > 0:
            time.sleep(TestHTTPHandler.response_delay)

        if not TestHTTPHandler.is_healthy:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'TTS Service Down')
            return

        response_data = {
            "success": True,
            "audio_url": "http://localhost:9999/audio/test.wav"
        }
        self._send_json_response(response_data)

    def _send_json_response(self, data):
        """Sendet JSON Response"""
        response = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)


class TestServerManager:
    """Manager für Test HTTP Server"""

    def __init__(self, port=9999):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Startet Test Server in eigenem Thread"""
        self.server = HTTPServer(('localhost', self.port), TestHTTPHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        # Kurz warten bis Server bereit ist
        time.sleep(0.1)
        logger.info(f"🚀 Test HTTP Server gestartet auf Port {self.port}")

    def stop(self):
        """Stoppt Test Server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1.0)
        logger.info("🛑 Test HTTP Server gestoppt")

    def set_healthy(self, healthy=True):
        """Setzt Service Health Status"""
        TestHTTPHandler.is_healthy = healthy
        logger.info(f"📊 Test Server Health: {'Healthy' if healthy else 'Unhealthy'}")

    def set_response_delay(self, delay=0.0):
        """Setzt Response Delay"""
        TestHTTPHandler.response_delay = delay
        logger.info(f"⏱️ Test Server Response Delay: {delay}s")

    def reset_call_count(self):
        """Reset Call Counter"""
        TestHTTPHandler.call_count = 0


# Globaler Test Server für alle Tests
test_server = TestServerManager()


def setup_module():
    """Setup für gesamtes Test Modul"""
    test_server.start()


def teardown_module():
    """Teardown für gesamtes Test Modul"""
    test_server.stop()


@pytest.fixture
def circuit_breaker():
    """Test Circuit Breaker mit echtem HTTP Service"""
    config = CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=2,
        success_threshold=2,
        timeout=1.0
    )

    circuit = CircuitBreaker("integration-test", config)
    yield circuit

    # Cleanup nach Test
    circuit.reset()


@pytest.fixture
def reset_server():
    """Reset Test Server für jeden Test"""
    test_server.set_healthy(True)
    test_server.set_response_delay(0.0)
    test_server.reset_call_count()
    yield
    # Cleanup nach Test
    test_server.set_healthy(True)
    test_server.set_response_delay(0.0)


class TestCircuitBreakerRealSystem:
    """Integration Tests mit echtem HTTP System"""

    @pytest.mark.asyncio
    async def test_real_circuit_breaker_success_flow(self, circuit_breaker, reset_server):
        """Test: Echter Circuit Breaker Success Flow"""
        test_server.set_healthy(True)

        async def real_http_call():
            """Echte HTTP-Anfrage an Test Server"""
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{test_server.port}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data
                    else:
                        raise Exception(f"HTTP {resp.status}")

        # Erfolgreiche Calls
        result1 = await circuit_breaker.call(real_http_call)
        assert result1["status"] == "healthy"
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.health.successful_requests == 1

        await circuit_breaker.call(real_http_call)
        assert circuit_breaker.health.successful_requests == 2

        # Health Metrics prüfen
        health_status = circuit_breaker.get_health_status()
        assert health_status["health_metrics"]["success_rate"] == 100.0
        assert health_status["health_metrics"]["total_requests"] == 2

    @pytest.mark.asyncio
    async def test_real_circuit_breaker_failure_flow(self, circuit_breaker, reset_server):
        """Test: Echter Circuit Breaker Failure Flow"""
        test_server.set_healthy(False)

        async def real_http_call():
            """Echte HTTP-Anfrage die fehlschlägt"""
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{test_server.port}/health") as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        raise Exception(f"HTTP {resp.status}: Service Down")

        # Failures sammeln bis Circuit OPEN geht
        failure_count = 0
        for i in range(circuit_breaker.config.failure_threshold):
            with pytest.raises(Exception) as exc_info:
                await circuit_breaker.call(real_http_call)
            assert "Service Down" in str(exc_info.value)
            failure_count += 1

        # Circuit sollte jetzt OPEN sein
        assert circuit_breaker.state == CircuitState.OPEN
        assert circuit_breaker.failure_count == failure_count

        # Weitere Calls sollten sofort blockiert werden
        with pytest.raises(CircuitBreakerOpenError):
            await circuit_breaker.call(real_http_call)

    @pytest.mark.asyncio
    async def test_real_timeout_handling(self, circuit_breaker, reset_server):
        """Test: Echte Timeout-Behandlung"""
        # Test Server mit langer Response-Zeit konfigurieren
        test_server.set_response_delay(2.0)  # Länger als Circuit Timeout (1.0s)
        test_server.set_healthy(True)

        async def slow_http_call():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.0)) as session:
                async with session.get(f"http://localhost:{test_server.port}/health") as resp:
                    return await resp.json()

        # Call sollte mit Timeout fehlschlagen
        start_time = time.time()
        with pytest.raises(
            (TimeoutError, asyncio.TimeoutError, aiohttp.ServerTimeoutError)
        ):
            await circuit_breaker.call(slow_http_call)

        # Prüfe dass Timeout eingetreten ist
        elapsed_time = time.time() - start_time
        assert elapsed_time >= 1.0  # Mindestens Timeout-Zeit
        assert elapsed_time < 1.5   # Aber nicht viel länger

        # Failure sollte gezählt werden
        assert circuit_breaker.failure_count == 1


class TestServiceHealthManagerRealSystem:
    """Service Health Manager Tests mit echtem System"""

    @pytest.mark.asyncio
    async def test_real_service_registration_and_health_check(self, reset_server):
        """Test: Echte Service Registration und Health Check"""
        manager = ServiceHealthManager()

        # Echten Test Service registrieren
        endpoint = ServiceEndpoint(
            name="real-test-service",
            base_url=f"http://localhost:{test_server.port}",
            timeout=1.0
        )
        manager.register_service(endpoint)

        # Service sollte registriert sein
        assert "real-test-service" in manager.services
        assert "real-test-service" in manager.service_status
        assert "real-test-service" in manager.circuit_breakers

        # Health Check mit echtem HTTP Service
        test_server.set_healthy(True)
        await manager._check_service_health("real-test-service", endpoint)

        # Status prüfen
        status = manager.service_status["real-test-service"]
        assert status.is_healthy is True
        assert status.last_check is not None
        assert status.error_message is None

        await manager.stop_monitoring()

    @pytest.mark.asyncio
    async def test_real_service_failure_detection(self, reset_server):
        """Test: Echte Service Failure Detection"""
        manager = ServiceHealthManager()

        endpoint = ServiceEndpoint(
            name="failing-service",
            base_url=f"http://localhost:{test_server.port}",
            timeout=1.0
        )
        manager.register_service(endpoint)

        # Service auf unhealthy setzen
        test_server.set_healthy(False)

        # Health Check mit fehlschlagendem Service
        await manager._check_service_health("failing-service", endpoint)

        # Failure sollte erkannt werden
        status = manager.service_status["failing-service"]
        assert status.is_healthy is False
        assert status.error_message is not None
        assert "500" in status.error_message or "failed" in status.error_message.lower()

        await manager.stop_monitoring()

    @pytest.mark.asyncio
    async def test_real_overall_health_status(self, reset_server):
        """Test: Echter Overall Health Status"""
        manager = ServiceHealthManager()

        # Service registrieren
        endpoint = ServiceEndpoint(
            name="test-service",
            base_url=f"http://localhost:{test_server.port}",
            timeout=1.0
        )
        manager.register_service(endpoint)

        # Service healthy
        test_server.set_healthy(True)
        await manager._check_service_health("test-service", manager.services["test-service"])

        # Overall Health prüfen
        overall_health = manager.get_overall_health()
        assert overall_health["overall_healthy"] is True
        assert overall_health["summary"]["total_services"] >= 1
        assert overall_health["summary"]["healthy_services"] >= 1

        await manager.stop_monitoring()

    @pytest.mark.asyncio
    async def test_gpu_summary_alerts_and_aggregation(self):
        """Test: GPU Summary erzeugt Alerts bei hoher Auslastung"""
        manager = ServiceHealthManager()

        try:
            status = manager.service_status.get("asr")
            assert status is not None

            status.is_healthy = True
            status.last_check = datetime.now()
            status.resources = {
                "gpu": {
                    "available": True,
                    "device_count": 1,
                    "devices": [
                        {
                            "index": 0,
                            "name": "Mock GPU",
                            "utilization_percent": 92.5,
                            "memory_utilization": 88.1,
                            "temperature_c": 70
                        }
                    ]
                }
            }
            status.autoscaling = {
                "recommended_action": "scale_up",
                "reasons": ["gpu_pressure"]
            }

            gpu_summary = manager.get_gpu_summary()
            assert gpu_summary["devices_reporting"] == 1
            assert gpu_summary["critical_devices"] == 1
            assert gpu_summary["scale_up_recommendations"] == 1
            assert any(alert["severity"] == "critical" for alert in gpu_summary["alerts"])
            assert gpu_summary["recommended_action"] == "scale_up"

            overall_health = manager.get_overall_health()
            assert overall_health["gpu_summary"]["critical_devices"] == 1
            assert overall_health["gpu_summary"]["devices_reporting"] == 1
            assert overall_health["gpu_summary"]["recommended_action"] == "scale_up"
        finally:
            await manager.stop_monitoring()


class TestGracefulDegradationRealSystem:
    """Graceful Degradation Tests mit echtem System"""

    @pytest.mark.asyncio
    async def test_real_cache_fallback_mechanism(self, reset_server):
        """Test: Echte Cache Fallback Funktionalität"""
        degradation_manager = GracefulDegradationManager()

        # 1. Erfolgreiche Response cachen
        service_name = "test-service"
        request_data = {"text": "test message", "language": "de"}
        success_response = {
            "success": True,
            "result": "Cached test result",
            "timestamp": time.time()
        }

        await degradation_manager.cache_response(
            service_name, request_data, success_response, ttl=60
        )

        # 2. Service Failure simulieren
        test_server.set_healthy(False)
        original_error = Exception("Real service failure")

        # 3. Fallback sollte gecachte Response zurückgeben
        fallback_result = await degradation_manager.handle_service_failure(
            service_name, request_data, original_error
        )

        # Prüfe dass Cache verwendet wurde
        assert fallback_result.get("cached") is True
        assert fallback_result["result"] == "Cached test result"
        assert fallback_result.get("fallback_reason") == "service_unavailable"

    @pytest.mark.asyncio
    async def test_real_service_mode_transitions(self, reset_server):
        """Test: Echte Service Mode Transitions"""
        degradation_manager = GracefulDegradationManager()

        # Initial sollte FULL Mode sein
        status = degradation_manager.get_degradation_status()
        assert status["current_mode"] == "full"

        # Service Failures simulieren
        await degradation_manager._update_service_mode("asr", is_failure=True)
        status = degradation_manager.get_degradation_status()
        assert status["current_mode"] == "degraded"

        # Weitere Failure
        await degradation_manager._update_service_mode("translation", is_failure=True)
        status = degradation_manager.get_degradation_status()
        assert status["current_mode"] == "minimal"

        # Mode History sollte getracked werden
        assert len(status["mode_history"]) >= 2


class TestCircuitBreakerServiceClientRealSystem:
    """Circuit Breaker Service Client Tests mit echtem System"""

    @pytest.mark.asyncio
    async def test_real_service_client_initialization(self, reset_server):
        """Test: Echte Service Client Initialisierung"""
        client = CircuitBreakerServiceClient()

        # Session sollte bei Bedarf erstellt werden
        await client._ensure_session()
        assert client.session is not None
        assert not client.session.closed

        # Health Status sollte abrufbar sein (wenn Services laufen)
        try:
            health_status = await client.get_health_status()
            assert isinstance(health_status, dict)
            assert "overall_healthy" in health_status
        except Exception as e:
            # Erwartbar wenn keine echten Services laufen
            logger.info(f"Health status nicht verfügbar (erwartbar): {e}")

        # Cleanup
        await client.close()

    @pytest.mark.asyncio
    async def test_real_http_call_with_circuit_breaker(self, reset_server):
        """Test: Echter HTTP Call mit Circuit Breaker"""
        test_server.set_healthy(True)

        # Circuit Breaker für Test Service
        circuit = CircuitBreaker("http-test")

        async def http_call():
            """Echter HTTP Call an Test Server"""
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{test_server.port}/health") as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        raise Exception(f"HTTP {resp.status}")

        # Erfolgreicher Call
        result = await circuit.call(http_call)
        assert result["status"] == "healthy"
        assert circuit.state == CircuitState.CLOSED
        assert circuit.health.successful_requests == 1


class TestEndToEndRealSystem:
    """End-to-End Tests mit komplettem echten System"""

    @pytest.mark.asyncio
    async def test_concurrent_real_service_calls(self, reset_server):
        """Test: Concurrent Service Calls mit echtem System"""
        circuit = CircuitBreaker("concurrent-test")
        test_server.set_healthy(True)

        async def concurrent_service_call(call_id: int):
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://localhost:{test_server.port}/health") as resp:
                    data = await resp.json()
                    data["call_id"] = call_id
                    return data

        # 5 gleichzeitige Calls (stabil für Integrationstests)
        tasks = [
            circuit.call(concurrent_service_call, i)
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # Alle Calls sollten erfolgreich sein
        assert len(results) == 5
        assert all(result["status"] == "healthy" for result in results)
        assert circuit.health.successful_requests == 5

        # Call IDs sollten korrekt sein
        call_ids = [result["call_id"] for result in results]
        assert sorted(call_ids) == list(range(5))

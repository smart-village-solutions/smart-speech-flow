"""Fixtures for the gateway contract suite (#228).

The tests beside this file drive only the public surface: HTTP through
TestClient, the WebSocket endpoints and app.openapi(). The app's dependency
container and the globals that remain are reached here and nowhere else, so
the composition root work repoints this one file instead of every test.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import anyio.from_thread
import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import (
    VERIFIED_TENANT_ID_CLAIM,
    optional_ssf_user,
    require_ssf_user,
)
from services.api_gateway.dependencies import GatewayDependencies
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.studio_v2 import RuntimeRead
from services.api_gateway.tenant_context import StudioTenantContext, require_studio_tenant_context
from tests.gateway_contract.contract_support import (
    REVISION,
    TENANT_A,
    runtime_read,
    wav_bytes,
)

STUDIO_ENVIRONMENT = (
    "STUDIO_RUNTIME_CONFIGURATION_BASE_URL",
    "STUDIO_RUNTIME_FIXED_TOKEN",
    "STUDIO_RUNTIME_TOKEN_URL",
    "STUDIO_RUNTIME_CLIENT_ID",
    "STUDIO_RUNTIME_CLIENT_SECRET",
    "STUDIO_RUNTIME_AUDIENCE",
)

_CLIENT_ADDRESSES = itertools.count(1)


class SignedIdentity:
    """Switches the signed operator identity the gateway sees.

    Signature verification has its own suite (tests/test_auth.py); here the
    verified claims are supplied directly, as every route suite does.
    """

    def __init__(self) -> None:
        self.tenant_id = TENANT_A
        self.customer_claims: dict[str, Any] | None = None
        self._install()

    def act_as(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def customer_bearer(self, tenant_id: str | None) -> None:
        """A customer request that carries an operator bearer, or none at all."""
        self.customer_claims = (
            None
            if tenant_id is None
            else {"sub": f"operator-{tenant_id}", VERIFIED_TENANT_ID_CLAIM: tenant_id}
        )

    def unauthenticated(self) -> None:
        """Requests carry no verified operator identity at all."""
        for dependency in (
            require_ssf_user,
            require_studio_tenant_context,
            require_validated_runtime_configuration,
            optional_ssf_user,
        ):
            app.dependency_overrides.pop(dependency, None)

    def with_real_customer_authentication(self) -> None:
        """A supplied customer bearer goes through real token validation."""
        app.dependency_overrides.pop(optional_ssf_user, None)

    def with_real_tenant_context(self) -> None:
        """Verified claims, but the real request-side tenant selector checks."""
        app.dependency_overrides.pop(require_studio_tenant_context, None)

    def claims(self) -> dict[str, str]:
        return {
            "sub": f"operator-{self.tenant_id}",
            VERIFIED_TENANT_ID_CLAIM: self.tenant_id,
        }

    def context(self) -> StudioTenantContext:
        return StudioTenantContext(self.tenant_id, REVISION)

    def runtime(self) -> ValidatedRuntimeConfiguration:
        return ValidatedRuntimeConfiguration(
            self.context(), runtime_read(self.tenant_id), f"contract-{self.tenant_id}"
        )

    def _install(self) -> None:
        app.dependency_overrides[require_ssf_user] = self.claims
        app.dependency_overrides[require_studio_tenant_context] = self.context
        app.dependency_overrides[require_validated_runtime_configuration] = self.runtime
        app.dependency_overrides[optional_ssf_user] = lambda: self.customer_claims


class TicketClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _UnavailableTicketBackend:
    def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        raise ConnectionError("ticket backend down")

    def put(self, key: str, value: str, ttl_seconds: int) -> None:
        raise ConnectionError("ticket backend down")

    def consume(self, key: str) -> str | None:
        raise ConnectionError("ticket backend down")

    def get(self, key: str) -> str | None:
        raise ConnectionError("ticket backend down")


@dataclass
class RealtimeTickets:
    clock: TicketClock
    make_unavailable: Callable[[], None]


@pytest.fixture(autouse=True)
def gateway_state(
    monkeypatch, gateway_dependencies: GatewayDependencies
) -> Iterator[SignedIdentity]:
    """Fresh conversation state and a signed identity per test, restored afterwards.

    Every test gets its own dependency container from tests/conftest.py, so
    sessions, realtime tickets, pollers and sockets start empty. Studio is unconfigured
    unless a test asks for the `studio` fixture, so no Studio request can
    leave the process.
    """
    for variable in STUDIO_ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    overrides = app.dependency_overrides.copy()
    try:
        yield SignedIdentity()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)


@pytest.fixture
def gateway():
    return app


@pytest.fixture
def identity(gateway_state: SignedIdentity) -> SignedIdentity:
    return gateway_state


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client without the lifespan, on its own rate-limit bucket.

    Every request and socket shares one event loop, as they do in production.
    TestClient otherwise gives each WebSocket its own loop, and a frame one
    socket's handler sends to another then waits for an unrelated timer to
    wake the receiving loop.
    """
    number = next(_CLIENT_ADDRESSES)
    test_client = TestClient(
        app, headers={"x-forwarded-for": f"10.228.{number // 250}.{number % 250}"}
    )
    with anyio.from_thread.start_blocking_portal("asyncio") as portal:
        test_client.portal = portal
        try:
            yield test_client
        finally:
            test_client.close()


@pytest.fixture
def realtime_tickets(gateway_dependencies: GatewayDependencies) -> RealtimeTickets:
    """Control over the realtime ticket backend's clock and availability."""
    from services.api_gateway.realtime_ticket import MemoryRealtimeTicketBackend

    realtime_ticket_store = gateway_dependencies.realtime_tickets
    clock = TicketClock()
    realtime_ticket_store.clock = clock
    realtime_ticket_store.backend = MemoryRealtimeTicketBackend(clock=clock)

    def make_unavailable() -> None:
        realtime_ticket_store.backend = _UnavailableTicketBackend()

    return RealtimeTickets(clock=clock, make_unavailable=make_unavailable)


class SessionClock:
    """The session manager's clock, moved forward instead of waited out."""

    def __init__(self, dependencies: GatewayDependencies) -> None:
        self.offset = timedelta()
        self.sessions = dependencies.session_manager
        self.sessions.clock = self

    def __call__(self) -> datetime:
        return datetime.now(timezone.utc) + self.offset

    def advance(self, **delta: float) -> None:
        self.offset += timedelta(**delta)

    def check_timeouts(self, client: TestClient) -> None:
        """One pass of the lifespan's session-timeout task, on the client's loop."""
        client.portal.call(self.sessions.check_session_timeouts)


@pytest.fixture
def session_clock(gateway_dependencies: GatewayDependencies) -> SessionClock:
    return SessionClock(gateway_dependencies)


@pytest.fixture
def lapse_sessions(gateway_dependencies: GatewayDependencies) -> Callable[[], None]:
    """Drops every session from the manager and its store without terminating any.

    This is how a lapsed Redis record looks to the gateway: nothing was
    terminated, so no realtime ticket was revoked. No HTTP request leaves a
    session in that state.
    """
    sessions = gateway_dependencies.session_manager

    def lapse() -> None:
        sessions.sessions.clear()
        sessions.store.clear()

    return lapse


@pytest.fixture
def openapi_document(gateway) -> dict[str, Any]:
    return gateway.openapi()


class StudioStub:
    """Studio runtime configuration v2 as seen by the gateway.

    One object answers all three reads: the admin create resolution, the
    customer activation read and the persistence gate.
    """

    def __init__(self) -> None:
        self.storage_mode = "ask"
        self.error: Exception | None = None
        self.configuration_override: RuntimeRead | None = None
        self.fetches: list[tuple[str, str]] = []

    def fail(self, code: str, *, retryable: bool) -> None:
        from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2ClientError

        self.error = StudioRuntimeV2ClientError(code, retryable=retryable)

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeRead:
        self.fetches.append((tenant_id, correlation_id))
        if self.error is not None:
            raise self.error
        if self.configuration_override is not None:
            return self.configuration_override
        return runtime_read(tenant_id, storage_mode=self.storage_mode)


@pytest.fixture
def studio(gateway_dependencies: GatewayDependencies) -> Iterator[StudioStub]:
    """Route every Studio read to a stub, with the real resolution dependency."""
    from services.api_gateway import studio_runtime_flow
    from services.api_gateway.runtime_policy import RuntimePolicyGate

    stub = StudioStub()
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)
    gateway_dependencies.studio_runtime_flow = studio_runtime_flow.StudioRuntimeFlow(stub)
    gateway_dependencies.session_manager.runtime_policy = RuntimePolicyGate(stub)
    yield stub


class StudioMock:
    """The Studio mock at its HTTP boundary, read by the real v2 and installation clients.

    Wired by `wire_studio`, as the lifespan wires Studio.
    """

    TOKEN = "studio-mock-authorized-token"

    def __init__(self) -> None:
        from services.studio_mock import app as mock

        self._mock = TestClient(mock.app)
        self.scenario: str | None = None
        self.stopped = False
        self.now = 1000.0
        # Set by the fixture: fresh content state, as after a gateway restart,
        # which keeps its sessions and loses its cache.
        self.restart_content: Callable[[], None] = lambda: None

    def clock(self) -> float:
        return self.now

    def age_content(self, seconds: float) -> None:
        """Move the content cache's clock on, so its content counts as old."""
        self.now += seconds

    async def token(self) -> str:
        return self.TOKEN

    async def get(self, url: str, headers: Any, timeout_seconds: float) -> Any:
        import aiohttp

        from services.api_gateway.studio_v1 import StudioV1HttpResponse

        if self.stopped:
            raise aiohttp.ClientConnectionError("studio-mock is stopped")
        sent = dict(headers)
        if self.scenario:
            sent["X-Mock-Scenario"] = self.scenario
        response = self._mock.get(urlsplit(url).path, headers=sent)
        return StudioV1HttpResponse(response.status_code, response.json())


@pytest.fixture
def studio_mock(gateway_dependencies: GatewayDependencies) -> StudioMock:
    from prometheus_client import CollectorRegistry

    from services.api_gateway.studio_content import StudioContentCache
    from services.api_gateway.studio_content_metrics import StudioContentMetrics
    from services.api_gateway.studio_installation_client import StudioInstallationClient
    from services.api_gateway.studio_policy_reads import StudioPolicyReadMetrics
    from services.api_gateway.studio_runtime_v2_client import StudioRuntimeV2Client
    from services.api_gateway.studio_wiring import wire_studio

    studio = StudioMock()
    base_url = "http://studio-mock.test"

    def wire() -> None:
        wiring = wire_studio(
            StudioRuntimeV2Client(base_url, studio.token, transport=studio),
            StudioInstallationClient(base_url, studio.token, transport=studio),
            StudioContentCache(clock=studio.clock),
            policy_registry=CollectorRegistry(),
            content_metrics=StudioContentMetrics(CollectorRegistry()),
            policy_reads=StudioPolicyReadMetrics(CollectorRegistry()),
        )
        gateway_dependencies.studio_runtime_flow = wiring.runtime_flow
        gateway_dependencies.session_manager.runtime_policy = wiring.runtime_policy
        gateway_dependencies.studio_content = wiring.content

    app.dependency_overrides.pop(require_validated_runtime_configuration, None)
    wire()
    studio.restart_content = wire
    return studio


@pytest.fixture
def guest_grace_window(gateway_dependencies: GatewayDependencies) -> Callable[[timedelta], None]:
    """Sets how long after a conversation ends its guest may still read content."""

    def set_window(window: timedelta) -> None:
        gateway_dependencies.guest_grace_window = window

    return set_window


@pytest.fixture
def studio_unconfigured() -> None:
    """The real resolution dependency with no Studio settings at all."""
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)


@pytest.fixture
def unbound_persistence_gate(gateway_dependencies: GatewayDependencies) -> None:
    """The production default when Studio is unconfigured: every write refused."""
    gateway_dependencies.session_manager.runtime_policy = None


class _SpeechResponse:
    def __init__(
        self,
        status_code: int,
        *,
        payload: dict[str, Any] | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content
        self.headers = headers or {"content-type": "application/json"}
        self.text = str(self._payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} from upstream", response=self)


_SERVICE_BY_PATH = {
    "/transcribe": "asr",
    "/translate": "translation",
    "/synthesize": "tts",
    "/generate": "refinement",
}


class SpeechServices:
    """The ASR, translation, TTS and refinement services, answered at their HTTP boundary."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.failures: dict[str, _SpeechResponse | Exception] = {}
        self.asr_text = "Guten Tag"
        self.refined_text = "Good day, refined"
        self.tts_text: str | None = None

    def fail(self, service: str, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.failures[service] = _SpeechResponse(
            status_code, payload={"detail": f"{service} failed"}, headers=headers
        )

    def raise_on(self, service: str, error: Exception) -> None:
        """The transport itself fails, as a refused connection or a timeout does."""
        self.failures[service] = error

    def answer_tts_without_audio(self) -> None:
        """TTS answers 200 with a JSON error body, as it does when synthesis fails."""
        self.failures["tts"] = _SpeechResponse(200, payload={"error": "synthesis failed"})

    def recover(self, service: str) -> None:
        self.failures.pop(service, None)

    def sent_to(self, service: str) -> list[dict[str, Any]]:
        return [options for name, options in self.requests if name == service]

    def post(self, url: str, **options: Any) -> _SpeechResponse:
        service = _SERVICE_BY_PATH["/" + url.rsplit("/", 1)[-1]]
        self.calls.append(service)
        self.requests.append((service, options))
        failure = self.failures.get(service)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if service == "asr":
            return _SpeechResponse(200, payload={"text": self.asr_text, "debug": {"model": "asr"}})
        if service == "translation":
            payload = {"translations": "Good day"}
            if self.tts_text is not None:
                payload["tts_text"] = self.tts_text
            return _SpeechResponse(200, payload=payload)
        if service == "refinement":
            return _SpeechResponse(200, payload={"response": self.refined_text})
        return _SpeechResponse(200, content=wav_bytes(0.2), headers={"content-type": "audio/wav"})


@pytest.fixture
def speech_services(monkeypatch) -> SpeechServices:
    """The speech services at their HTTP boundary.

    Each test's container has its own circuit breakers, so they start closed.
    """
    import requests

    services = SpeechServices()
    monkeypatch.setattr(requests, "post", services.post)
    return services


REFINER_ENDPOINT = "http://refiner.contract:11434"
REFINER_MODEL = "contract-refiner"
REFINER_SKIPPED_TARGET = "fa"


@pytest.fixture
def refinement(
    speech_services: SpeechServices, gateway_dependencies: GatewayDependencies
) -> SpeechServices:
    """An active Ollama refiner, answered at its HTTP boundary by `speech_services`."""
    from services.api_gateway.translation_refiner import OllamaTranslationRefiner

    refiner = OllamaTranslationRefiner(
        REFINER_ENDPOINT,
        REFINER_MODEL,
        timeout_seconds=4.0,
        temperature=0.0,
        max_retries=1,
        skip_target_languages=[REFINER_SKIPPED_TARGET],
    )
    # The conversation service and the pipeline routes hold this one object.
    gateway_dependencies.speech_pipeline.refiner = refiner
    return speech_services


class Conversations:
    """Creates and joins conversations through the public routes only."""

    def __init__(self, client: TestClient, identity: SignedIdentity) -> None:
        self.client = client
        self.identity = identity

    def create(self, tenant_id: str = TENANT_A) -> str:
        self.identity.act_as(tenant_id)
        created = self.client.post("/api/admin/session/create")
        assert created.status_code == 201, created.text
        return created.json()["session_id"]

    def activate(
        self, session_id: str, language: str = "en", consent: bool | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"session_id": session_id, "customer_language": language}
        if consent is not None:
            body["data_retention_consent"] = consent
        activated = self.client.post("/api/customer/session/activate", json=body)
        assert activated.status_code == 200, activated.text
        return activated.json()

    def ticket(self, session_id: str, transport: str = "websocket") -> str:
        issued = self.client.post(
            f"/api/admin/session/{session_id}/realtime-ticket", json={"transport": transport}
        )
        assert issued.status_code == 200, issued.text
        return issued.json()["ticket"]

    def send_text(
        self, session_id: str, role: str = "admin", source: str = "de", target: str = "en"
    ):
        return self.client.post(
            f"/api/{role}/session/{session_id}/message",
            json={"text": "Guten Tag", "source_lang": source, "target_lang": target},
        )

    def terminate(self, session_id: str) -> None:
        terminated = self.client.delete(f"/api/admin/session/{session_id}/terminate")
        assert terminated.status_code == 200, terminated.text


@pytest.fixture
def conversations(client: TestClient, identity: SignedIdentity) -> Conversations:
    return Conversations(client, identity)

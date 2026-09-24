"""Fixtures for the gateway contract suite (#228).

The tests beside this file drive only the public surface: HTTP through
TestClient, the WebSocket endpoints and app.openapi(). State that still lives
in module-level globals is reached here and nowhere else, so the composition
root work repoints this one file instead of every test.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import anyio.from_thread
import pytest
from fastapi.testclient import TestClient

from services.api_gateway.app import app
from services.api_gateway.auth import optional_ssf_user, require_ssf_user
from services.api_gateway.studio_runtime_client import RuntimeConfiguration
from services.api_gateway.studio_runtime_flow import (
    ValidatedRuntimeConfiguration,
    require_validated_runtime_configuration,
)
from services.api_gateway.tenant_context import StudioTenantContext, require_studio_tenant_context
from tests.gateway_contract.contract_support import (
    REVISION,
    TENANT_A,
    runtime_configuration,
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
            else {"studio_tenant_id": tenant_id, "ssf_authorization_revision": REVISION}
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
            "studio_tenant_id": self.tenant_id,
            "ssf_authorization_revision": REVISION,
        }

    def context(self) -> StudioTenantContext:
        return StudioTenantContext(self.tenant_id, REVISION)

    def runtime(self) -> ValidatedRuntimeConfiguration:
        return ValidatedRuntimeConfiguration(
            self.context(), runtime_configuration(self.tenant_id), f"contract-{self.tenant_id}"
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
    def set(self, *args: object, **kwargs: object) -> bool:
        raise ConnectionError("ticket backend down")

    def eval(self, *args: object, **kwargs: object) -> str | None:
        raise ConnectionError("ticket backend down")

    def get(self, *args: object, **kwargs: object) -> str | None:
        raise ConnectionError("ticket backend down")


@dataclass
class RealtimeTickets:
    clock: TicketClock
    make_unavailable: Callable[[], None]


def _reset_conversation_state() -> None:
    from services.api_gateway import websocket as websocket_module
    from services.api_gateway.session_manager import session_manager
    from services.api_gateway.websocket_polling_routes import polling_store

    session_manager.reset(clear_persistence=True)
    websocket_module.websocket_manager = None
    polling_store.clients.clear()


@pytest.fixture(autouse=True)
def gateway_state(monkeypatch) -> Iterator[SignedIdentity]:
    """Fresh conversation state and a signed identity per test, restored afterwards.

    Studio is unconfigured unless a test asks for the `studio` fixture, so no
    Studio request can leave the process.
    """
    from services.api_gateway import websocket as websocket_module
    from services.api_gateway.realtime_ticket import (
        MemoryRealtimeTicketBackend,
        realtime_ticket_store,
    )
    from services.api_gateway.session_manager import session_manager
    from services.api_gateway.studio_runtime_flow import runtime_flow_from_environment

    for variable in STUDIO_ENVIRONMENT:
        monkeypatch.delenv(variable, raising=False)
    runtime_flow_from_environment.cache_clear()
    overrides = app.dependency_overrides.copy()
    websocket_manager = websocket_module.websocket_manager
    ticket_backend = realtime_ticket_store.redis
    ticket_clock = realtime_ticket_store.clock
    realtime_ticket_store.redis = MemoryRealtimeTicketBackend()
    _reset_conversation_state()
    try:
        yield SignedIdentity()
    finally:
        _reset_conversation_state()
        realtime_ticket_store.redis = ticket_backend
        realtime_ticket_store.clock = ticket_clock
        websocket_module.websocket_manager = websocket_manager
        if websocket_manager is not None:
            session_manager.register_websocket_manager(websocket_manager)
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
        runtime_flow_from_environment.cache_clear()


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
def realtime_tickets() -> RealtimeTickets:
    """Control over the realtime ticket backend's clock and availability."""
    from services.api_gateway.realtime_ticket import (
        MemoryRealtimeTicketBackend,
        realtime_ticket_store,
    )

    clock = TicketClock()
    realtime_ticket_store.clock = clock
    realtime_ticket_store.redis = MemoryRealtimeTicketBackend(clock=clock)

    def make_unavailable() -> None:
        realtime_ticket_store.redis = _UnavailableTicketBackend()

    return RealtimeTickets(clock=clock, make_unavailable=make_unavailable)


@pytest.fixture
def openapi_document(gateway) -> dict[str, Any]:
    return gateway.openapi()


class StudioStub:
    """Studio Runtime Configuration V1 as seen by the gateway.

    One object answers all three reads: the admin create resolution, the
    customer activation read and the persistence gate.
    """

    def __init__(self) -> None:
        self.storage_mode = "ask"
        self.error: Exception | None = None
        self.configuration_override: RuntimeConfiguration | None = None
        self.fetches: list[tuple[str, str]] = []

    def fail(self, code: str, *, retryable: bool) -> None:
        from services.api_gateway.studio_runtime_client import StudioRuntimeClientError

        self.error = StudioRuntimeClientError(code, retryable=retryable)

    async def fetch(self, tenant_id: str, correlation_id: str) -> RuntimeConfiguration:
        self.fetches.append((tenant_id, correlation_id))
        if self.error is not None:
            raise self.error
        if self.configuration_override is not None:
            return self.configuration_override
        return runtime_configuration(tenant_id, storage_mode=self.storage_mode)


@pytest.fixture
def studio(monkeypatch) -> Iterator[StudioStub]:
    """Route every Studio read to a stub, with the real resolution dependency."""
    from services.api_gateway import studio_runtime_flow
    from services.api_gateway.routes import customer as customer_routes
    from services.api_gateway.runtime_policy import (
        RuntimePolicyGate,
        bind_runtime_policy,
        current_runtime_policy,
    )

    stub = StudioStub()
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)
    flow = studio_runtime_flow.StudioRuntimeFlow(stub)
    monkeypatch.setattr(studio_runtime_flow, "runtime_flow_from_environment", lambda: flow)
    monkeypatch.setattr(customer_routes, "runtime_flow_from_environment", lambda: flow)
    previous_gate = current_runtime_policy()
    bind_runtime_policy(RuntimePolicyGate(stub))
    try:
        yield stub
    finally:
        bind_runtime_policy(previous_gate)


@pytest.fixture
def studio_unconfigured() -> None:
    """The real resolution dependency with no Studio settings at all."""
    app.dependency_overrides.pop(require_validated_runtime_configuration, None)


@pytest.fixture
def unbound_persistence_gate() -> Iterator[None]:
    """The production default when Studio is unconfigured: every write refused."""
    from services.api_gateway.runtime_policy import bind_runtime_policy, current_runtime_policy

    previous_gate = current_runtime_policy()
    bind_runtime_policy(None)
    try:
        yield
    finally:
        bind_runtime_policy(previous_gate)


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


class SpeechServices:
    """The ASR, translation and TTS services, answered at their HTTP boundary."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[str, _SpeechResponse] = {}

    def fail(self, service: str, status_code: int, headers: dict[str, str] | None = None) -> None:
        self.failures[service] = _SpeechResponse(
            status_code, payload={"detail": f"{service} failed"}, headers=headers
        )

    def post(self, url: str, **_kwargs: Any) -> _SpeechResponse:
        service = {"/transcribe": "asr", "/translate": "translation", "/synthesize": "tts"}[
            "/" + url.rsplit("/", 1)[-1]
        ]
        self.calls.append(service)
        if service in self.failures:
            return self.failures[service]
        if service == "asr":
            return _SpeechResponse(200, payload={"text": "Guten Tag", "debug": {"model": "asr"}})
        if service == "translation":
            return _SpeechResponse(200, payload={"translations": "Good day"})
        return _SpeechResponse(200, content=wav_bytes(0.2), headers={"content-type": "audio/wav"})


@pytest.fixture
def speech_services(monkeypatch) -> SpeechServices:
    import requests

    services = SpeechServices()
    monkeypatch.setattr(requests, "post", services.post)
    return services


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

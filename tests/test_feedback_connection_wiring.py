"""The two feedback pools are opened, reported and recovered independently.

Reconciliation and retention are deployment-wide: there is no tenant to bind
them to, so under the request-path role they would see no rows and report
success. Migration 002 gives them `ssf_feedback_maintenance`, and these assert
the gateway really opens a second pool with it -- sharing the request pool
would silently disable both passes.

They are also the tests for the reporting: the halves fail independently, and
announcing an endpoint outage because the maintenance role is unreachable sends
an operator to the wrong problem.
"""

import base64

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway import app as gateway
from services.api_gateway.feedback import repository as repository_module

APP_URL = "postgresql://ssf_feedback_app@db:5432/ssf"
MAINTENANCE_URL = "postgresql://ssf_feedback_maintenance@db:5432/ssf"

# Not URL-safe, deliberately: this is the shape `openssl rand -base64 32`
# produces, and it must reach asyncpg untouched.
APP_PASSWORD = "app/secret+value="
MAINTENANCE_PASSWORD = "maintenance/secret+value="


class RecordingRepository:
    """Stands in for a pool, recording exactly what it was asked to open."""

    opened: list[dict] = []
    fail_for: set[str] = set()

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @classmethod
    async def create(cls, *, dsn: str, password: str | None = None):
        cls.opened.append({"dsn": dsn, "password": password})
        if dsn in cls.fail_for:
            raise ConnectionRefusedError("the database is not accepting connections")
        return cls(dsn)


@pytest.fixture
def wired(monkeypatch):
    """A gateway app.state with nothing feedback-related wired yet."""
    RecordingRepository.opened = []
    RecordingRepository.fail_for = set()
    monkeypatch.setattr(repository_module, "PostgresFeedbackRepository", RecordingRepository)

    monkeypatch.setenv("SSF_FEEDBACK_DATABASE_PASSWORD", APP_PASSWORD)
    monkeypatch.setenv("SSF_FEEDBACK_MAINTENANCE_DATABASE_PASSWORD", MAINTENANCE_PASSWORD)
    monkeypatch.setenv(
        "SSF_FEEDBACK_ENCRYPTION_KEY",
        base64.b64encode(b"test-only-32-byte-key-for-units!").decode(),
    )

    state = gateway.app.state
    previous = {
        name: getattr(state, name, None)
        for name in (
            "feedback_repository",
            "feedback_maintenance_repository",
            "feedback_service",
            "feedback_maintenance",
            "quality_telemetry",
            "prometheus_registry",
        )
    }
    state.feedback_repository = None
    state.feedback_maintenance_repository = None
    state.feedback_service = None
    state.feedback_maintenance = None
    state.quality_telemetry = object()
    state.prometheus_registry = CollectorRegistry()

    yield state

    for name, value in previous.items():
        setattr(state, name, value)


class TestEachHalfOpensItsOwnPool:
    async def test_the_request_path_opens_the_request_role(self, wired) -> None:
        await gateway._connect_feedback_request_path(APP_URL, object())

        assert RecordingRepository.opened == [{"dsn": APP_URL, "password": APP_PASSWORD}]
        assert wired.feedback_service is not None

    async def test_the_passes_open_the_maintenance_role(self, wired) -> None:
        await gateway._connect_feedback_maintenance(MAINTENANCE_URL)

        assert RecordingRepository.opened == [
            {"dsn": MAINTENANCE_URL, "password": MAINTENANCE_PASSWORD}
        ]
        assert wired.feedback_maintenance is not None

    async def test_the_two_pools_are_not_the_same_pool(self, wired) -> None:
        await gateway._connect_feedback_request_path(APP_URL, object())
        await gateway._connect_feedback_maintenance(MAINTENANCE_URL)

        assert wired.feedback_repository is not wired.feedback_maintenance_repository
        assert wired.feedback_maintenance_repository.dsn == MAINTENANCE_URL

    async def test_a_generated_password_is_not_pasted_into_the_url(self, wired) -> None:
        """`/` in a URL password raises before any I/O; `@` corrupts the host."""
        await gateway._connect_feedback_request_path(APP_URL, object())

        opened = RecordingRepository.opened[0]
        assert APP_PASSWORD not in opened["dsn"]
        assert opened["password"] == APP_PASSWORD


class TestTheHalvesFailIndependently:
    async def test_an_unreachable_maintenance_role_leaves_submissions_working(self, wired) -> None:
        """Collecting feedback matters more than reconciling it."""
        RecordingRepository.fail_for = {MAINTENANCE_URL}

        assert await gateway._connect_feedback_request_path(APP_URL, object()) is True
        assert await gateway._connect_feedback_maintenance(MAINTENANCE_URL) is False

        assert wired.feedback_service is not None
        assert wired.feedback_maintenance is None

    async def test_an_unreachable_request_role_is_reported_as_retryable(self, wired) -> None:
        RecordingRepository.fail_for = {APP_URL}

        assert await gateway._connect_feedback_request_path(APP_URL, object()) is False
        assert wired.feedback_service is None

    async def test_a_missing_maintenance_url_is_settled_rather_than_retried(self, wired) -> None:
        """Unset is a decision, not an outage: retrying it would never end."""
        assert await gateway._connect_feedback_maintenance("") is True
        assert wired.feedback_maintenance is None

    async def test_a_missing_encryption_key_is_settled_rather_than_retried(
        self, wired, monkeypatch
    ) -> None:
        """No key appears on its own, so this must not retry forever."""
        monkeypatch.delenv("SSF_FEEDBACK_ENCRYPTION_KEY", raising=False)

        assert await gateway._connect_feedback_request_path(APP_URL, object()) is True
        assert wired.feedback_service is None
        assert RecordingRepository.opened == []


class TestReconnectingIsIdempotent:
    async def test_an_already_wired_half_is_not_opened_twice(self, wired) -> None:
        """The retry loop calls both halves on every tick."""
        await gateway._connect_feedback_request_path(APP_URL, object())
        await gateway._connect_feedback_request_path(APP_URL, object())

        assert len(RecordingRepository.opened) == 1


class TestTheHalvesAreIndependentlyReachable:
    """Turning submission off must not turn retention off with it.

    Unsetting SSF_FEEDBACK_DATABASE_URL is the documented way to stop
    accepting feedback while keeping the database. The rows already stored
    still carry a twelve-month expiry the submission notice promises in ten
    languages, and nothing else enforces it.
    """

    async def test_the_passes_run_even_when_submission_is_switched_off(self, wired) -> None:
        await gateway._wire_feedback("", MAINTENANCE_URL, object())

        assert wired.feedback_service is None
        assert wired.feedback_maintenance is not None

    async def test_the_retry_loop_keeps_trying_the_maintenance_half_alone(self, wired) -> None:
        """Otherwise a database that is briefly down disables retention until
        someone restarts the gateway."""
        RecordingRepository.fail_for = {MAINTENANCE_URL}

        assert await gateway._wire_feedback("", MAINTENANCE_URL, object()) is False

    async def test_neither_url_set_is_settled_rather_than_retried(self, wired) -> None:
        assert await gateway._wire_feedback("", "", object()) is True


class TestAMissingDependencyCostsFeedbackNotTheGateway:
    """The feedback modules are imported lazily and must stay non-fatal.

    `crypto.py` imports `cryptography` directly, which reaches the image only
    as the `[crypto]` extra on PyJWT. Dropping that extra -- or any other
    import error inside this subtree -- would otherwise propagate out of the
    lifespan and stop the gateway booting at all, which is the opposite of
    what every comment in this path promises.
    """

    async def test_an_import_error_degrades_to_503_rather_than_failing_startup(
        self, wired, monkeypatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def refuse_cryptography(name, *args, **kwargs):
            if "feedback.crypto" in name or name == "cryptography":
                raise ImportError("No module named 'cryptography'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse_cryptography)

        assert await gateway._connect_feedback_request_path(APP_URL, object()) is True
        assert wired.feedback_service is None


READER_URL = "postgresql://ssf_feedback_reader@db:5432/ssf"
READER_PASSWORD = "reader/secret+value="


class RecordingReadRepository(RecordingRepository):
    """The read role's pool, recorded separately from the other two."""

    opened: list[dict] = []
    fail_for: set[str] = set()


@pytest.fixture
def wired_reader(wired, monkeypatch):
    RecordingReadRepository.opened = []
    RecordingReadRepository.fail_for = set()
    monkeypatch.setattr(
        repository_module, "PostgresFeedbackReadRepository", RecordingReadRepository
    )
    monkeypatch.setenv("SSF_FEEDBACK_READER_DATABASE_PASSWORD", READER_PASSWORD)
    previous = getattr(wired, "feedback_read_service", None)
    wired.feedback_read_service = None
    wired.feedback_read_repository = None
    yield wired
    wired.feedback_read_service = previous


class TestTheReadPathOpensItsOwnRole:
    async def test_the_read_path_opens_the_read_role(self, wired_reader) -> None:
        await gateway._connect_feedback_read_path(READER_URL)

        assert RecordingReadRepository.opened == [{"dsn": READER_URL, "password": READER_PASSWORD}]
        assert wired_reader.feedback_read_service is not None

    async def test_the_read_pool_is_not_the_request_pool(self, wired_reader) -> None:
        """Sharing would give the unauthenticated submit path audit privileges."""
        await gateway._connect_feedback_request_path(APP_URL, object())
        await gateway._connect_feedback_read_path(READER_URL)

        assert wired_reader.feedback_read_repository is not wired_reader.feedback_repository

    async def test_an_unconfigured_read_role_leaves_submissions_working(self, wired_reader) -> None:
        """Not every deployment grants Studio read access; that is not a fault."""
        await gateway._connect_feedback_request_path(APP_URL, object())

        assert await gateway._connect_feedback_read_path("") is True
        assert wired_reader.feedback_read_service is None
        assert wired_reader.feedback_service is not None

    async def test_an_unreachable_read_role_does_not_disable_submissions(
        self, wired_reader
    ) -> None:
        RecordingReadRepository.fail_for = {READER_URL}

        await gateway._connect_feedback_request_path(APP_URL, object())
        connected = await gateway._connect_feedback_read_path(READER_URL)

        assert connected is False
        assert wired_reader.feedback_read_service is None
        assert wired_reader.feedback_service is not None

    async def test_a_generated_read_password_is_not_pasted_into_the_url(self, wired_reader) -> None:
        await gateway._connect_feedback_read_path(READER_URL)

        opened = RecordingReadRepository.opened[0]
        assert READER_PASSWORD not in opened["dsn"]
        assert opened["password"] == READER_PASSWORD


class TestTheRequestPathTakesTheTenantFromTheSession:
    async def test_the_service_resolves_tenants_through_the_session(self, wired) -> None:
        """Wiring the configured resolver alone would store every tenant's
        feedback under one tenant, and the read path would then show it to
        one tenant's operators and hide it from all the others."""
        from services.api_gateway.feedback.tenant import SessionTenantResolver

        await gateway._connect_feedback_request_path(APP_URL, object())

        assert isinstance(wired.feedback_service._tenant_resolver, SessionTenantResolver)

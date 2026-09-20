"""The password must not travel inside the connection string.

asyncpg parses a DSN as a URL. `openssl rand -base64 32` -- what the runbook
tells an operator to run -- produces `/` in about half of its output, and with
two role passwords that made roughly three deployments in four fail at pool
creation. `@` is worse: it does not raise at all, it truncates the password and
folds the rest into the hostname.

These tests use the production repository's pool creation boundary, so a
regression in how it passes credentials to asyncpg is observable too.
"""

import asyncio
import socket

import asyncpg
import pytest

from services.api_gateway.feedback.repository import PostgresFeedbackRepository

# Refused immediately rather than routed anywhere: a DSN that parses gets a
# connection error, a DSN that does not parse never reaches the socket. That
# difference is the assertion.
UNREACHABLE = "127.0.0.1:1"

CONNECT_REACHED = (OSError, asyncio.TimeoutError, asyncpg.PostgresError)


async def _connect(
    dsn: str,
    password: str | None = None,
    *,
    error_type: type[Exception] = ConnectionRefusedError,
    match: str = "Connect call failed",
) -> Exception:
    async with asyncio.timeout(2):
        with pytest.raises(error_type, match=match) as caught:
            await PostgresFeedbackRepository.create(dsn=dsn, password=password)
    return caught.value


async def test_a_password_with_a_slash_is_fatal_inside_the_connection_string() -> None:
    """The defect, at the boundary that has it."""
    error = await _connect(
        f"postgresql://ssf_feedback_app:a/b@{UNREACHABLE}/ssf",
        error_type=ValueError,
        match="invalid literal for int",
    )

    assert isinstance(error, ValueError)
    assert not isinstance(error, CONNECT_REACHED)


async def test_a_password_with_an_at_sign_silently_corrupts_the_host() -> None:
    """No parse error: the password is truncated and the rest becomes the host.

    127.0.0.1 refuses the connection, so a DSN that survived intact fails with
    ECONNREFUSED. This one cannot resolve `b@127.0.0.1` at all, and the
    difference between those two failures is the whole defect.
    """
    error = await _connect(
        f"postgresql://ssf_feedback_app:a@b@{UNREACHABLE}/ssf",
        error_type=socket.gaierror,
        match="Name or service not known|nodename nor servname|Name does not resolve",
    )

    assert isinstance(error, socket.gaierror), error
    intact = await _connect(f"postgresql://ssf_feedback_app@{UNREACHABLE}/ssf", "a@b")
    assert not isinstance(intact, socket.gaierror), intact


async def test_the_same_password_supplied_separately_reaches_the_socket() -> None:
    """Out of band, every byte a generator can emit is just a password."""
    for password in ("a/b", "a@b", "a:b", "a?b", "a#b", "not-a-secret" + "/+=@"):
        error = await _connect(f"postgresql://ssf_feedback_app@{UNREACHABLE}/ssf", password)

        assert isinstance(error, CONNECT_REACHED), (password, error)


class TestEveryDriverFailureIsRetryable:
    """`store()` must map any driver failure onto FeedbackStorageUnavailable.

    The route catches that one exception and answers 503 with Retry-After.
    Anything else reaches FastAPI as a 500 with a traceback -- which loses the
    submission and, worse, puts the asyncpg error into a response, and an
    asyncpg error carries the bound parameters.
    """

    # Neither of these inherits from PostgresError or OSError. InterfaceError
    # is what a pooled connection closed by the server raises, and what
    # `pool.acquire()` raises once the pool is closing -- so both arrive during
    # an ordinary restart, not only in exotic failures.
    @pytest.mark.parametrize(
        "error",
        [asyncpg.InterfaceError("connection is closed"), asyncpg.InternalClientError("broken")],
    )
    def test_the_driver_error_does_not_inherit_from_what_the_handler_caught(self, error) -> None:
        assert not isinstance(error, (asyncpg.PostgresError, OSError))

    @pytest.mark.parametrize(
        "error",
        [
            asyncpg.InterfaceError("connection is closed"),
            asyncpg.InternalClientError("broken"),
            asyncpg.PostgresError("server said no"),
            OSError("network is unreachable"),
        ],
    )
    async def test_it_is_reported_as_unavailable_rather_than_escaping(self, error) -> None:
        from services.api_gateway.feedback.repository import (
            FeedbackStorageUnavailable,
            PostgresFeedbackRepository,
        )

        class FailingPool:
            def acquire(self):
                raise error

        repository = PostgresFeedbackRepository(FailingPool())
        record = object()

        with pytest.raises(FeedbackStorageUnavailable, match="could not be committed"):
            await repository.store(record)


class TestTheReadPathFailsTheSameWay:
    """The Studio read path gets the same mapping `store()` has.

    Without it, an ordinary PostgreSQL restart turns both GET endpoints into a
    500, when the lifespan and the provider both promise a retryable 503.
    """

    ERRORS = [
        asyncpg.InterfaceError("connection is closed"),
        asyncpg.InternalClientError("broken"),
        asyncpg.PostgresError("server said no"),
        OSError("network is unreachable"),
    ]

    @staticmethod
    def _repository(error):
        from services.api_gateway.feedback.repository import PostgresFeedbackReadRepository

        class FailingPool:
            def acquire(self):
                raise error

        return PostgresFeedbackReadRepository(FailingPool())

    @pytest.mark.parametrize("error", ERRORS)
    async def test_listing_is_reported_as_unavailable(self, error) -> None:
        from services.api_gateway.feedback.repository import FeedbackStorageUnavailable

        repository = self._repository(error)
        with pytest.raises(FeedbackStorageUnavailable, match="could not be read"):
            await repository.list_records(tenant_id="t", limit=1, offset=0)

    @pytest.mark.parametrize("error", ERRORS)
    async def test_fetching_is_reported_as_unavailable(self, error) -> None:
        from uuid import uuid4

        from services.api_gateway.feedback.repository import FeedbackStorageUnavailable

        repository = self._repository(error)
        feedback_id = uuid4()
        with pytest.raises(FeedbackStorageUnavailable, match="could not be read"):
            await repository.fetch_record(feedback_id=feedback_id, tenant_id="t")

    @pytest.mark.parametrize("error", ERRORS)
    async def test_auditing_is_reported_as_unavailable(self, error) -> None:
        """An audit that cannot be written must stop the disclosure, not 500 it."""
        from uuid import uuid4

        from services.api_gateway.feedback.repository import FeedbackStorageUnavailable

        repository = self._repository(error)
        feedback_id = uuid4()
        with pytest.raises(FeedbackStorageUnavailable, match="could not be read"):
            await repository.record_access(
                feedback_id=feedback_id, tenant_id="t", accessed_by="op", access_scope="detail"
            )

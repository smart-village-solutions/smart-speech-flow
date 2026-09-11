"""The password must not travel inside the connection string.

asyncpg parses a DSN as a URL. `openssl rand -base64 32` -- what the runbook
tells an operator to run -- produces `/` in about half of its output, and with
two role passwords that made roughly three deployments in four fail at pool
creation. `@` is worse: it does not raise at all, it truncates the password and
folds the rest into the hostname.

These tests use only asyncpg's public entry point, so they keep holding if its
DSN parser is rewritten.
"""

import asyncio
import socket

import asyncpg
import pytest

# Refused immediately rather than routed anywhere: a DSN that parses gets a
# connection error, a DSN that does not parse never reaches the socket. That
# difference is the assertion.
UNREACHABLE = "127.0.0.1:1"

CONNECT_REACHED = (OSError, asyncio.TimeoutError, asyncpg.PostgresError)


async def _connect(dsn: str, password: str | None = None) -> Exception:
    with pytest.raises(Exception) as caught:  # noqa: PT011 - the type is the result
        await asyncpg.connect(dsn=dsn, password=password, timeout=1)
    return caught.value


async def test_a_password_with_a_slash_is_fatal_inside_the_connection_string() -> None:
    """The defect, at the boundary that has it."""
    error = await _connect(f"postgresql://ssf_feedback_app:a/b@{UNREACHABLE}/ssf")

    assert isinstance(error, ValueError)
    assert not isinstance(error, CONNECT_REACHED)


async def test_a_password_with_an_at_sign_silently_corrupts_the_host() -> None:
    """No parse error: the password is truncated and the rest becomes the host.

    127.0.0.1 refuses the connection, so a DSN that survived intact fails with
    ECONNREFUSED. This one cannot resolve `b@127.0.0.1` at all, and the
    difference between those two failures is the whole defect.
    """
    error = await _connect(f"postgresql://ssf_feedback_app:a@b@{UNREACHABLE}/ssf")

    assert isinstance(error, socket.gaierror), error
    intact = await _connect(f"postgresql://ssf_feedback_app@{UNREACHABLE}/ssf", "a@b")
    assert not isinstance(intact, socket.gaierror), intact


async def test_the_same_password_supplied_separately_reaches_the_socket() -> None:
    """Out of band, every byte a generator can emit is just a password."""
    for password in ("a/b", "a@b", "a:b", "a?b", "a#b", "not-a-secret" + "/+=@"):
        error = await _connect(f"postgresql://ssf_feedback_app@{UNREACHABLE}/ssf", password)

        assert isinstance(error, CONNECT_REACHED), (password, error)

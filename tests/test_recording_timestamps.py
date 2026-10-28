"""RFC 3161 requests and replies (spec §11.2).

Replies are assembled here from DER; the request side was also checked
against `openssl ts -query -in ... -text` and a public authority by hand.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import aiohttp
import pytest

from services.api_gateway.recording import timestamps
from services.api_gateway.recording.timestamps import (
    REPLY_TYPE,
    TimestampAuthority,
    TimestampRejectedError,
    TimestampUnavailableError,
    _children,
    _integer,
    _read,
    _tlv,
    parse_reply,
    timestamp_request,
)

DIGEST = bytes(range(32))
NONCE = 0x1234_5678_9ABC
SHA256 = bytes.fromhex("608648016503040201")


def _seq(*items: bytes) -> bytes:
    return _tlv(0x30, b"".join(items))


def _oid(raw_hex: str) -> bytes:
    return _tlv(0x06, bytes.fromhex(raw_hex))


def _tst_info(
    digest=DIGEST, nonce=NONCE, *, algorithm=SHA256, accuracy=True, gen_time=b"20261027120000.5Z"
) -> bytes:
    fields = [
        _integer(1),
        _oid("2b0601040181b2310203"),  # some policy OID
        _seq(_seq(_tlv(0x06, algorithm), _tlv(0x05, b"")), _tlv(0x04, digest)),
        _integer(42),
        _tlv(0x18, gen_time),
    ]
    if accuracy:
        fields.append(_seq(_integer(1)))
    if nonce is not None:
        fields.append(_integer(nonce))
    return _seq(*fields)


def _token(info: bytes, certificate: bytes = b"") -> bytes:
    encapsulated = _seq(_oid("2a864886f70d0109100104"), _tlv(0xA0, _tlv(0x04, info)))
    certificates = _tlv(0xA0, certificate) if certificate else b""
    signed_data = _seq(_integer(3), _tlv(0x31, b""), encapsulated, certificates, _tlv(0x31, b""))
    return _seq(_oid("2a864886f70d010702"), _tlv(0xA0, signed_data))


def _reply(status=0, info=None) -> bytes:
    token = _token(_tst_info() if info is None else info)
    return _seq(_seq(_integer(status)), token)


def test_a_request_carries_the_sha256_imprint_the_nonce_and_asks_for_the_certificate():
    request = timestamp_request(DIGEST, NONCE)

    assert request.startswith(b"\x30")
    assert SHA256 in request
    assert _tlv(0x04, DIGEST) in request
    assert _integer(NONCE) in request
    assert request.endswith(b"\x01\x01\xff")


def test_a_request_refuses_anything_but_a_sha256_imprint():
    with pytest.raises(ValueError):
        timestamp_request(b"short", NONCE)


def test_integers_keep_a_leading_zero_where_the_top_bit_is_set():
    assert _integer(0x80) == b"\x02\x02\x00\x80"
    assert _integer(0x7F) == b"\x02\x01\x7f"


def test_a_granted_reply_for_our_imprint_and_nonce_yields_its_token_and_time():
    reply = _reply()

    stamp = parse_reply(reply, DIGEST, NONCE)

    assert stamp.token == _token(_tst_info())
    assert stamp.gen_time == datetime(2026, 10, 27, 12, 0, 0, 500000, tzinfo=timezone.utc)


def test_granted_with_modifications_is_granted_too():
    assert parse_reply(_reply(status=1), DIGEST, NONCE).token


def test_a_reply_without_accuracy_still_finds_the_nonce():
    assert parse_reply(_reply(info=_tst_info(accuracy=False)), DIGEST, NONCE).token


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (_seq(_seq(_integer(2))), "status_2"),
        # A refusal that still carries a token for our request is a refusal.
        (_reply(status=2), "status_2"),
        (_reply(info=_tst_info(digest=bytes(32))), "other_imprint"),
        (_reply(info=_tst_info(algorithm=bytes.fromhex("2b0e03021a"))), "other_imprint"),
        (_reply(info=_tst_info(nonce=NONCE + 1)), "other_nonce"),
        (_reply(info=_tst_info(nonce=None)), "other_nonce"),
        (b"\x30\x05\x02\x01", "malformed_reply"),
        (_reply() + b"\x00", "malformed_reply"),
        (b"", "malformed_reply"),
    ],
)
def test_a_reply_that_is_not_a_grant_for_our_request_is_rejected(reply, code):
    with pytest.raises(TimestampRejectedError) as error:
        parse_reply(reply, DIGEST, NONCE)

    assert error.value.code == code


class Authority:
    """Answers each request with a grant for whatever imprint and nonce it carried."""

    def __init__(self, status=200, content_type=REPLY_TYPE, error=None):
        self.status, self.content_type, self.error = status, content_type, error
        self.requests: list[tuple[str, bytes]] = []

    async def __call__(self, url: str, body: bytes):
        self.requests.append((url, body))
        if self.error is not None:
            raise self.error
        nonce = int.from_bytes(_children(_read(body)[1])[2][1], "big")
        return self.status, self.content_type, _reply(info=_tst_info(nonce=nonce))


def test_the_client_posts_the_query_and_keeps_the_granted_token():
    authority = Authority()

    stamp = asyncio.run(TimestampAuthority(authority).stamp("https://tsa.test/tsr", DIGEST))

    assert stamp.gen_time.year == 2026
    assert authority.requests[0][0] == "https://tsa.test/tsr"


def test_each_request_carries_a_fresh_nonce():
    authority = Authority()
    client = TimestampAuthority(authority)

    asyncio.run(client.stamp("https://tsa.test/tsr", DIGEST))
    asyncio.run(client.stamp("https://tsa.test/tsr", DIGEST))

    assert authority.requests[0][1] != authority.requests[1][1]


@pytest.mark.parametrize(
    "authority",
    [
        Authority(error=aiohttp.ClientConnectionError()),
        Authority(error=TimeoutError()),
        Authority(status=503),
    ],
)
def test_an_unreachable_or_failing_authority_is_retried_later(authority):
    with pytest.raises(TimestampUnavailableError):
        asyncio.run(TimestampAuthority(authority).stamp("https://tsa.test/tsr", DIGEST))


def test_a_reply_of_another_content_type_is_rejected():
    authority = Authority(content_type="text/html")

    with pytest.raises(TimestampRejectedError):
        asyncio.run(TimestampAuthority(authority).stamp("https://tsa.test/tsr", DIGEST))


def test_an_oversized_reply_is_rejected():
    async def huge(url, body):
        return 200, REPLY_TYPE, b"\x00" * (timestamps.MAX_REPLY_BYTES + 1)

    with pytest.raises(TimestampRejectedError):
        asyncio.run(TimestampAuthority(huge).stamp("https://tsa.test/tsr", DIGEST))


@pytest.mark.parametrize(
    "gen_time",
    [
        b"20261027120000.-5Z",
        b"20261027120000.+5Z",
        b"20261027120000. 5Z",
        b"2026102712000Z",
        b" 20261027120000Z",
        b"20261027120000.5",
        b"20261327120000Z",
        "20261027120000.٥Z".encode(),
    ],
)
def test_a_reply_with_a_malformed_time_is_rejected_not_raised(gen_time):
    reply = _reply(info=_tst_info(gen_time=gen_time))

    with pytest.raises(TimestampRejectedError) as error:
        parse_reply(reply, DIGEST, NONCE)

    assert error.value.code == "malformed_reply"


def test_a_time_with_nanoseconds_keeps_its_microseconds():
    stamp = parse_reply(
        _reply(info=_tst_info(gen_time=b"20261027120000.123456789Z")), DIGEST, NONCE
    )

    assert stamp.gen_time.microsecond == 123456


async def test_a_reply_that_arrives_in_pieces_is_read_whole(unused_tcp_port):
    from aiohttp import web

    async def answer(request):
        body = await request.read()
        nonce = int.from_bytes(_children(_read(body)[1])[2][1], "big")
        # The authority's certificate makes a real reply several kilobytes long.
        token = _token(_tst_info(nonce=nonce), certificate=b"\x30" * 5000)
        reply = _seq(_seq(_integer(0)), token)
        response = web.StreamResponse(headers={"Content-Type": REPLY_TYPE})
        await response.prepare(request)
        for start in range(0, len(reply), 512):
            await response.write(reply[start : start + 512])
            await asyncio.sleep(0.005)
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/tsr", answer)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
    try:
        url = "http" + f"://127.0.0.1:{unused_tcp_port}/tsr"
        stamp = await TimestampAuthority().stamp(url, DIGEST)
    finally:
        await runner.cleanup()

    assert stamp.gen_time.year == 2026
    assert len(stamp.token) > 5000

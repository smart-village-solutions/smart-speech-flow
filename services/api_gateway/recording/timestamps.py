"""RFC 3161 timestamps for chain heads (spec §11.2).

Only a hash leaves SSF: the request carries the chain head's 32 bytes as a
SHA-256 message imprint and a random nonce. A token is kept only if the
authority granted it and its TSTInfo names that imprint and that nonce; the
CMS signature over it is checked by whoever reads the archive (#616, #619),
against the authority the tenant chose.

The DER here is the few structures RFC 3161 needs, so no ASN.1 library is
pulled into the gateway for them.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

import aiohttp

_SEQUENCE: Final[int] = 0x30
_SET: Final[int] = 0x31
_INTEGER: Final[int] = 0x02
_OCTET_STRING: Final[int] = 0x04
_NULL: Final[int] = 0x05
_OID: Final[int] = 0x06
_BOOLEAN: Final[int] = 0x01
_GENERALIZED_TIME: Final[int] = 0x18
_CONTEXT_0: Final[int] = 0xA0

_SHA256: Final[bytes] = bytes.fromhex("608648016503040201")  # 2.16.840.1.101.3.4.2.1
_SIGNED_DATA: Final[bytes] = bytes.fromhex("2a864886f70d010702")  # 1.2.840.113549.1.7.2
_TST_INFO: Final[bytes] = bytes.fromhex("2a864886f70d0109100104")  # 1.2.840.113549.1.9.16.1.4
_GRANTED: Final[frozenset[int]] = frozenset({0, 1})  # granted, grantedWithMods
_GENERALIZED_TIME_TEXT: Final[re.Pattern[bytes]] = re.compile(rb"([0-9]{14})(?:\.([0-9]{1,9}))?Z")

QUERY_TYPE: Final[str] = "application/timestamp-query"
REPLY_TYPE: Final[str] = "application/timestamp-reply"
REQUEST_TIMEOUT_SECONDS: Final[float] = 10.0
MAX_REPLY_BYTES: Final[int] = 64 * 1024


class TimestampError(Exception):
    """No usable token. `code` names the reason; never a URL or a token byte."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TimestampUnavailableError(TimestampError):
    """The authority could not be reached or answered with an error: retry later."""


class TimestampRejectedError(TimestampError):
    """The authority's answer is a refusal, malformed, or names another hash or nonce."""


@dataclass(frozen=True)
class Timestamp:
    token: bytes  # the DER TimeStampToken (a CMS ContentInfo), as the authority signed it
    gen_time: datetime


def _length(size: int) -> bytes:
    if size < 0x80:
        return bytes([size])
    raw = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _length(len(value)) + value


def _integer(value: int) -> bytes:
    # Unsigned values only; a leading zero keeps the top bit from reading as a sign.
    return _tlv(_INTEGER, value.to_bytes(value.bit_length() // 8 + 1, "big"))


def timestamp_request(digest: bytes, nonce: int) -> bytes:
    if len(digest) != 32:
        raise ValueError("a SHA-256 imprint is 32 bytes")
    algorithm = _tlv(_SEQUENCE, _tlv(_OID, _SHA256) + _tlv(_NULL, b""))
    imprint = _tlv(_SEQUENCE, algorithm + _tlv(_OCTET_STRING, digest))
    cert_req = _tlv(_BOOLEAN, b"\xff")
    return _tlv(_SEQUENCE, _integer(1) + imprint + _integer(nonce) + cert_req)


def _read(data: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    """One definite-length TLV at `offset`: (tag, value, offset after it)."""
    try:
        tag, first = data[offset], data[offset + 1]
    except IndexError:
        raise TimestampRejectedError("malformed_reply") from None
    offset += 2
    if first & 0x80:
        count = first & 0x7F
        if count == 0 or count > 4 or offset + count > len(data):
            raise TimestampRejectedError("malformed_reply")
        size = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    else:
        size = first
    if offset + size > len(data):
        raise TimestampRejectedError("malformed_reply")
    return tag, data[offset : offset + size], offset + size


def _element(data: bytes) -> tuple[int, bytes, bytes]:
    """The single TLV that `data` must consist of."""
    tag, value, end = _read(data)
    if end != len(data):
        raise TimestampRejectedError("malformed_reply")
    return tag, value, data


def _children(value: bytes) -> list[tuple[int, bytes, bytes]]:
    """(tag, value, whole TLV) of each element inside a constructed value."""
    items, offset = [], 0
    while offset < len(value):
        tag, inner, end = _read(value, offset)
        items.append((tag, inner, value[offset:end]))
        offset = end
    return items


def _expect(item: tuple[int, bytes, bytes], tag: int) -> bytes:
    if item[0] != tag:
        raise TimestampRejectedError("malformed_reply")
    return item[1]


def _gen_time(raw: bytes) -> datetime:
    """GeneralizedTime as RFC 3161 allows it: YYYYMMDDhhmmss[.fraction]Z, ASCII digits only."""
    match = _GENERALIZED_TIME_TEXT.fullmatch(raw)
    if match is None:
        raise TimestampRejectedError("malformed_reply")
    whole, fraction = match.group(1).decode(), (match.group(2) or b"").decode()
    try:
        at = datetime.strptime(whole, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return at.replace(microsecond=int((fraction + "000000")[:6]))
    except ValueError:
        raise TimestampRejectedError("malformed_reply") from None


def _tst_info(token: bytes) -> list[tuple[int, bytes, bytes]]:
    """The fields of the TSTInfo inside a token: ContentInfo → SignedData → eContent."""
    content_info = _children(_expect(_element(token), _SEQUENCE))
    if _expect(content_info[0], _OID) != _SIGNED_DATA:
        raise TimestampRejectedError("malformed_reply")
    signed_data_tlv = _children(_expect(content_info[1], _CONTEXT_0))[0]
    # SignedData: version, digestAlgorithms, encapContentInfo, ...
    encapsulated = _children(_expect(_children(_expect(signed_data_tlv, _SEQUENCE))[2], _SEQUENCE))
    if _expect(encapsulated[0], _OID) != _TST_INFO:
        raise TimestampRejectedError("malformed_reply")
    octets = _expect(_children(_expect(encapsulated[1], _CONTEXT_0))[0], _OCTET_STRING)
    return _children(_expect(_element(octets), _SEQUENCE))


def _nonce(fields: list[tuple[int, bytes, bytes]]) -> int | None:
    # After genTime come accuracy (SEQUENCE) and ordering (BOOLEAN), both optional;
    # the first INTEGER after them is the nonce.
    for tag, value, _ in fields[5:]:
        if tag == _INTEGER:
            return int.from_bytes(value, "big", signed=True)
        if tag not in (_SEQUENCE, _BOOLEAN):
            return None
    return None


def parse_reply(reply: bytes, digest: bytes, nonce: int) -> Timestamp:
    """The token in `reply`, if the authority granted it for `digest` and `nonce`."""
    try:
        parts = _children(_expect(_element(reply), _SEQUENCE))
        status_info = _children(_expect(parts[0], _SEQUENCE))
        status = int.from_bytes(_expect(status_info[0], _INTEGER), "big", signed=True)
        if status not in _GRANTED or len(parts) < 2:
            raise TimestampRejectedError(f"status_{status}")
        token = parts[1][2]
        fields = _tst_info(token)
        imprint = _children(_expect(fields[2], _SEQUENCE))
        algorithm = _children(_expect(imprint[0], _SEQUENCE))
        if _expect(algorithm[0], _OID) != _SHA256 or _expect(imprint[1], _OCTET_STRING) != digest:
            raise TimestampRejectedError("other_imprint")
        if _nonce(fields) != nonce:
            raise TimestampRejectedError("other_nonce")
        return Timestamp(token, _gen_time(_expect(fields[4], _GENERALIZED_TIME)))
    except IndexError:
        raise TimestampRejectedError("malformed_reply") from None


# (url, request body) -> (status, content type, body)
Transport = Callable[[str, bytes], Awaitable[tuple[int, str, bytes]]]


async def _aiohttp_transport(url: str, body: bytes) -> tuple[int, str, bytes]:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            url, data=body, headers={"Content-Type": QUERY_TYPE}, allow_redirects=False
        ) as response:
            # read(n) returns what has arrived so far; a reply carrying the
            # authority's certificate often arrives in several pieces.
            reply = bytearray()
            async for piece in response.content.iter_chunked(16 * 1024):
                reply += piece
                if len(reply) > MAX_REPLY_BYTES:
                    break
            return response.status, response.headers.get("Content-Type", ""), bytes(reply)


class TimestampAuthority:
    def __init__(self, transport: Transport = _aiohttp_transport) -> None:
        self._transport = transport

    async def stamp(self, url: str, digest: bytes) -> Timestamp:
        nonce = secrets.randbits(63) + 1
        try:
            status, content_type, reply = await self._transport(
                url, timestamp_request(digest, nonce)
            )
        except (aiohttp.ClientError, TimeoutError, OSError):
            raise TimestampUnavailableError("unreachable") from None
        if status != 200:
            raise TimestampUnavailableError(f"http_{status}")
        if not content_type.lower().startswith(REPLY_TYPE) or len(reply) > MAX_REPLY_BYTES:
            raise TimestampRejectedError("not_a_reply")
        return parse_reply(reply, digest, nonce)

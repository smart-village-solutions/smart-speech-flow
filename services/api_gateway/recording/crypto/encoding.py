"""Canonical byte encodings shared with the browser (spec Appendix A.1).

Every associated-data string, signed message and proof hash is built with
`enc`, so a field can never be shifted into its neighbour: each one carries
its own two-byte length.
"""

from __future__ import annotations

import base64
import re
from typing import Final

SCALAR_BYTES: Final[int] = 32
_MAX_FIELD_BYTES: Final[int] = 0xFFFF
_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")

Field = str | bytes | int


def enc(*fields: Field) -> bytes:
    """Length-prefix each field: strings UTF-8, integers decimal ASCII, bytes as is."""
    out = bytearray()
    for field in fields:
        raw = _field_bytes(field)
        if len(raw) > _MAX_FIELD_BYTES:
            raise ValueError("an encoded field is longer than 65535 bytes")
        out += len(raw).to_bytes(2, "big") + raw
    return bytes(out)


def _field_bytes(field: Field) -> bytes:
    # bool is an int subclass; a flag must be spelled out as a string instead.
    if isinstance(field, bool):
        raise TypeError("booleans have no canonical encoding")
    if isinstance(field, bytes):
        return field
    if isinstance(field, str):
        return field.encode("utf-8")
    if field < 0:
        raise ValueError("integers are encoded unsigned")
    return str(field).encode("ascii")


def scalar_to_bytes(value: int) -> bytes:
    return value.to_bytes(SCALAR_BYTES, "big")


def scalar_from_bytes(raw: bytes) -> int:
    if len(raw) != SCALAR_BYTES:
        raise ValueError("a scalar is 32 bytes")
    return int.from_bytes(raw, "big")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def from_b64url(text: str) -> bytes:
    """Strict: the URL-safe alphabet without padding, nothing else."""
    if not _B64URL.fullmatch(text) or len(text) % 4 == 1:
        raise ValueError("not unpadded base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

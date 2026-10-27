"""AWS Signature Version 4 for the S3 requests the archive makes (spec §12.2).

Only what the archive store sends is covered: path-style URLs, a signed
payload hash, and headers given explicitly. Signing authenticates a request
to the storage VM; the objects themselves are ciphertext already.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"


@dataclass(frozen=True)
class Credentials:
    access_key_id: str
    secret_access_key: str

    def __repr__(self) -> str:
        return f"Credentials(access_key_id={self.access_key_id!r}, secret_access_key=<hidden>)"


def payload_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _encode(value: str, *, keep_slash: bool) -> str:
    return quote(value, safe="/~" if keep_slash else "~")


def canonical_query(query: Mapping[str, str]) -> str:
    pairs = sorted(
        (_encode(k, keep_slash=False), _encode(v, keep_slash=False)) for k, v in query.items()
    )
    return "&".join(f"{key}={value}" for key, value in pairs)


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date: str, region: str) -> bytes:
    key = _hmac(f"AWS4{secret}".encode("utf-8"), date)
    for part in (region, SERVICE, "aws4_request"):
        key = _hmac(key, part)
    return key


def sign(
    *,
    method: str,
    host: str,
    path: str,
    query: Mapping[str, str],
    headers: Mapping[str, str],
    body_hash: str,
    credentials: Credentials,
    region: str,
    now: datetime,
) -> dict[str, str]:
    """The headers to send: `headers` plus host, x-amz-date, x-amz-content-sha256 and Authorization.

    Every header passed in is signed. `path` is the unencoded object path.
    """
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    signed = {name.lower(): " ".join(str(value).split()) for name, value in headers.items()}
    signed |= {"host": host, "x-amz-date": stamp, "x-amz-content-sha256": body_hash}
    names = sorted(signed)
    canonical = "\n".join(
        [
            method,
            _encode(path, keep_slash=True),
            canonical_query(query),
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            body_hash,
        ]
    )
    scope = f"{date}/{region}/{SERVICE}/aws4_request"
    to_sign = "\n".join(
        [ALGORITHM, stamp, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(credentials.secret_access_key, date, region),
        to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"{ALGORITHM} Credential={credentials.access_key_id}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return {**{k: v for k, v in signed.items() if k != "host"}, "Authorization": authorization}

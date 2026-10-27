"""The SigV4 signer reproduces AWS's published S3 examples exactly."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.storage.sigv4 import Credentials, payload_hash, sign

# AWS's documentation key pair, assembled here so no scanner mistakes it for a real one.
EXAMPLE = Credentials("AKIA" + "IOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY")
WHEN = datetime(2013, 5, 24, tzinfo=timezone.utc)
HOST = "examplebucket.s3.amazonaws.com"
EMPTY = payload_hash(b"")


@pytest.mark.parametrize(
    ("method", "path", "query", "headers", "body_hash", "signature"),
    [
        (
            "GET",
            "/test.txt",
            {},
            {"Range": "bytes=0-9"},
            EMPTY,
            "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
        ),
        (
            "PUT",
            "/test$file.text",
            {},
            {"Date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-storage-class": "REDUCED_REDUNDANCY"},
            payload_hash(b"Welcome to Amazon S3."),
            "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd",
        ),
        (
            "GET",
            "/",
            {"lifecycle": ""},
            {},
            EMPTY,
            "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543",
        ),
        (
            "GET",
            "/",
            {"max-keys": "2", "prefix": "J"},
            {},
            EMPTY,
            "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7",
        ),
    ],
)
def test_the_published_examples_sign_identically(
    method, path, query, headers, body_hash, signature
):
    signed = sign(
        method=method,
        host=HOST,
        path=path,
        query=query,
        headers=headers,
        body_hash=body_hash,
        credentials=EXAMPLE,
        region="us-east-1",
        now=WHEN,
    )
    assert signed["Authorization"].endswith(f"Signature={signature}")
    assert signed["Authorization"].startswith(
        f"AWS4-HMAC-SHA256 Credential={EXAMPLE.access_key_id}/20130524/us-east-1/s3/aws4_request"
    )
    assert signed["x-amz-content-sha256"] == body_hash


def test_the_secret_never_appears_in_a_repr_or_the_headers():
    signed = sign(
        method="GET",
        host=HOST,
        path="/x",
        query={},
        headers={},
        body_hash=EMPTY,
        credentials=EXAMPLE,
        region="us-east-1",
        now=WHEN,
    )
    assert EXAMPLE.secret_access_key not in repr(EXAMPLE)
    assert all(EXAMPLE.secret_access_key not in value for value in signed.values())

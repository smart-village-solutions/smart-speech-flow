"""Recording secrets load from files, and refuse anything but the exact shapes."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from services.api_gateway.recording.crypto import aead
from services.api_gateway.recording.secrets import (
    BLOB_KEY_FILE_ENV,
    SIGNING_KEY_FILE_ENV,
    MissingRecordingSecrets,
    RecordingSecrets,
    ServerLayer,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "recording" / "generate-secrets.sh"


def _pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture
def secret_files(tmp_path):
    signing = tmp_path / "signing-key.pem"
    signing.write_bytes(_pem(ec.generate_private_key(ec.SECP256R1())))
    blob = tmp_path / "blob-key"
    blob.write_text(base64.b64encode(os.urandom(32)).decode() + "\n")
    return signing, blob


def test_secrets_load_from_the_configured_files(secret_files, monkeypatch):
    signing, blob = secret_files
    monkeypatch.setenv(SIGNING_KEY_FILE_ENV, str(signing))
    monkeypatch.setenv(BLOB_KEY_FILE_ENV, str(blob))
    secrets = RecordingSecrets.from_environment()
    assert secrets.signing_key_id.startswith("gk-") and len(secrets.signing_key_id) == 19
    assert len(secrets.signing_public_key) == 65


def test_a_missing_file_disables_recording(tmp_path, monkeypatch):
    monkeypatch.setenv(SIGNING_KEY_FILE_ENV, str(tmp_path / "absent.pem"))
    monkeypatch.setenv(BLOB_KEY_FILE_ENV, str(tmp_path / "absent"))
    with pytest.raises(MissingRecordingSecrets):
        RecordingSecrets.from_environment()


def test_a_non_p256_signing_key_is_refused(secret_files):
    signing, blob = secret_files
    signing.write_bytes(_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    with pytest.raises(MissingRecordingSecrets):
        RecordingSecrets.from_files(signing, blob)


@pytest.mark.parametrize("content", ["not base64!", base64.b64encode(b"short").decode()])
def test_a_malformed_blob_key_is_refused(secret_files, content):
    signing, blob = secret_files
    blob.write_text(content)
    with pytest.raises(MissingRecordingSecrets):
        RecordingSecrets.from_files(signing, blob)


def test_the_server_layer_is_bound_to_its_user():
    layer = ServerLayer(os.urandom(32))
    sealed = layer.seal(b"blob", tenant_id="t", user_sub="alice")
    assert layer.open(sealed, tenant_id="t", user_sub="alice") == b"blob"
    with pytest.raises(aead.EnvelopeError):
        layer.open(sealed, tenant_id="t", user_sub="bob")


def test_the_generator_script_writes_loadable_secrets_and_never_overwrites(tmp_path):
    target = tmp_path / "secrets"
    subprocess.run(["sh", str(SCRIPT), str(target)], check=True, capture_output=True)
    RecordingSecrets.from_files(target / "signing-key.pem", target / "blob-key")
    again = subprocess.run(["sh", str(SCRIPT), str(target)], capture_output=True)
    assert again.returncode != 0
    assert oct((target / "blob-key").stat().st_mode & 0o777) == "0o600"

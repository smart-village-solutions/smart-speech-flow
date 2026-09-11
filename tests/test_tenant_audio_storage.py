"""Tenant-isolated audio artifact paths."""

import pytest

from services.api_gateway.audio_storage import AudioVariant, audio_path, save_audio
from services.api_gateway.tenant_session import TenantSessionKey


def test_audio_path_contains_pseudonymous_tenant_and_session(tmp_path) -> None:
    key = TenantSessionKey("tenant-a", "ABC12345")

    path = audio_path(
        key,
        "msg-1",
        AudioVariant.ORIGINAL,
        base_dir=tmp_path,
    )

    assert path == (tmp_path / "v2" / key.tenant_ref / "ABC12345" / "original" / "msg-1.wav")
    assert "tenant-a" not in str(path)


@pytest.mark.parametrize("identifier", ["../escape", "a/b", "", "x" * 129])
def test_audio_path_rejects_unsafe_message_identifiers(tmp_path, identifier) -> None:
    key = TenantSessionKey("tenant-a", "ABC12345")

    with pytest.raises(ValueError):
        audio_path(key, identifier, AudioVariant.TRANSLATED, base_dir=tmp_path)


def test_save_audio_writes_only_the_v2_tenant_path(tmp_path) -> None:
    key = TenantSessionKey("tenant-a", "ABC12345")

    stored = save_audio(
        key,
        "msg-1",
        AudioVariant.TRANSLATED,
        b"RIFFdata",
        base_dir=tmp_path,
    )

    assert stored.read_bytes() == b"RIFFdata"
    assert list(tmp_path.rglob("*.wav")) == [stored]

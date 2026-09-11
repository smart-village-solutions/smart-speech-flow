"""Tenant-isolated audio artifact paths."""

import os
import time

import pytest

from services.api_gateway.audio_storage import (
    AudioVariant,
    RETENTION_HOURS,
    audio_path,
    cleanup_old_audio_files,
    get_disk_usage,
    save_audio,
)
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


def test_v2_cleanup_and_disk_usage_ignore_unmanaged_files(tmp_path) -> None:
    key = TenantSessionKey("tenant-a", "ABC12345")
    expired = save_audio(
        key,
        "expired",
        AudioVariant.ORIGINAL,
        b"old",
        base_dir=tmp_path,
    )
    recent = save_audio(
        key,
        "recent",
        AudioVariant.TRANSLATED,
        b"new-data",
        base_dir=tmp_path,
    )
    legacy = tmp_path / "original" / "legacy.wav"
    unrelated = tmp_path / "v2" / "notes.wav"
    malformed_scope = (
        tmp_path / "v2" / "not-a-tenant-ref" / "ABC12345" / "original" / "other.wav"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    unrelated.write_bytes(b"unrelated")
    malformed_scope.parent.mkdir(parents=True)
    malformed_scope.write_bytes(b"unmanaged")
    old_timestamp = time.time() - (RETENTION_HOURS + 1) * 3600
    os.utime(expired, (old_timestamp, old_timestamp))
    os.utime(legacy, (old_timestamp, old_timestamp))
    os.utime(unrelated, (old_timestamp, old_timestamp))
    os.utime(malformed_scope, (old_timestamp, old_timestamp))

    usage = get_disk_usage(base_dir=tmp_path)
    cleanup = cleanup_old_audio_files(base_dir=tmp_path)

    assert usage == {
        "original_bytes": 3,
        "translated_bytes": 8,
        "original_files": 1,
        "translated_files": 1,
        "total_bytes": 11,
        "total_files": 2,
    }
    assert cleanup == {
        "deleted_original": 1,
        "deleted_translated": 0,
        "total_deleted": 1,
        "errors": 0,
    }
    assert not expired.exists()
    assert recent.exists()
    assert legacy.exists()
    assert unrelated.exists()
    assert malformed_scope.exists()

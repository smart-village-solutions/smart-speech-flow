"""Tenant-isolated audio artifact paths, and the retention marker beside them."""

import json
from pathlib import Path
import logging
import os
import time

import pytest

from services.api_gateway.audio_storage import (
    RETENTION_MARKER,
    AudioVariant,
    audio_path,
    cleanup_old_audio_files,
    get_disk_usage,
    save_audio,
)
from services.api_gateway.content_retention import DEFAULT_TERMINAL_RECORD_HOURS
from services.api_gateway.tenant_session import TenantSessionKey

KEY = TenantSessionKey("tenant-a", "ABC12345")


@pytest.fixture(autouse=True)
def default_terminal_period(monkeypatch):
    monkeypatch.delenv("SSF_TERMINAL_RECORD_HOURS", raising=False)


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
    old_timestamp = time.time() - (DEFAULT_TERMINAL_RECORD_HOURS + 1) * 3600
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


def _hours_ago(path, hours: float) -> None:
    then = time.time() - hours * 3600
    os.utime(path, (then, then))


def _session_dir(tmp_path, key: TenantSessionKey = KEY):
    return tmp_path / "v2" / key.tenant_ref / key.session_id


def _saved(tmp_path, message_id: str, *, age_hours: float, retention_hours=None, key=KEY):
    path = save_audio(
        key,
        message_id,
        AudioVariant.ORIGINAL,
        b"RIFF",
        base_dir=tmp_path,
        retention_hours=retention_hours,
    )
    _hours_ago(path, age_hours)
    return path


def _age_directory(tmp_path, hours: float, key: TenantSessionKey = KEY) -> None:
    """Date every entry of a session directory back, as if nothing touched it since."""
    session_dir = _session_dir(tmp_path, key)
    for entry in [*session_dir.rglob("*"), session_dir]:
        _hours_ago(entry, hours)


def test_saving_with_a_captured_retention_writes_the_marker(tmp_path) -> None:
    save_audio(KEY, "msg-1", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path, retention_hours=4320)

    marker = _session_dir(tmp_path) / RETENTION_MARKER
    assert json.loads(marker.read_text(encoding="utf-8")) == {"hours": 4320}


def test_saving_without_a_captured_retention_writes_no_marker(tmp_path) -> None:
    save_audio(KEY, "msg-1", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path)

    assert not (_session_dir(tmp_path) / RETENTION_MARKER).exists()


def test_a_matching_marker_is_not_rewritten(tmp_path) -> None:
    save_audio(KEY, "msg-1", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path, retention_hours=0)
    marker = _session_dir(tmp_path) / RETENTION_MARKER
    _hours_ago(marker, 5)
    written = marker.stat().st_mtime

    save_audio(KEY, "msg-2", AudioVariant.TRANSLATED, b"RIFF", base_dir=tmp_path, retention_hours=0)

    assert marker.stat().st_mtime == written
    assert [entry.name for entry in _session_dir(tmp_path).iterdir() if entry.is_file()] == [
        RETENTION_MARKER
    ]


@pytest.mark.parametrize(("hours", "age", "kept"), [(4320, 48, True), (72, 73, False)])
def test_cleanup_applies_the_sessions_marker(tmp_path, hours, age, kept) -> None:
    wav = _saved(tmp_path, "msg-1", age_hours=age, retention_hours=hours)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert wav.exists() is kept


def test_a_zero_marker_keeps_audio_forever(tmp_path) -> None:
    wav = _saved(tmp_path, "msg-1", age_hours=24 * 365, retention_hours=0)
    _age_directory(tmp_path, 24 * 365)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert wav.exists()
    assert (_session_dir(tmp_path) / RETENTION_MARKER).exists()


def test_each_session_directory_is_cleaned_by_its_own_marker(tmp_path) -> None:
    long_key = TenantSessionKey("tenant-a", "LONGKEEP")
    short_key = TenantSessionKey("tenant-b", "SHORTKEP")
    kept = _saved(tmp_path, "msg-1", age_hours=48, retention_hours=4320, key=long_key)
    gone = _saved(tmp_path, "msg-1", age_hours=48, key=short_key)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert kept.exists()
    assert not gone.exists()


def test_without_a_marker_the_short_default_applies(tmp_path) -> None:
    wav = _saved(tmp_path, "msg-1", age_hours=25)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not wav.exists()


def test_the_short_default_is_configurable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "48")
    wav = _saved(tmp_path, "msg-1", age_hours=25)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert wav.exists()


@pytest.mark.parametrize(
    "content",
    ["x", "", "[]", '{"hours": -1}', '{"hours": "4320"}', '{"hours": true}', '{"hours": 1.5}',
     '{"days": 180}', '{"hours": 4320, "extra": 1}', '{"hours": 8761}', '{"hours": 99999999}'],
)
def test_a_corrupt_marker_falls_back_to_the_short_default(tmp_path, content) -> None:
    wav = _saved(tmp_path, "msg-1", age_hours=25)
    (_session_dir(tmp_path) / RETENTION_MARKER).write_text(content, encoding="utf-8")

    stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert not wav.exists()
    assert stats["errors"] == 0


def test_a_marker_that_is_a_directory_falls_back_to_the_short_default(tmp_path) -> None:
    wav = _saved(tmp_path, "msg-1", age_hours=25)
    (_session_dir(tmp_path) / RETENTION_MARKER).mkdir()

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not wav.exists()


def test_a_symlinked_marker_is_not_followed(tmp_path) -> None:
    # A link could borrow another session's "keep forever".
    wav = _saved(tmp_path, "msg-1", age_hours=25)
    elsewhere = tmp_path / "forever.json"
    elsewhere.write_text('{"hours": 0}', encoding="utf-8")
    (_session_dir(tmp_path) / RETENTION_MARKER).symlink_to(elsewhere)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not wav.exists()


def test_the_marker_is_neither_audio_nor_an_unsafe_entry(tmp_path, caplog) -> None:
    _saved(tmp_path, "msg-1", age_hours=1, retention_hours=4320)

    with caplog.at_level(logging.WARNING):
        usage = get_disk_usage(base_dir=tmp_path)
        stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert usage["total_files"] == 1
    assert usage["original_bytes"] == 4
    assert stats["errors"] == 0
    assert "unsafe" not in caplog.text


def test_a_session_directory_emptied_by_cleanup_is_removed(tmp_path) -> None:
    _saved(tmp_path, "msg-1", age_hours=73, retention_hours=72)
    _age_directory(tmp_path, 73)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()


def test_a_session_directory_still_holding_audio_is_kept(tmp_path) -> None:
    gone = _saved(tmp_path, "old", age_hours=73, retention_hours=72)
    kept = _saved(tmp_path, "new", age_hours=1, retention_hours=72)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()
    assert kept.exists()
    assert (_session_dir(tmp_path) / RETENTION_MARKER).exists()


def test_an_empty_session_directory_goes_after_the_short_default(tmp_path) -> None:
    # A declined session: settlement deleted its refused audio, leaving the directories.
    wav = _saved(tmp_path, "msg-1", age_hours=2)
    wav.unlink()
    _age_directory(tmp_path, 2)
    cleanup_old_audio_files(base_dir=tmp_path)
    assert _session_dir(tmp_path).exists()

    _age_directory(tmp_path, 25)
    cleanup_old_audio_files(base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()


def test_an_unknown_entry_stops_removal_and_keeps_the_marker(tmp_path) -> None:
    _saved(tmp_path, "msg-1", age_hours=73, retention_hours=72)
    (_session_dir(tmp_path) / "notes.txt").write_text("operator", encoding="utf-8")
    _age_directory(tmp_path, 73)

    stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert json.loads((_session_dir(tmp_path) / RETENTION_MARKER).read_text()) == {"hours": 72}
    assert (_session_dir(tmp_path) / "notes.txt").exists()
    assert stats["errors"] == 0


def test_a_save_recreates_the_marker_of_a_removed_directory(tmp_path) -> None:
    _saved(tmp_path, "msg-1", age_hours=73, retention_hours=72)
    _age_directory(tmp_path, 73)
    cleanup_old_audio_files(base_dir=tmp_path)

    save_audio(KEY, "msg-2", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path, retention_hours=72)

    assert json.loads((_session_dir(tmp_path) / RETENTION_MARKER).read_text()) == {"hours": 72}


def test_an_out_of_range_marker_does_not_stop_the_pass(tmp_path) -> None:
    # Beyond Studio's cap a cutoff can fall before year 1; one bad marker must
    # not cost every other tenant its cleanup.
    other = TenantSessionKey("tenant-b", "OTHERSES")
    _saved(tmp_path, "msg-1", age_hours=25)
    (_session_dir(tmp_path) / RETENTION_MARKER).write_text('{"hours": 99999999}', encoding="utf-8")
    gone = _saved(tmp_path, "msg-1", age_hours=25, key=other)

    stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()
    assert stats["errors"] == 0


def _old_empty_session(tmp_path, *, hours=None):
    """A session directory whose audio is gone, untouched past every cutoff."""
    wav = _saved(tmp_path, "msg-1", age_hours=1, retention_hours=hours)
    wav.unlink()
    _age_directory(tmp_path, 100)


def test_a_marker_a_save_writes_during_removal_survives(tmp_path, monkeypatch) -> None:
    # The cleanup read no marker; a consented save lands while it removes the directory.
    _old_empty_session(tmp_path)
    real_rmdir = Path.rmdir
    raced = []

    def rmdir_with_a_save(self):
        if self.name == AudioVariant.TRANSLATED.value and not raced:
            raced.append(save_audio(
                KEY, "msg-2", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path, retention_hours=4320
            ))
        return real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", rmdir_with_a_save)
    cleanup_old_audio_files(base_dir=tmp_path)

    assert raced[0].exists()
    assert json.loads((_session_dir(tmp_path) / RETENTION_MARKER).read_text()) == {"hours": 4320}


def test_a_session_directory_that_vanishes_mid_removal_does_not_stop_the_pass(
    tmp_path, monkeypatch
) -> None:
    import shutil

    _old_empty_session(tmp_path, hours=72)
    other = TenantSessionKey("tenant-b", "OTHERSES")
    gone = _saved(tmp_path, "msg-1", age_hours=25, key=other)
    real_rmdir = Path.rmdir

    def vanish(self):
        if self == _session_dir(tmp_path):
            shutil.rmtree(self)
            raise FileNotFoundError(self)
        return real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", vanish)
    cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()

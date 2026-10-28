"""Tenant-isolated delivery audio: its paths, its session deletion and its stray-file cleanup."""

from pathlib import Path
import logging
import os
import shutil
import time

import pytest

from services.api_gateway.audio_storage import (
    AudioStore,
    AudioVariant,
    audio_path,
    cleanup_old_audio_files,
    delete_session_audio,
    get_disk_usage,
    save_audio,
)
from services.api_gateway.content_retention import delivery_audio_hours
from services.api_gateway.tenant_session import TenantSessionKey

KEY = TenantSessionKey("tenant-a", "ABC12345")


@pytest.fixture(autouse=True)
def default_terminal_period(monkeypatch):
    monkeypatch.delenv("SSF_TERMINAL_RECORD_HOURS", raising=False)
    monkeypatch.delenv("SSF_SESSION_MAX_HOURS", raising=False)


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
    malformed_scope = tmp_path / "v2" / "not-a-tenant-ref" / "ABC12345" / "original" / "other.wav"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    unrelated.write_bytes(b"unrelated")
    malformed_scope.parent.mkdir(parents=True)
    malformed_scope.write_bytes(b"unmanaged")
    old_timestamp = time.time() - (delivery_audio_hours() + 1) * 3600
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


def _saved(
    tmp_path,
    message_id: str,
    *,
    age_hours: float,
    key=KEY,
    variant: AudioVariant = AudioVariant.ORIGINAL,
):
    path = save_audio(key, message_id, variant, b"RIFF", base_dir=tmp_path)
    _hours_ago(path, age_hours)
    return path


def _old_empty_session(tmp_path) -> None:
    """A session directory whose audio is gone."""
    _saved(tmp_path, "msg-1", age_hours=1).unlink()


def test_deleting_a_session_removes_all_its_audio_and_its_directory(tmp_path) -> None:
    for variant in AudioVariant:
        _saved(tmp_path, "msg-1", age_hours=0, variant=variant)
    _saved(tmp_path, "msg-2", age_hours=0)

    delete_session_audio(KEY, base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()
    assert list(tmp_path.rglob("*.wav")) == []


def test_deleting_a_session_leaves_other_sessions_audio(tmp_path) -> None:
    same_tenant = TenantSessionKey("tenant-a", "SIBLING1")
    other_tenant = TenantSessionKey("tenant-b", "ABC12345")
    _saved(tmp_path, "msg-1", age_hours=0)
    sibling = _saved(tmp_path, "msg-1", age_hours=0, key=same_tenant)
    foreign = _saved(tmp_path, "msg-1", age_hours=0, key=other_tenant)

    delete_session_audio(KEY, base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()
    assert sibling.read_bytes() == b"RIFF"
    assert foreign.read_bytes() == b"RIFF"


def test_deleting_a_session_without_audio_does_nothing(tmp_path) -> None:
    delete_session_audio(KEY, base_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_deleting_a_session_does_not_follow_a_symlinked_session_directory(tmp_path, caplog) -> None:
    elsewhere = tmp_path / "elsewhere" / "original"
    elsewhere.mkdir(parents=True)
    victim = elsewhere / "keep.wav"
    victim.write_bytes(b"RIFF")
    _session_dir(tmp_path).parent.mkdir(parents=True)
    _session_dir(tmp_path).symlink_to(elsewhere.parent, target_is_directory=True)

    with caplog.at_level(logging.WARNING):
        delete_session_audio(KEY, base_dir=tmp_path)

    assert victim.read_bytes() == b"RIFF"
    assert _session_dir(tmp_path).is_symlink()
    assert caplog.text == ""


def test_a_session_deletion_the_filesystem_refuses_is_logged_not_raised(
    tmp_path, monkeypatch, caplog
) -> None:
    stuck = _saved(tmp_path, "msg-1", age_hours=0)

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(shutil, "rmtree", refuse)
    with caplog.at_level(logging.WARNING):
        delete_session_audio(KEY, base_dir=tmp_path)

    assert stuck.exists()
    assert "Failed to delete a session's audio" in caplog.text


def test_the_store_deletes_a_session_below_its_own_directory(tmp_path) -> None:
    store = AudioStore(tmp_path)
    store.save(KEY, "msg-1", AudioVariant.TRANSLATED, b"RIFF")

    store.delete_session(KEY)

    assert not _session_dir(tmp_path).exists()


def test_cleanup_deletes_audio_older_than_any_session_and_keeps_newer(tmp_path) -> None:
    """No session outlives SSF_SESSION_MAX_HOURS (8): its audio cannot either, plus an hour."""
    assert delivery_audio_hours() == 9
    gone = _saved(tmp_path, "old", age_hours=10)
    kept = _saved(tmp_path, "new", age_hours=8)

    stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()
    assert kept.exists()
    assert stats["total_deleted"] == 1


def test_cleanup_applies_the_same_period_to_every_session(tmp_path) -> None:
    other = TenantSessionKey("tenant-b", "OTHERSES")
    gone = _saved(tmp_path, "msg-1", age_hours=25)
    also_gone = _saved(tmp_path, "msg-1", age_hours=25, key=other, variant=AudioVariant.TRANSLATED)

    stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()
    assert not also_gone.exists()
    assert (stats["deleted_original"], stats["deleted_translated"]) == (1, 1)


def test_the_cutoff_follows_the_maximum_session_lifetime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SSF_SESSION_MAX_HOURS", "48")
    kept = _saved(tmp_path, "kept", age_hours=25)
    gone = _saved(tmp_path, "gone", age_hours=50)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert kept.exists()
    assert not gone.exists()


def test_a_shorter_session_lifetime_deletes_sooner(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SSF_SESSION_MAX_HOURS", "2")
    gone = _saved(tmp_path, "msg-1", age_hours=4)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()


def test_a_short_terminal_record_period_never_reaches_a_live_sessions_audio(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SSF_TERMINAL_RECORD_HOURS", "1")
    kept = _saved(tmp_path, "msg-1", age_hours=5)  # the session may run 8 hours

    cleanup_old_audio_files(base_dir=tmp_path)

    assert kept.exists()


def test_an_unusable_session_lifetime_falls_back_to_the_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SSF_SESSION_MAX_HOURS", "never")
    gone = _saved(tmp_path, "msg-1", age_hours=25)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()


def test_a_session_directory_emptied_by_cleanup_is_removed(tmp_path) -> None:
    for variant in AudioVariant:
        _saved(tmp_path, "msg-1", age_hours=25, variant=variant)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()
    assert _session_dir(tmp_path).parent.exists()


def test_a_session_directory_still_holding_audio_is_kept(tmp_path) -> None:
    gone = _saved(tmp_path, "old", age_hours=25)
    kept = _saved(tmp_path, "new", age_hours=1)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not gone.exists()
    assert kept.exists()


def test_an_empty_session_directory_is_removed_on_the_next_pass(tmp_path) -> None:
    _old_empty_session(tmp_path)

    cleanup_old_audio_files(base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()


def test_an_unknown_entry_keeps_the_session_directory_and_is_reported(tmp_path, caplog) -> None:
    _saved(tmp_path, "msg-1", age_hours=25)
    (_session_dir(tmp_path) / "notes.txt").write_text("operator", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        stats = cleanup_old_audio_files(base_dir=tmp_path)

    assert (_session_dir(tmp_path) / "notes.txt").exists()
    assert "could not be removed" in caplog.text
    assert stats["errors"] == 0


def test_a_save_during_directory_removal_survives(tmp_path, monkeypatch) -> None:
    _old_empty_session(tmp_path)
    real_rmdir = Path.rmdir
    raced = []

    def rmdir_with_a_save(self):
        if self.name == AudioVariant.TRANSLATED.value and not raced:
            raced.append(
                save_audio(KEY, "msg-2", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path)
            )
        return real_rmdir(self)

    monkeypatch.setattr(Path, "rmdir", rmdir_with_a_save)
    cleanup_old_audio_files(base_dir=tmp_path)

    assert raced[0].read_bytes() == b"RIFF"


def test_a_session_directory_that_vanishes_mid_removal_does_not_stop_the_pass(
    tmp_path, monkeypatch
) -> None:
    _old_empty_session(tmp_path)
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


def _shift_back(tmp_path, hours: float) -> None:
    """Let `hours` pass: every entry of the session directory ages by that much."""
    session_dir = _session_dir(tmp_path)
    for entry in [*session_dir.rglob("*"), session_dir]:
        stat = entry.stat()
        os.utime(entry, (stat.st_atime - hours * 3600, stat.st_mtime - hours * 3600))


def test_a_directory_whose_audio_expires_in_separate_passes_is_removed(tmp_path) -> None:
    _saved(tmp_path, "first", age_hours=10)
    second = _saved(tmp_path, "second", age_hours=7)
    cleanup_old_audio_files(base_dir=tmp_path)
    assert second.exists()

    _shift_back(tmp_path, 3)
    cleanup_old_audio_files(base_dir=tmp_path)

    assert not _session_dir(tmp_path).exists()


def test_a_save_survives_the_cleanup_removing_its_fresh_directory(tmp_path, monkeypatch) -> None:
    real_write = Path.write_bytes
    removed = []

    def removed_first(self, data):
        if not removed:
            removed.append(self)
            shutil.rmtree(_session_dir(tmp_path))
        return real_write(self, data)

    monkeypatch.setattr(Path, "write_bytes", removed_first)
    stored = save_audio(KEY, "msg-1", AudioVariant.ORIGINAL, b"RIFF", base_dir=tmp_path)

    assert removed and stored.read_bytes() == b"RIFF"

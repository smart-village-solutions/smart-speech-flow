from pathlib import Path

import pytest

from services.api_gateway.tenant_cutover import cutover


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def get(self, key: str):
        return self.values.get(key)

    def scan_iter(self, *, match: str, count: int):
        prefix = match.removesuffix("*")
        yield from [key for key in self.values if key.startswith(prefix)]

    def unlink(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                del self.values[key]
                deleted += 1
        return deleted


@pytest.fixture
def fake_redis():
    redis = FakeRedis()
    redis.set("ssf:sessions", "[]")
    redis.set("ssf:session:active_admin", "ABC12345")
    redis.set("ssf:session:ABC12345", "{}")
    redis.set("ssf:v2:tenant:safe", "keep")
    redis.set("unrelated:key", "keep")
    return redis


def test_cutover_removes_only_allowlisted_legacy_state(fake_redis, tmp_path):
    audio_root = tmp_path / "audio"
    (audio_root / "original").mkdir(parents=True)
    (audio_root / "translated").mkdir()
    (audio_root / "original" / "input-msg.wav").write_bytes(b"wav")
    (audio_root / "keep").mkdir()

    result = cutover(fake_redis, audio_root, apply=True, confirmed=True)

    assert result.redis_keys_deleted == 3
    assert result.audio_directories_deleted == 2
    assert fake_redis.get("ssf:v2:tenant:safe") == "keep"
    assert fake_redis.get("unrelated:key") == "keep"
    assert (audio_root / "keep").is_dir()
    assert not (audio_root / "original").exists()
    assert not (audio_root / "translated").exists()

    repeated = cutover(fake_redis, audio_root, apply=True, confirmed=True)
    assert repeated.redis_keys_deleted == 0
    assert repeated.audio_directories_deleted == 0


def test_dry_run_reports_matches_without_deleting(fake_redis, tmp_path):
    audio_root = tmp_path / "audio"
    (audio_root / "original").mkdir(parents=True)

    result = cutover(fake_redis, audio_root, apply=False, confirmed=False)

    assert result.redis_keys_matched == 3
    assert result.redis_keys_deleted == 0
    assert result.audio_directories_matched == 1
    assert (audio_root / "original").is_dir()
    assert fake_redis.get("ssf:sessions") == "[]"


def test_apply_requires_explicit_empty_production_confirmation(fake_redis, tmp_path):
    with pytest.raises(ValueError, match="confirm-empty-production"):
        cutover(fake_redis, tmp_path / "audio", apply=True, confirmed=False)


@pytest.mark.parametrize("unsafe_root", [Path("/"), Path("")])
def test_cutover_refuses_a_broad_audio_root(fake_redis, unsafe_root):
    with pytest.raises(ValueError, match="audio root"):
        cutover(fake_redis, unsafe_root, apply=False, confirmed=False)


def test_cutover_refuses_symlinked_audio_targets(fake_redis, tmp_path):
    audio_root = tmp_path / "audio"
    elsewhere = tmp_path / "elsewhere"
    audio_root.mkdir()
    elsewhere.mkdir()
    (audio_root / "original").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        cutover(fake_redis, audio_root, apply=False, confirmed=False)

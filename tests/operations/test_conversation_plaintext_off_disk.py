"""Outside the archive, no stack keeps conversation content on disk (spec §5.5, D12)."""

import pytest

from tests.compose_documents import DEVELOPMENT_COMPOSE, PRODUCTION_COMPOSE, load_compose

STACKS = pytest.mark.parametrize(
    "compose", [DEVELOPMENT_COMPOSE, PRODUCTION_COMPOSE], ids=["development", "production"]
)


def _service(compose, name: str) -> dict:
    return load_compose(compose)["services"][name]


def _environment(service: dict) -> dict[str, str]:
    entries = service.get("environment", [])
    if isinstance(entries, dict):
        return {key: str(value) for key, value in entries.items()}
    return dict(entry.split("=", 1) for entry in entries)


@STACKS
def test_redis_writes_nothing_to_disk(compose) -> None:
    redis = _service(compose, "redis")
    command = [str(part) for part in redis["command"]]

    assert command[command.index("--save") + 1] == ""
    assert command[command.index("--appendonly") + 1] == "no"
    assert not redis.get("volumes"), "a Redis volume would keep a dump of live conversations"
    assert "redis-data" not in (load_compose(compose).get("volumes") or {})


@STACKS
def test_delivery_audio_lives_only_on_the_gateways_tmpfs(compose) -> None:
    gateway = _service(compose, "api_gateway")
    tmpfs = [
        volume["target"]
        for volume in gateway["volumes"]
        if isinstance(volume, dict) and volume.get("type") == "tmpfs"
    ]
    named = [volume for volume in gateway["volumes"] if isinstance(volume, str)]

    assert _environment(gateway)["SSF_AUDIO_BASE_DIR"] in tmpfs
    # The gateway runs as uid 100: a root-only mount loses every message's audio,
    # as the root-owned audio volume did in 2026-09.
    [audio] = [v for v in gateway["volumes"] if isinstance(v, dict) and v["target"] == "/tmp/audio"]
    assert audio["tmpfs"]["mode"] == 0o1777
    assert not any(volume.endswith(":/data/audio") for volume in named)
    assert "audio-data" not in (load_compose(compose).get("volumes") or {})


@STACKS
def test_the_gateway_writes_no_core_dump(compose) -> None:
    assert _service(compose, "api_gateway")["ulimits"] == {"core": 0}


def _tmpfs_targets(service: dict) -> list[str]:
    targets = [
        volume["target"]
        for volume in service.get("volumes", [])
        if isinstance(volume, dict) and volume.get("type") == "tmpfs"
    ]
    short = service.get("tmpfs", [])
    targets += [entry.split(":", 1)[0] for entry in ([short] if isinstance(short, str) else short)]
    return targets


@STACKS
@pytest.mark.parametrize("name", ["api_gateway", "asr"])
def test_spooled_uploads_and_temporary_audio_stay_in_memory(compose, name) -> None:
    """Starlette spools an upload over 1 MiB into /tmp, and ASR writes every utterance there."""
    assert "/tmp" in _tmpfs_targets(_service(compose, name))

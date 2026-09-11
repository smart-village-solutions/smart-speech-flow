"""Guarded deletion of conversation state that predates tenant isolation."""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

LEGACY_EXACT_KEYS: Final[tuple[str, ...]] = (
    "{namespace}:sessions",
    "{namespace}:session:active_admin",
)
LEGACY_SESSION_PREFIX: Final[str] = "{namespace}:session:"
LEGACY_AUDIO_DIRS: Final[tuple[str, ...]] = ("original", "translated")
_UNLINK_BATCH_SIZE: Final[int] = 100


@dataclass(frozen=True, slots=True)
class CutoverResult:
    redis_keys_matched: int
    redis_keys_deleted: int
    audio_directories_matched: int
    audio_directories_deleted: int


def _text_key(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="strict")
    if isinstance(raw, str):
        return raw
    raise ValueError("Redis returned a non-text key")


def _legacy_redis_keys(redis_client: Any, namespace: str) -> tuple[str, ...]:
    exact = {template.format(namespace=namespace) for template in LEGACY_EXACT_KEYS}
    prefix = LEGACY_SESSION_PREFIX.format(namespace=namespace)
    v2_prefix = f"{namespace}:v2:"
    candidates: set[str] = set()

    for pattern in (*exact, f"{prefix}*"):
        for raw in redis_client.scan_iter(match=pattern, count=500):
            key = _text_key(raw)
            if key.startswith(v2_prefix):
                continue
            if key in exact or key.startswith(prefix):
                candidates.add(key)
                continue
            raise ValueError("Redis scan returned a key outside the deletion allowlist")

    return tuple(sorted(candidates))


def _audio_targets(audio_root: Path) -> tuple[Path, ...]:
    if not audio_root.is_absolute() or audio_root == Path("/"):
        raise ValueError("audio root must be an absolute, narrow directory")
    if audio_root.is_symlink():
        raise ValueError("audio root must not be a symlink")

    resolved_root = audio_root.resolve(strict=False)
    targets: list[Path] = []
    for name in LEGACY_AUDIO_DIRS:
        target = audio_root / name
        if target.is_symlink():
            raise ValueError("legacy audio target must not be a symlink")
        if target.parent.resolve(strict=False) != resolved_root:
            raise ValueError("legacy audio target escaped the audio root")
        targets.append(target)
    return tuple(targets)


def cutover(
    redis_client: Any,
    audio_root: Path,
    *,
    apply: bool,
    confirmed: bool,
    namespace: str = "ssf",
) -> CutoverResult:
    """Inspect or delete only allowlisted pre-v2 conversation artifacts."""
    if apply and not confirmed:
        raise ValueError("--apply requires --confirm-empty-production")
    if not namespace or any(character.isspace() for character in namespace):
        raise ValueError("invalid Redis namespace")

    redis_keys = _legacy_redis_keys(redis_client, namespace)
    audio_targets = _audio_targets(Path(audio_root))
    existing_audio_targets = tuple(
        target for target in audio_targets if target.is_dir()
    )

    redis_deleted = 0
    audio_deleted = 0
    if apply:
        for offset in range(0, len(redis_keys), _UNLINK_BATCH_SIZE):
            redis_deleted += int(
                redis_client.unlink(*redis_keys[offset : offset + _UNLINK_BATCH_SIZE])
            )
        for target in existing_audio_targets:
            shutil.rmtree(target)
            audio_deleted += 1

    return CutoverResult(
        redis_keys_matched=len(redis_keys),
        redis_keys_deleted=redis_deleted,
        audio_directories_matched=len(existing_audio_targets),
        audio_directories_deleted=audio_deleted,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reset allowlisted legacy conversation state before tenant cutover."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-empty-production", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        from redis import Redis

        redis_client = Redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
        )
        result = cutover(
            redis_client,
            Path(os.environ.get("AUDIO_STORAGE_PATH", "/data/audio")),
            apply=args.apply,
            confirmed=args.confirm_empty_production,
            namespace=os.environ.get("REDIS_NAMESPACE", "ssf"),
        )
    except Exception:
        print("Cutover refused")
        return 2

    mode = "applied" if args.apply else "dry-run"
    print(
        f"Cutover {mode}: legacy_redis_matched={result.redis_keys_matched} "
        f"legacy_redis_deleted={result.redis_keys_deleted} "
        f"legacy_audio_dirs_matched={result.audio_directories_matched} "
        f"legacy_audio_dirs_deleted={result.audio_directories_deleted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The gateway image must own the directories Compose mounts volumes onto.

Docker creates a named volume as root:root when the image has no directory at
the mount point, and the gateway runs as the unprivileged `app` user. That
combination cost production every audio file between 2026-07-21, when the
`audio-data` volume was created, and 2026-09-24: `save_audio` raised
PermissionError, the route logged it as a warning, and the pipeline still
reported success -- so every message arrived with text, no audio URL, and
therefore no player in the UI.
"""

import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY_ROOT / "services" / "api_gateway" / "Dockerfile"
PRODUCTION_COMPOSE = REPOSITORY_ROOT / "deploy" / "production" / "docker-compose.production.yml"


def audio_mount_target() -> str:
    """Where production mounts the audio volume, e.g. ``/data/audio``."""
    compose = yaml.safe_load(PRODUCTION_COMPOSE.read_text())
    targets = [
        entry.split(":", 1)[1]
        for entry in compose["services"]["api_gateway"]["volumes"]
        if isinstance(entry, str) and entry.startswith("audio-data:")
    ]
    assert len(targets) == 1, targets
    return targets[0]


def test_image_creates_the_audio_mount_point_owned_by_the_runtime_user():
    dockerfile = DOCKERFILE.read_text()
    target = audio_mount_target()

    assert f"mkdir -p {target}" in dockerfile, (
        f"the image must contain {target} so Docker initialises the volume "
        "with the image's ownership instead of root:root"
    )
    chowned = {
        match.group("path")
        for match in re.finditer(r"chown\s+-R\s+app:app\s+(?P<path>/\S+)", dockerfile)
    }
    covers_target = any(
        target == path or target.startswith(path.rstrip("/") + "/") for path in chowned
    )
    assert covers_target, (
        f"{target} must belong to app, the user the container runs as; "
        f"recursively chowned paths are {sorted(chowned)}"
    )


def test_the_audio_mount_point_is_prepared_before_the_image_drops_privileges():
    """A chown after ``USER app`` cannot run: app may not chown."""
    dockerfile = DOCKERFILE.read_text()
    target = audio_mount_target()

    assert dockerfile.index(f"mkdir -p {target}") < dockerfile.index("\nUSER app")

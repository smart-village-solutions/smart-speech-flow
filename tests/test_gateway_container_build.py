"""The gateway image must own the directories Compose mounts volumes onto.

Docker creates a named volume as root:root when the image has no directory at
the mount point, and the gateway runs as the unprivileged `app` user. That
combination cost production every audio file between 2026-07-21, when the
`audio-data` volume (since replaced by a tmpfs) was created, and 2026-09-24: `save_audio` raised
PermissionError, the route logged it as a warning, and the pipeline still
reported success -- so every message arrived with text, no audio URL, and
therefore no player in the UI.
"""

import re
from pathlib import Path

from tests.compose_documents import PRODUCTION_COMPOSE, load_compose

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY_ROOT / "services" / "api_gateway" / "Dockerfile"


def volume_mount_targets() -> list[str]:
    """Where production mounts named volumes on the gateway, e.g. ``/data/archive-spool``."""
    compose = load_compose(PRODUCTION_COMPOSE)
    targets = [
        entry.split(":", 2)[1]
        for entry in compose["services"]["api_gateway"]["volumes"]
        if isinstance(entry, str) and not entry.startswith(("/", ".", "$"))
    ]
    assert targets, "the gateway mounts no named volume"
    return targets


def test_image_creates_each_volume_mount_point_owned_by_the_runtime_user():
    dockerfile = DOCKERFILE.read_text()
    chowned = {
        match.group("path")
        for match in re.finditer(r"chown\s+-R\s+app:app\s+(?P<path>/\S+)", dockerfile)
    }
    for target in volume_mount_targets():
        assert re.search(rf"mkdir -p [^\n]*{re.escape(target)}\b", dockerfile), (
            f"the image must contain {target} so Docker initialises the volume "
            "with the image's ownership instead of root:root"
        )
        assert any(
            target == path or target.startswith(path.rstrip("/") + "/") for path in chowned
        ), (
            f"{target} must belong to app, the user the container runs as; "
            f"recursively chowned paths are {sorted(chowned)}"
        )


def test_each_volume_mount_point_is_prepared_before_the_image_drops_privileges():
    """A chown after ``USER app`` cannot run: app may not chown."""
    dockerfile = DOCKERFILE.read_text()
    for target in volume_mount_targets():
        made = re.search(rf"mkdir -p [^\n]*{re.escape(target)}\b", dockerfile)
        assert made is not None and made.start() < dockerfile.index("\nUSER app")

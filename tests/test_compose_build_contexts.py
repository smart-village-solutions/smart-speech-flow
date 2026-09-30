"""A fresh clone must be able to run `docker compose build` (#230)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"


def _build_targets() -> list[tuple[str, Path, Path]]:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    targets = []
    for name, service in compose["services"].items():
        build = service.get("build")
        if build is None:
            continue
        if isinstance(build, str):
            build = {"context": build}
        context = (COMPOSE_PATH.parent / build.get("context", ".")).resolve()
        dockerfile = context / build.get("dockerfile", "Dockerfile")
        targets.append((name, context, dockerfile))
    return targets


def test_default_compose_build_contexts_are_inside_the_repository() -> None:
    targets = _build_targets()

    assert targets, "docker-compose.yml defines no build targets"
    outside = [name for name, context, _ in targets if not context.is_relative_to(ROOT)]
    missing = [name for name, _, dockerfile in targets if not dockerfile.is_file()]
    assert outside == [], f"build context outside the repository: {outside}"
    assert missing == [], f"Dockerfile missing in the build context: {missing}"

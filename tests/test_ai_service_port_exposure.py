"""#221: the model services must not be reachable without authentication.

Both compose files are asserted, because production runs the pinned file in
`deploy/production/` and a fix applied to only one of them leaves the hole open
in the environment that matters.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "deploy" / "production" / "docker-compose.production.yml",
)
AI_SERVICES = ("asr", "translation", "tts")


def _service(compose_path: Path, name: str) -> dict:
    services = yaml.safe_load(compose_path.read_text())["services"]
    assert name in services, f"{name} missing from {compose_path.name}"
    return services[name]


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("name", AI_SERVICES)
def test_ai_service_publishes_no_host_port(compose_path: Path, name: str):
    """A `ports` entry binds 0.0.0.0 by default, which is the whole defect."""
    service = _service(compose_path, name)
    assert "ports" not in service, (
        f"{name} in {compose_path.name} publishes {service.get('ports')} to the host; "
        "use `expose` so the port stays on the compose network"
    )


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("name", AI_SERVICES)
def test_ai_service_still_reachable_inside_the_network(compose_path: Path, name: str):
    """Removing `ports` must not also remove container-to-container access."""
    service = _service(compose_path, name)
    exposed = [str(port) for port in service.get("expose", [])]
    assert "8000" in exposed, (
        f"{name} in {compose_path.name} exposes {exposed}; the gateway calls it "
        "on port 8000 over the compose network"
    )

"""Grafana remains reachable through Traefik without a direct host port."""

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "deploy" / "production" / "docker-compose.production.yml",
)


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda path: path.name)
def test_grafana_is_only_reachable_through_traefik(compose_path: Path) -> None:
    service = yaml.safe_load(compose_path.read_text())["services"]["grafana"]

    assert "ports" not in service
    labels = service.get("labels", [])
    assert any("traefik.http.routers.grafana.rule=" in label for label in labels)
    assert any("traefik.http.services.grafana.loadbalancer.server.port=3000" in label for label in labels)

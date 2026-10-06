"""Grafana remains reachable through Traefik without a direct host port."""

from pathlib import Path

import pytest

from tests.compose_documents import DEVELOPMENT_COMPOSE, PRODUCTION_COMPOSE, load_compose


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (DEVELOPMENT_COMPOSE, PRODUCTION_COMPOSE)


@pytest.mark.parametrize("compose_path", COMPOSE_FILES, ids=lambda path: path.name)
def test_grafana_is_only_reachable_through_traefik(compose_path: Path) -> None:
    service = load_compose(compose_path)["services"]["grafana"]

    assert "ports" not in service
    labels = service.get("labels", [])
    assert any("traefik.http.routers.grafana.rule=" in label for label in labels)
    assert any("traefik.http.services.grafana.loadbalancer.server.port=3000" in label for label in labels)

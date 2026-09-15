"""A runbook command must name the stack it is meant to act on.

Runbooks are followed during an incident, on the production host. A bare
`docker compose` there reads `docker-compose.yml` plus whatever
`docker-compose.override.yml` the operator happens to have, under a project
name derived from the current directory -- a different stack from the one
production runs, which is
`docker compose --project-name ssf-backend --env-file .env
 --file deploy/production/docker-compose.production.yml`, wrapped as
`production_compose` in scripts/lib/production-common.sh.

This guard exists because following the precedent in this directory produced
the bug: `production_compose` has been available since 2026-08-30 and no
runbook used it, so a new runbook written by matching its neighbours was
wrong by construction. A reviewer caught it; nothing in the repository would
have.

KNOWN_BARE_COMPOSE is a ratchet, not an exemption. Each entry records the
number of bare invocations a runbook had when this guard was written. The
count may only go down: fixing lines requires lowering the number, and adding
one fails. A runbook not listed here gets no allowance at all.
"""

import re
from pathlib import Path

import pytest

RUNBOOKS = Path(__file__).resolve().parents[1] / "docs" / "operations" / "runbooks"

# A command line, not prose: the invocation starts the line. Prose references
# such as "`docker compose` reads the dev file" are explanatory and fine.
BARE_COMPOSE = re.compile(r"^\s*(sudo\s+)?docker[- ]compose\s", re.MULTILINE)

KNOWN_BARE_COMPOSE = {
    "clickhouse-operations.md": 20,
    "keycloak-operations.md": 4,
    "websocket-broadcast-failures.md": 6,
}


def _runbooks():
    return sorted(RUNBOOKS.glob("*.md"))


def _bare_count(path: Path) -> int:
    return len(BARE_COMPOSE.findall(path.read_text(encoding="utf-8")))


def test_the_runbook_directory_exists():
    """A rename that empties the glob would make every test below vacuous."""
    assert _runbooks(), f"no runbooks found under {RUNBOOKS}"


@pytest.mark.parametrize("path", _runbooks(), ids=lambda p: p.name)
def test_a_runbook_does_not_grow_bare_compose_commands(path: Path):
    allowed = KNOWN_BARE_COMPOSE.get(path.name, 0)
    found = _bare_count(path)

    assert found <= allowed, (
        f"{path.name} has {found} bare `docker compose` command(s), "
        f"{allowed} allowed. On the production host these act on the "
        "development stack. Use `production_compose` from "
        "scripts/lib/production-common.sh, or spell out --project-name, "
        "--env-file and --file."
    )


@pytest.mark.parametrize("name", sorted(KNOWN_BARE_COMPOSE), ids=str)
def test_the_ratchet_is_tightened_when_a_runbook_is_fixed(name: str):
    """Recorded debt that has been paid must be recorded as paid, or the
    allowance silently becomes room for a new bare command."""
    path = RUNBOOKS / name
    if not path.exists():
        pytest.fail(f"{name} is recorded in KNOWN_BARE_COMPOSE but does not exist")

    found = _bare_count(path)
    allowed = KNOWN_BARE_COMPOSE[name]

    assert found == allowed, (
        f"{name} now has {found} bare `docker compose` command(s) but "
        f"KNOWN_BARE_COMPOSE still says {allowed}. Lower it to {found}."
    )


def test_the_service_down_runbook_uses_production_compose():
    """The runbook this guard was written for, asserted directly."""
    text = (RUNBOOKS / "service-down-alerts.md").read_text(encoding="utf-8")

    assert "production_compose" in text
    assert not BARE_COMPOSE.search(text)

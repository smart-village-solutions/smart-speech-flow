"""Every required production variable must appear in the example that documents it.

`docker-compose.production.yml` refuses to start when a `${VAR:?required}`
variable is unset, and `production.env.example` is the only place an operator
learns what to set. A variable in one and not the other turns a deployment into
an interpolation error with no guidance attached.

The existing guard in test_otel_collector_compose_configuration.py checks a
hardcoded list, so it cannot notice a newly added variable -- which is how #302
shipped `SSF_POSTGRES_DB`, `SSF_POSTGRES_USER`, `SSF_POSTGRES_PASSWORD` and
`SSF_FEEDBACK_ENCRYPTION_KEY` as required with none of them documented. This
derives the list from the compose file, so the next addition is covered without
anyone remembering to extend it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_COMPOSE = ROOT / "deploy" / "production" / "docker-compose.production.yml"
PRODUCTION_ENV_EXAMPLE = ROOT / "deploy" / "production" / "production.env.example"

# ${NAME:?anything} and ${NAME?anything} both fail closed when unset.
_REQUIRED = re.compile(r"\$\{([A-Z0-9_]+):?\?[^}]*\}")


def _required_variables() -> set[str]:
    return set(_REQUIRED.findall(PRODUCTION_COMPOSE.read_text(encoding="utf-8")))


def _documented_variables() -> set[str]:
    documented = set()
    for line in PRODUCTION_ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        documented.add(stripped.split("=", 1)[0].strip())
    return documented


def test_the_compose_file_actually_requires_something() -> None:
    """A regex that matches nothing would make every other test here vacuous."""
    assert len(_required_variables()) >= 4


def test_every_required_variable_is_documented_in_the_example() -> None:
    missing = sorted(_required_variables() - _documented_variables())

    assert missing == [], f"required but undocumented: {missing}"

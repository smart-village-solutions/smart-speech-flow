"""One place that parses and renders the Compose files for tests (#346).

Every interpolating test used to carry its own copy of the required test
environment, so adding one `:?required` variable broke all of them at once.
"""

import base64
import copy
import functools
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_COMPOSE = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE = ROOT / "deploy" / "production" / "docker-compose.production.yml"

# Encoded here rather than written out, so no base64 blob that looks like a real
# key is committed next to the name of one. Secret scanners cannot tell a fake
# from the real thing, and they are right not to try.
TEST_ENCRYPTION_KEY = base64.b64encode(b"test-only-32-byte-key-for-units!").decode()

TEST_ENV = {
    "CLICKHOUSE_DB": "ssf_analytics_test",
    "CLICKHOUSE_USER": "ssf_telemetry_test",
    "CLICKHOUSE_PASSWORD": "test-only-password",
    "KEYCLOAK_DB_NAME": "keycloak_test",
    "KEYCLOAK_DB_USER": "keycloak_test_user",
    "KEYCLOAK_DB_PASSWORD": "test-only-db-password",
    "KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME": "bootstrap_admin",
    "KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD": "test-only-admin-password",
    "KEYCLOAK_HOSTNAME": "auth.test.example",
    "SSF_POSTGRES_DB": "ssf_test",
    "SSF_POSTGRES_USER": "ssf_test_user",
    "SSF_POSTGRES_PASSWORD": "test-only-db-password",
    "SSF_FEEDBACK_APP_PASSWORD": "test-only-app-password",
    "SSF_FEEDBACK_MAINTENANCE_PASSWORD": "test-only-maint-password",
    "SSF_FEEDBACK_READER_PASSWORD": "test-only-reader-password",
    "SSF_FEEDBACK_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
}


@functools.cache
def _parsed(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_compose(path: Path) -> dict:
    """A private copy, so one test's mutation cannot leak into another."""
    return copy.deepcopy(_parsed(path.resolve()))


def render_development_compose(**overrides: str) -> dict:
    """`docker compose config` for the committed development file, parsed.

    Rendered on every call, never cached: Compose lets the shell environment
    override `--env-file`, so a test that changes the environment must see it.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as env_file:
        for name, value in {**TEST_ENV, **overrides}.items():
            env_file.write(f"{name}={value}\n")
    try:
        # -f pins the committed file: a developer's untracked
        # docker-compose.override.yml must not change what these tests see.
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "--env-file",
                env_file.name,
                "config",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(env_file.name)
    return yaml.safe_load(result.stdout)

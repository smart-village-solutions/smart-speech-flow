"""Regression tests for the SSF feedback database Compose contract.

The feedback database is the only store that holds feedback free text in a
recoverable form. These are text and rendering guards, not container guards, so
they run in CI: a host port or a lost dependency would be found here rather than
in production.
"""

import base64
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

# Encoded here rather than written out, so no base64 blob that looks like a real
# key is committed next to the name of one. Secret scanners cannot tell a fake
# from the real thing, and they are right not to try.
TEST_ENCRYPTION_KEY = base64.b64encode(b"test-only-32-byte-key-for-units!").decode()

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "deploy/postgres/migrations/001_feedback.sql"
APPLY_SCRIPT = ROOT / "deploy/postgres/apply.sh"


def _render_services() -> dict:
    """Render Compose with isolated credentials and return every service."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".env") as env_file:
        env_file.write("CLICKHOUSE_DB=ssf_analytics_test\n")
        env_file.write("CLICKHOUSE_USER=ssf_telemetry_test\n")
        env_file.write("CLICKHOUSE_PASSWORD=test-only-password\n")
        env_file.write("KEYCLOAK_DB_NAME=keycloak_test\n")
        env_file.write("KEYCLOAK_DB_USER=keycloak_test_user\n")
        env_file.write("KEYCLOAK_DB_PASSWORD=test-only-db-password\n")
        env_file.write("KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=bootstrap_admin\n")
        env_file.write("KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=test-only-admin-password\n")
        env_file.write("KEYCLOAK_HOSTNAME=auth.test.example\n")
        env_file.write("SSF_POSTGRES_DB=ssf_test\n")
        env_file.write("SSF_POSTGRES_USER=ssf_test_user\n")
        env_file.write("SSF_POSTGRES_PASSWORD=test-only-db-password\n")
        env_file.write("SSF_FEEDBACK_APP_PASSWORD=test-only-app-password\n")
        env_file.write("SSF_FEEDBACK_MAINTENANCE_PASSWORD=test-only-maint-password\n")
        env_file.write(f"SSF_FEEDBACK_ENCRYPTION_KEY={TEST_ENCRYPTION_KEY}\n")
        rendered_env = env_file.name

    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", rendered_env, "config"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(rendered_env)

    return yaml.safe_load(result.stdout)["services"]


def test_feedback_database_is_private_to_the_compose_network() -> None:
    """Fail if the feedback database gains a host port or a public route."""
    database = _render_services()["ssf-postgres"]

    assert database["image"] == "postgres:17.7-alpine"
    assert database["restart"] == "always"
    assert database.get("ports") is None
    assert database.get("labels") is None
    assert database["healthcheck"]


def test_gateway_waits_for_a_healthy_feedback_database() -> None:
    """A gateway that starts first would serve 503s on every submission."""
    gateway = _render_services()["api_gateway"]

    assert gateway["depends_on"]["ssf-postgres"]["condition"] == "service_healthy"


def test_the_encryption_key_has_no_default() -> None:
    """A defaulted key silently encrypts rows nobody can ever decrypt."""
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "SSF_FEEDBACK_ENCRYPTION_KEY:?required" in compose


def test_the_migration_stores_ciphertext_not_readable_text() -> None:
    """The schema must have no column that could hold readable free text."""
    sql = MIGRATION.read_text()

    assert "improvements_ciphertext" in sql
    assert "BYTEA" in sql
    assert "improvements TEXT" not in sql


def test_the_migration_enables_row_level_security() -> None:
    """Enabling this later would need a migration and an access review."""
    sql = MIGRATION.read_text()

    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "feedback_tenant_isolation" in sql


def test_the_migration_is_rerunnable() -> None:
    """apply.sh runs on every container start; it must be idempotent."""
    sql = MIGRATION.read_text()

    assert sql.count("CREATE TABLE IF NOT EXISTS") == 3
    assert "CREATE TABLE feedback (" not in sql


def test_the_apply_script_is_executable() -> None:
    """A non-executable entrypoint script is skipped silently by Postgres."""
    assert APPLY_SCRIPT.exists()
    assert os.access(APPLY_SCRIPT, os.X_OK)


def test_the_production_stack_ships_the_same_database() -> None:
    """A dev-only feedback store loses every production submission."""
    production = (ROOT / "deploy/production/docker-compose.production.yml").read_text()

    assert "ssf-postgres:" in production
    assert "ssf-postgres-data" in production


# --- The roles that make the tenant policy real -----------------------------
#
# `ENABLE ROW LEVEL SECURITY` in 001 is inert for a superuser, and the owner
# the image creates from POSTGRES_USER is one. Proven against
# postgres:17.7-alpine: bound to one tenant, the owner still saw both tenants'
# rows. These pin the two things that fix it -- a restricted request role, and a
# separate role for the deployment-wide passes.

ROLES_MIGRATION = ROOT / "deploy/postgres/migrations/002_feedback_roles.sql"


def test_the_request_path_does_not_connect_as_the_database_owner() -> None:
    """The whole defect in one assertion: a superuser bypasses every policy."""
    environment = _render_services()["api_gateway"]["environment"]

    dsn = environment["SSF_FEEDBACK_DATABASE_URL"]

    assert dsn.startswith("postgresql://ssf_feedback_app:"), dsn


def test_the_maintenance_passes_connect_as_their_own_role() -> None:
    environment = _render_services()["api_gateway"]["environment"]

    dsn = environment["SSF_FEEDBACK_MAINTENANCE_DATABASE_URL"]

    assert dsn.startswith("postgresql://ssf_feedback_maintenance:"), dsn


def test_the_two_roles_do_not_share_a_password() -> None:
    """One password for both would make the privilege split cosmetic."""
    environment = _render_services()["api_gateway"]["environment"]

    assert (
        environment["SSF_FEEDBACK_DATABASE_URL"]
        != environment["SSF_FEEDBACK_MAINTENANCE_DATABASE_URL"]
    )


def test_the_database_receives_both_role_passwords() -> None:
    """apply.sh needs them at init or migration 002 cannot create the roles."""
    environment = _render_services()["ssf-postgres"]["environment"]

    assert "SSF_FEEDBACK_APP_PASSWORD" in environment
    assert "SSF_FEEDBACK_MAINTENANCE_PASSWORD" in environment


def test_the_request_role_cannot_delete_feedback() -> None:
    """Retention must not be reachable from an HTTP request."""
    sql = ROLES_MIGRATION.read_text(encoding="utf-8")

    grant = next(line for line in sql.splitlines() if "ON feedback TO ssf_feedback_app" in line)

    assert "DELETE" not in grant, grant


def test_the_request_role_is_not_exempt_from_the_policy() -> None:
    sql = ROLES_MIGRATION.read_text(encoding="utf-8")

    assert "NOBYPASSRLS" in sql
    assert "ssf_feedback_app" in sql


def test_the_maintenance_role_is_exempt_because_it_has_no_tenant() -> None:
    """Both passes are deployment-wide; bound to one tenant they would do nothing."""
    sql = ROLES_MIGRATION.read_text(encoding="utf-8")

    maintenance = sql[sql.index("ALTER ROLE ssf_feedback_maintenance") :]
    maintenance = maintenance[: maintenance.index(";")]

    assert "BYPASSRLS" in maintenance
    assert "NOSUPERUSER" in maintenance


def test_neither_application_role_is_a_superuser() -> None:
    sql = ROLES_MIGRATION.read_text(encoding="utf-8")

    assert sql.count("NOSUPERUSER") == 2


def test_the_roles_migration_carries_no_literal_password() -> None:
    """Passwords arrive as psql variables; a literal here would be committed."""
    sql = ROLES_MIGRATION.read_text(encoding="utf-8")

    assert ":'app_password'" in sql
    assert ":'maintenance_password'" in sql
    assert "PASSWORD '" not in sql

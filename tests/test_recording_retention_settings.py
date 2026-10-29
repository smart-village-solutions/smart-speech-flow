"""The retention worker's settings: one site, one retention pair, no secret in any error."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.api_gateway.recording.retention.settings import WorkerSettings
from services.api_gateway.recording.storage.settings import ArchiveConfigError

SECRET = "s3cr3t-" + "value"
DATABASE_SECRET = "db-" + "password/+=@"


@pytest.fixture
def environment(tmp_path: Path) -> dict[str, str]:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "s3-retention.json").write_text(
        json.dumps({"access_key_id": "retention", "secret_access_key": SECRET})
    )
    (secrets / "database-password").write_text(DATABASE_SECRET + "\n")
    return {
        "SSF_RETENTION_SITE": "replica",
        "SSF_RETENTION_ENDPOINT": "http://seaweedfs:8333",
        "SSF_RETENTION_DATABASE_URL": "postgresql://ssf_recording_replica@db:5432/ssf_recording",
        "SSF_RETENTION_SECRETS_DIR": str(secrets),
        "SSF_RETENTION_STATE_DIR": str(tmp_path / "state"),
    }


def test_valid_settings_load_with_their_defaults(environment):
    settings = WorkerSettings.from_environment(environment)
    assert settings.site == "replica"
    assert settings.endpoint == "http://seaweedfs:8333"
    assert settings.credentials.access_key_id == "retention"
    assert settings.credentials.secret_access_key == SECRET
    assert settings.database_password == DATABASE_SECRET
    assert settings.interval_seconds == 300.0
    assert settings.sweep_hours == 24.0
    assert SECRET not in repr(settings) and DATABASE_SECRET not in repr(settings)


def test_the_intervals_can_be_set(environment):
    settings = WorkerSettings.from_environment(
        environment | {"SSF_RETENTION_INTERVAL_SECONDS": "60", "SSF_RETENTION_SWEEP_HOURS": "6"}
    )
    assert (settings.interval_seconds, settings.sweep_hours) == (60.0, 6.0)


def _write(environment, name: str, text: str) -> None:
    (Path(environment["SSF_RETENTION_SECRETS_DIR"]) / name).write_text(text)


@pytest.mark.parametrize(
    "change",
    [
        {"SSF_RETENTION_SITE": "both"},
        {"SSF_RETENTION_SITE": ""},
        {"SSF_RETENTION_ENDPOINT": ""},
        {"SSF_RETENTION_DATABASE_URL": " "},
        {"SSF_RETENTION_INTERVAL_SECONDS": "9.9"},
        {"SSF_RETENTION_INTERVAL_SECONDS": "often"},
        {"SSF_RETENTION_SWEEP_HOURS": "0"},
        {"SSF_RETENTION_SECRETS_DIR": "/nonexistent/ssf-retention"},
    ],
)
def test_unusable_settings_are_refused(environment, change):
    with pytest.raises(ArchiveConfigError):
        WorkerSettings.from_environment(environment | change)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("s3-retention.json", "{" + SECRET),
        ("s3-retention.json", json.dumps(["retention", SECRET])),
        ("s3-retention.json", json.dumps({"access_key_id": "retention"})),
        (
            "s3-retention.json",
            json.dumps({"access_key_id": "re\ttention", "secret_access_key": SECRET}),
        ),
        ("database-password", "\n"),
        ("database-password", "pass\x00word"),
    ],
)
def test_unusable_secrets_are_refused_without_naming_them(environment, name, text):
    _write(environment, name, text)
    with pytest.raises(ArchiveConfigError) as refused:
        WorkerSettings.from_environment(environment)
    assert SECRET not in str(refused.value)
    assert DATABASE_SECRET not in str(refused.value)

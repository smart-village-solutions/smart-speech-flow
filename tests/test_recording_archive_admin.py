"""Archive configuration and the operator commands."""

from __future__ import annotations

import json

import pytest

from services.api_gateway.recording.storage import admin
from services.api_gateway.recording.storage.archive import ArchiveRefusedError, bucket_for
from services.api_gateway.recording.storage.s3 import S3Response
from services.api_gateway.recording.storage.settings import (
    ARCHIVE_ENDPOINT_ENV,
    ARCHIVE_WRITERS_FILE_ENV,
    ArchiveConfigError,
    ArchiveSettings,
    load_writers,
)
from services.api_gateway.recording.storage.sigv4 import Credentials
from services.api_gateway.session_pseudonym import tenant_ref

TENANT = "tenant-kassel"


@pytest.mark.parametrize(("hours", "days"), [(1, 2), (24, 2), (25, 3), (24 * 365, 366)])
def test_the_bucket_default_covers_the_retention_plus_a_day(hours, days):
    assert admin.default_retention_days(hours) == days


def test_a_retention_below_an_hour_is_refused():
    with pytest.raises(ValueError):
        admin.default_retention_days(0)


ENDPOINT = "https" + "://archive.test"


class Answers:
    """A transport that answers each request in turn."""

    def __init__(self, *responses: S3Response) -> None:
        self.responses = list(responses)
        self.sent: list[tuple[str, str]] = []

    async def send(self, method, url, headers, body, timeout_seconds) -> S3Response:
        self.sent.append((method, url))
        return self.responses.pop(0)


def _ok(body: bytes = b"") -> S3Response:
    return S3Response(200, {}, body)


def _lock(days: int) -> S3Response:
    return _ok(
        b"<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled><Rule>"
        b"<DefaultRetention><Mode>COMPLIANCE</Mode><Days>%d</Days></DefaultRetention>"
        b"</Rule></ObjectLockConfiguration>" % days
    )


NO_RULE = _ok(
    b"<ObjectLockConfiguration><ObjectLockEnabled>Enabled</ObjectLockEnabled>"
    b"</ObjectLockConfiguration>"
)


def test_a_new_writer_is_confined_to_its_tenant_bucket_by_a_policy(capsys):
    assert admin.main(["new-writer", TENANT]) == 0
    printed = json.loads(capsys.readouterr().out)
    bucket = bucket_for(TENANT)
    name = f"writer-{tenant_ref(TENANT)}"
    identity = printed["seaweedfs_identity"]
    assert identity["name"] == name
    assert identity["policyNames"] == [name]
    assert "actions" not in identity  # legacy Write would also allow lifecycle and CORS changes
    policy = printed["seaweedfs_policy"]
    assert policy["name"] == name
    statements = policy["document"]["Statement"]
    assert {(tuple(s["Action"]), tuple(s["Resource"])) for s in statements} == {
        (("s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"), (f"arn:aws:s3:::{bucket}/*",)),
        (("s3:ListBucket", "s3:GetBucketObjectLockConfiguration"), (f"arn:aws:s3:::{bucket}",)),
    }
    assert {s["Effect"] for s in statements} == {"Allow"}
    credential = identity["credentials"][0]
    assert printed["gateway_writer"][TENANT] == {
        "access_key_id": credential["accessKey"],
        "secret_access_key": credential["secretKey"],
    }
    assert len(credential["secretKey"]) >= 40


@pytest.mark.parametrize("tenant_id", ["", "tenant kassel\u00e4", "tenant\nkassel"])
def test_a_new_writer_needs_a_tenant_id_the_gateway_accepts(tenant_id, capsys):
    assert admin.main(["new-writer", tenant_id]) == 1
    assert capsys.readouterr().out == ""


async def test_create_bucket_reports_the_default_it_replaced(monkeypatch):
    monkeypatch.setenv(admin.ADMIN_KEY_ENV, "admin-key")
    monkeypatch.setenv(admin.ADMIN_SECRET_ENV, "admin-secret")
    monkeypatch.setenv(ARCHIVE_ENDPOINT_ENV, ENDPOINT)
    enabled = _ok(b"<ObjectLockEnabled>Enabled</ObjectLockEnabled>")
    answers = Answers(_ok(), enabled, _lock(31), _ok(), _lock(366))
    line = await admin.create_bucket(TENANT, 24 * 365, transport=answers)
    assert line == (
        f"{bucket_for(TENANT)}: object lock on, default compliance retention 366 days (was 31)"
    )
    assert answers.sent[3][0] == "PUT" and answers.sent[3][1].endswith("?object-lock=")


def _settings(*tenants: str) -> ArchiveSettings:
    return ArchiveSettings(ENDPOINT, {tenant: Credentials("k", "s") for tenant in tenants})


async def test_check_reports_each_tenant_and_a_bucket_without_default_retention():
    answers = Answers(_ok(), _lock(31), _ok(), NO_RULE)
    lines = await admin.check(_settings("tenant-a", "tenant-b"), transport=answers)
    assert lines == [
        f"ok    tenant-a {bucket_for('tenant-a')} 31 days",
        f"FAIL  tenant-b {bucket_for('tenant-b')} no_default_retention",
    ]


def test_check_with_no_writer_fails(monkeypatch, tmp_path, capsys):
    path = tmp_path / "archive-writers.json"
    path.write_text("{}")
    monkeypatch.setenv(ARCHIVE_ENDPOINT_ENV, ENDPOINT)
    monkeypatch.setenv(ARCHIVE_WRITERS_FILE_ENV, str(path))
    assert admin.main(["check"]) == 1
    assert "no tenant" in capsys.readouterr().err


def test_create_bucket_needs_the_admin_credential_for_that_run(monkeypatch, capsys):
    monkeypatch.delenv(admin.ADMIN_KEY_ENV, raising=False)
    monkeypatch.setenv(ARCHIVE_ENDPOINT_ENV, "https" + "://archive.test")
    assert admin.main(["create-bucket", TENANT, "--retention-hours", "24"]) == 1
    assert admin.ADMIN_KEY_ENV in capsys.readouterr().err


def test_settings_are_off_without_an_endpoint(monkeypatch):
    monkeypatch.delenv(ARCHIVE_ENDPOINT_ENV, raising=False)
    assert ArchiveSettings.from_environment() is None


def test_writers_load_per_tenant_and_unknown_tenants_get_no_credential(tmp_path, monkeypatch):
    path = tmp_path / "archive-writers.json"
    path.write_text(json.dumps({TENANT: {"access_key_id": "k", "secret_access_key": "s"}}))
    monkeypatch.setenv(ARCHIVE_ENDPOINT_ENV, "https" + "://archive.test")
    monkeypatch.setenv(ARCHIVE_WRITERS_FILE_ENV, str(path))
    settings = ArchiveSettings.from_environment()
    assert settings.credentials_for(TENANT).access_key_id == "k"
    with pytest.raises(ArchiveRefusedError) as refused:
        settings.credentials_for("tenant-other")
    assert refused.value.code == "no_writer_credential"


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", json.dumps({TENANT: {"access_key_id": "k"}}), json.dumps({TENANT: "k"})],
)
def test_a_malformed_writers_file_is_refused_without_echoing_it(tmp_path, content):
    path = tmp_path / "archive-writers.json"
    path.write_text(content)
    with pytest.raises(ArchiveConfigError) as refused:
        load_writers(path)
    assert content not in str(refused.value)


def test_a_missing_writers_file_is_refused(tmp_path):
    with pytest.raises(ArchiveConfigError):
        load_writers(tmp_path / "absent.json")

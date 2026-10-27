"""deploy/archive-storage/merge_writer.py: onboarding a writer without a secret on screen."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

from services.api_gateway.recording.storage.admin import new_writer

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "archive-storage" / "merge_writer.py"
spec = importlib.util.spec_from_file_location("merge_writer", SCRIPT)
merge_writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_writer)

OWNER = f"{os.getuid()}:{os.getgid()}"


@pytest.fixture
def onboarding(tmp_path):
    new = tmp_path / "new-writer.json"
    new.write_text(json.dumps(new_writer("tenant-kassel")))
    s3 = tmp_path / "s3.json"
    s3.write_text(
        json.dumps(
            {
                "identities": [{"name": "admin", "actions": ["Admin"]}],
                "policies": [{"name": "retention", "document": {}}],
            }
        )
    )
    s3.chmod(0o400)
    return new, s3, tmp_path / "archive-writers.json"


def test_the_identity_and_its_policy_join_s3_json_once(onboarding, capsys):
    new, s3, _ = onboarding
    written = json.loads(new.read_text())
    for _ in range(2):
        assert merge_writer.main(["seaweedfs", str(new), str(s3), "--owner", OWNER]) == 0
    merged = json.loads(s3.read_text())
    assert [i["name"] for i in merged["identities"]] == [
        "admin",
        written["seaweedfs_identity"]["name"],
    ]
    assert merged["policies"][1] == written["seaweedfs_policy"]
    assert stat.S_IMODE(s3.stat().st_mode) == 0o400
    secret = written["seaweedfs_identity"]["credentials"][0]["secretKey"]
    assert secret not in capsys.readouterr().out


def test_the_gateway_entry_joins_a_new_or_existing_writers_file(onboarding, capsys):
    new, _, writers = onboarding
    assert merge_writer.main(["gateway", str(new), str(writers), "--owner", OWNER]) == 0
    other = {"tenant-other": {"access_key_id": "k", "secret_access_key": "s"}}
    writers.chmod(0o600)
    writers.write_text(json.dumps(json.loads(writers.read_text()) | other))
    assert merge_writer.main(["gateway", str(new), str(writers), "--owner", OWNER]) == 0
    assert sorted(json.loads(writers.read_text())) == ["tenant-kassel", "tenant-other"]
    assert stat.S_IMODE(writers.stat().st_mode) == 0o400
    secret = json.loads(new.read_text())["gateway_writer"]["tenant-kassel"]["secret_access_key"]
    assert secret not in capsys.readouterr().out


def test_a_broken_target_is_refused_and_left_alone(onboarding, capsys):
    new, s3, _ = onboarding
    s3.chmod(0o600)
    s3.write_text('{"identities": [')
    assert merge_writer.main(["seaweedfs", str(new), str(s3), "--owner", OWNER]) == 1
    assert s3.read_text() == '{"identities": ['
    assert "not valid JSON" in capsys.readouterr().err

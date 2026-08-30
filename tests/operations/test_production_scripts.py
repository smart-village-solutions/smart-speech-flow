import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_script(*arguments, environment=None):
    env = os.environ.copy()
    if environment:
        env.update(environment)
    return subprocess.run(
        [str(ROOT / arguments[0]), *arguments[1:]],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_health_script_rejects_invalid_timeout():
    result = run_script(
        "scripts/production-health-check.sh", "--timeout-seconds", "zero"
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr


def test_health_script_reports_missing_gpu(tmp_path):
    fake_nvidia_smi = tmp_path / "nvidia-smi"
    fake_nvidia_smi.write_text("#!/usr/bin/env bash\necho 'driver unavailable' >&2\nexit 1\n")
    fake_nvidia_smi.chmod(0o755)

    result = run_script(
        "scripts/production-health-check.sh",
        "--timeout-seconds",
        "1",
        environment={"PATH": f"{tmp_path}:{os.environ['PATH']}"},
    )

    assert result.returncode == 1
    assert "GPU" in result.stderr


def test_backup_verifier_rejects_missing_required_artifact(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "manifest.json").write_text('{"required": ["postgres.sql.gz"]}')

    result = run_script("scripts/verify-production-backup.sh", str(backup))

    assert result.returncode == 1
    assert "postgres.sql.gz" in result.stderr


def test_backup_verifier_rejects_latest_symlink(tmp_path):
    backup = tmp_path / "20260830_000000"
    backup.mkdir()
    latest = tmp_path / "latest"
    latest.symlink_to(backup, target_is_directory=True)

    result = run_script("scripts/verify-production-backup.sh", str(latest))

    assert result.returncode == 2
    assert "concrete backup directory" in result.stderr


def test_backup_verifier_rejects_empty_required_artifact(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "redis.rdb").touch()
    (backup / "manifest.json").write_text('{"required": ["redis.rdb"]}')

    result = run_script("scripts/verify-production-backup.sh", str(backup))

    assert result.returncode == 1
    assert "empty" in result.stderr


def test_clickhouse_backup_uses_the_configured_allowed_backup_path():
    script = (ROOT / "scripts/backup-production.sh").read_text()

    assert 'clickhouse_backup_filename="ssf-clickhouse-${timestamp}.zip"' in script
    assert "File('${clickhouse_backup_filename}')" in script
    assert "/var/lib/clickhouse/backups/${clickhouse_backup_filename}" in script
    assert 'rm -f "/var/lib/clickhouse/backups/${clickhouse_backup_filename}"' in script
    assert "/tmp/ssf-clickhouse-backup.zip" not in script

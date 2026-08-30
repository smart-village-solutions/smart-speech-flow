import os
import subprocess
import json
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


def test_backup_records_ollama_models_without_archiving_model_volume(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
arguments="$*"
if [[ "$arguments" == *"exec -T keycloak-postgres"* ]]; then
  printf 'postgres dump\\n'
elif [[ "$arguments" == *"exec -T redis cat /tmp/ssf-backup.rdb"* ]]; then
  printf 'redis dump\\n'
elif [[ "$arguments" == *"exec -T clickhouse cat /var/lib/clickhouse/backups/"* ]]; then
  printf 'clickhouse dump\\n'
elif [[ "$arguments" == *"exec -T ollama ollama list"* ]]; then
  printf 'NAME ID SIZE MODIFIED\\ngpt-oss:20b abc 13 GB now\\n'
elif [[ "${1:-}" == "run" ]]; then
  backup_mount=''
  for argument in "$@"; do
    if [[ "$argument" == *":/backup" ]]; then
      backup_mount="${argument%:/backup}"
    fi
  done
  archive="${arguments##*/backup/volumes/}"
  archive="${archive%% *}"
  mkdir -p "$backup_mount/volumes"
  /usr/bin/tar -C /tmp -czf "$backup_mount/volumes/$archive" --files-from /dev/null
fi
"""
    )
    fake_docker.chmod(0o755)
    fake_tar = fake_bin / "tar"
    fake_tar.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
for ((index = 1; index <= $#; index++)); do
  if [[ "${!index}" == "-czf" ]]; then
    next_index=$((index + 1))
    /usr/bin/tar -C /tmp -czf "${!next_index}" --files-from /dev/null
    exit 0
  fi
done
exec /usr/bin/tar "$@"
"""
    )
    fake_tar.chmod(0o755)
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/usr/bin/env bash\nprintf 'test-revision\\n'\n")
    fake_git.chmod(0o755)

    project_root = tmp_path / "project"
    for directory in ("deploy/production", "monitoring", "letsencrypt", "models"):
        (project_root / directory).mkdir(parents=True, exist_ok=True)
    (project_root / ".env").write_text("CLICKHOUSE_DB=ssf\n")

    backup_root = tmp_path / "backups"
    result = run_script(
        "scripts/backup-production.sh",
        environment={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_DOCKER_LOG": str(docker_log),
            "SSF_BACKUP_ROOT": str(backup_root),
            "SSF_CLICKHOUSE_DATABASE": "ssf",
            "SSF_PROJECT_ROOT": str(project_root),
        },
    )

    assert result.returncode == 0, result.stderr
    backup = next(path for path in backup_root.iterdir() if path.is_dir())
    manifest = json.loads((backup / "manifest.json").read_text())
    assert "ollama-models.txt" in manifest["required"]
    assert "volumes/ssf-backend_ollama-data.tar.gz" not in manifest["required"]
    assert "gpt-oss:20b" in (backup / "ollama-models.txt").read_text()
    assert "ssf-backend_ollama-data" not in docker_log.read_text()

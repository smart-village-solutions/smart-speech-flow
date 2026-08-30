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

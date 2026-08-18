"""Regression tests for frontend configuration embedded by the container build."""

from pathlib import Path
import os
import subprocess
import uuid

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPOSITORY_ROOT / "services" / "frontend"
API_BASE_URL = "https://ssf.smart-village.solutions"
WS_BASE_URL = "wss://ssf.smart-village.solutions"


def _docker_build(tag: str, *build_args: str) -> subprocess.CompletedProcess[str]:
    command = ["docker", "build", "--quiet", "--tag", tag]
    for build_arg in build_args:
        command.extend(("--build-arg", build_arg))
    command.append(str(FRONTEND_ROOT))
    return subprocess.run(command, capture_output=True, check=False, text=True)


def _compose_build(project_name: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["FRONTEND_DEMO_PASSWORD"] = "container-build-test-password"
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "build",
            "--quiet",
            "frontend",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


def _remove_image(tag: str) -> None:
    subprocess.run(
        ["docker", "image", "rm", "--force", tag],
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.integration
@pytest.mark.slow
def test_frontend_container_embeds_production_service_urls():
    """Build arguments must reach Vite rather than leaving localhost in the SPA."""
    project_name = f"ssf-frontend-config-test-{uuid.uuid4().hex}"
    tag = f"{project_name}-frontend"
    try:
        result = _compose_build(project_name)
        assert result.returncode == 0, result.stderr

        bundle_check = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                tag,
                "-c",
                (
                    "grep -R -q 'https://ssf.smart-village.solutions' /usr/share/nginx/html/assets "
                    "&& grep -R -q 'wss://ssf.smart-village.solutions' /usr/share/nginx/html/assets "
                    "&& grep -R -q 'container-build-test-password' /usr/share/nginx/html/assets "
                    "&& ! grep -R -q 'localhost:8000' /usr/share/nginx/html/assets"
                ),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        assert bundle_check.returncode == 0, bundle_check.stderr
    finally:
        _remove_image(tag)


@pytest.mark.integration
@pytest.mark.slow
def test_frontend_container_rejects_missing_production_service_urls():
    """A production image must not silently fall back to browser localhost."""
    tag = f"ssf-frontend-config-test:{uuid.uuid4().hex}"
    try:
        result = _docker_build(tag, "VITE_APP_PASSWORD=test-password")
        assert result.returncode != 0
        assert "VITE_API_BASE_URL and VITE_WS_BASE_URL must be set" in result.stderr
    finally:
        _remove_image(tag)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("api_base_url", "ws_base_url", "expected_error"),
    (
        (
            "http://LOCALHOST:8000",
            WS_BASE_URL,
            "VITE_API_BASE_URL must not target localhost",
        ),
        (
            API_BASE_URL,
            "ws://LocalHost:8000",
            "VITE_WS_BASE_URL must not target localhost",
        ),
    ),
)
def test_frontend_container_rejects_case_insensitive_localhost_urls(
    api_base_url: str, ws_base_url: str, expected_error: str
):
    """Hostname casing must not bypass the production localhost safeguard."""
    tag = f"ssf-frontend-config-test:{uuid.uuid4().hex}"
    try:
        result = _docker_build(
            tag,
            f"VITE_API_BASE_URL={api_base_url}",
            f"VITE_WS_BASE_URL={ws_base_url}",
            "VITE_APP_PASSWORD=test-password",
        )
        assert result.returncode != 0
        assert expected_error in result.stderr
    finally:
        _remove_image(tag)

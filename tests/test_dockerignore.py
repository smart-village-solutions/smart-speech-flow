"""The Docker build context leaves out what containers write back into the tree."""

from pathlib import Path

DOCKERIGNORE = Path(__file__).resolve().parents[1] / ".dockerignore"


def test_grafana_state_is_not_sent_to_the_build():
    """Grafana writes monitoring/grafana as root; a build that sends it fails.

    Its csv/, pdf/ and png/ are mode 0700 for the container's user, so every
    image built from the repository root stopped with "permission denied".
    """
    assert "monitoring/grafana/" in DOCKERIGNORE.read_text().splitlines()

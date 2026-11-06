"""Record the fingerprint of a built frontend image at deploy time (#620, spec §5)."""

import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

HTML_ROOT = "/usr/share/nginx/html"
INCLUDE = "/etc/nginx/snippets/security-headers.conf"
_POLICY = re.compile(
    r'^[ \t]*add_header[ \t]+(Content-Security-Policy(?:-Report-Only)?)[ \t]+"([^"]*)"[ \t]+always;',
    re.MULTILINE,
)


class RecordError(Exception):
    """The image or the request cannot be recorded."""


Copier = Callable[[str, Path], tuple[Path, str]]


def hash_tree(root: Path) -> dict[str, str]:
    """Map every file below root to its sha256."""
    files = sorted(path for path in root.rglob("*") if path.is_file())
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def parse_policy(include: str) -> tuple[str, str]:
    """Return the policy header's name and value from the nginx include."""
    found = _POLICY.findall(include)
    if len(found) != 1:
        raise RecordError(f"the include must hold exactly one policy header, found {len(found)}")
    return found[0]


def version(html: Path, include: str, image: str, commit: str, recorded_at: str) -> dict:
    """Describe what this image serves."""
    files = hash_tree(html)
    if "index.html" not in files:
        raise RecordError(f"{image} serves no index.html")
    header, policy = parse_policy(include)
    return {
        "image": image,
        "commit": commit,
        "recordedAt": recorded_at,
        "cspHeader": header,
        "csp": policy,
        "files": files,
    }


def _served(entry: dict) -> tuple:
    return entry["cspHeader"], entry["csp"], entry["files"]


def updated(existing: dict | None, new: dict) -> dict:
    """Make new the current version; an unchanged site keeps the file as it is."""
    current = (existing or {}).get("current")
    if current and _served(current) == _served(new):
        return existing
    return {"schema": 1, "current": new, "previous": current}


def copy_out(image: str, workdir: Path) -> tuple[Path, str]:
    """Copy the served files and the header include out of a container that never starts."""
    created = subprocess.run(
        ["docker", "create", image], check=True, capture_output=True, text=True
    )
    container = created.stdout.strip()
    try:
        for source, target in ((HTML_ROOT, "html"), (INCLUDE, "security-headers.conf")):
            subprocess.run(
                ["docker", "cp", f"{container}:{source}", str(workdir / target)],
                check=True,
                capture_output=True,
            )
    finally:
        subprocess.run(["docker", "rm", container], check=True, capture_output=True)
    return workdir / "html", (workdir / "security-headers.conf").read_text(encoding="utf-8")


def record(
    image: str, commit: str, manifest_path: Path, recorded_at: str, copy: Copier = copy_out
) -> dict:
    """Return the fingerprint file with this image as its current version."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RecordError("the commit must be the full 40-character sha")
    existing = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    )
    with tempfile.TemporaryDirectory() as workdir:
        html, include = copy(image, Path(workdir))
        return updated(existing, version(html, include, image, commit, recorded_at))


def dump(data: dict) -> str:
    """The file text: sorted keys, two-space indent, UTF-8, final newline."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

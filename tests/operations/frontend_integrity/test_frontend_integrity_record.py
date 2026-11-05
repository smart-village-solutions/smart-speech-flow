"""The deploy records what the image serves, keeping the version before it (#620, spec §5)."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.frontend_integrity.record import RecordError, dump, parse_policy, record

COMMIT = "0123456789abcdef0123456789abcdef01234567"
NEXT_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"
INCLUDE = (
    "add_header Content-Security-Policy-Report-Only \"default-src 'none'\" always;\n"
    'add_header X-Frame-Options "DENY" always;\n'
)


def _copier(files: dict[str, str], include: str = INCLUDE):
    def copy(image: str, workdir: Path) -> tuple[Path, str]:
        for name, text in files.items():
            target = workdir / "html" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return workdir / "html", include

    return copy


SITE = {"index.html": "<html></html>\n", "assets/index-a.js": "console.log(1);\n"}


def test_a_first_record_has_no_previous_version(tmp_path):
    data = record("img:a", COMMIT, tmp_path / "m.json", "2026-11-05T10:00:00Z", _copier(SITE))

    assert data["schema"] == 1
    assert data["previous"] is None
    assert data["current"] == {
        "image": "img:a",
        "commit": COMMIT,
        "recordedAt": "2026-11-05T10:00:00Z",
        "cspHeader": "Content-Security-Policy-Report-Only",
        "csp": "default-src 'none'",
        "files": {
            "assets/index-a.js": hashlib.sha256(b"console.log(1);\n").hexdigest(),
            "index.html": hashlib.sha256(b"<html></html>\n").hexdigest(),
        },
    }


def test_a_new_image_moves_the_current_version_to_previous(tmp_path):
    manifest = tmp_path / "m.json"
    first = record("img:a", COMMIT, manifest, "2026-11-05T10:00:00Z", _copier(SITE))
    manifest.write_text(dump(first))

    second = record(
        "img:b",
        NEXT_COMMIT,
        manifest,
        "2026-11-06T10:00:00Z",
        _copier({**SITE, "index.html": "<p>"}),
    )

    assert second["previous"] == first["current"]
    assert second["current"]["commit"] == NEXT_COMMIT


def test_recording_the_same_content_again_changes_nothing(tmp_path):
    manifest = tmp_path / "m.json"
    first = record("img:a", COMMIT, manifest, "2026-11-05T10:00:00Z", _copier(SITE))
    manifest.write_text(dump(first))

    assert record("img:a2", COMMIT, manifest, "2026-11-07T10:00:00Z", _copier(SITE)) == first


@pytest.mark.parametrize(
    "include",
    [
        'add_header X-Frame-Options "DENY" always;\n',
        INCLUDE + INCLUDE.splitlines()[0].replace("-Report-Only", "") + "\n",
    ],
)
def test_the_include_must_hold_exactly_one_policy(include):
    with pytest.raises(RecordError):
        parse_policy(include)


def test_an_image_without_index_html_is_refused(tmp_path):
    with pytest.raises(RecordError):
        record("img:a", COMMIT, tmp_path / "m.json", "t", _copier({"assets/a.js": "x"}))


def test_only_a_full_commit_is_accepted(tmp_path):
    with pytest.raises(RecordError):
        record("img:a", COMMIT[:7], tmp_path / "m.json", "t", _copier(SITE))


def test_the_file_text_is_canonical():
    text = dump({"b": 1, "a": "ü"})

    assert text == '{\n  "a": "ü",\n  "b": 1\n}\n'
    assert json.loads(text) == {"a": "ü", "b": 1}

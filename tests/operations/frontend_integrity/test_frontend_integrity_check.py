"""Every change to what a tablet would run is a mismatch (#620, spec §6 and §7)."""

import shutil

from scripts.frontend_integrity.check import DEEP_LINK, check, confirmed
from scripts.frontend_integrity.site import fetch
from tests.operations.frontend_integrity.frontend_integrity_fakes import (
    POLICY,
    POLICY_HEADER,
    FrontendServer,
    SiteBehaviour,
    closed_port_url,
    fingerprint,
    write_site,
)


def _manifest(current: dict, previous: dict | None = None) -> dict:
    return {"schema": 1, "current": current, "previous": previous}


def _verdict(behaviour: SiteBehaviour, manifest: dict):
    with FrontendServer(behaviour) as base:
        return check(base, manifest)


def test_the_untouched_site_matches_the_current_version(tmp_path):
    root = write_site(tmp_path / "site")

    verdict = _verdict(SiteBehaviour(root), _manifest(fingerprint(root)))

    assert (verdict.outcome, verdict.matched, verdict.findings) == ("match", "current", ())


def test_the_previous_version_still_matches(tmp_path):
    served = write_site(tmp_path / "old")
    newer = write_site(tmp_path / "new")
    (newer / "index.html").write_text("<html>new</html>\n")

    verdict = _verdict(SiteBehaviour(served), _manifest(fingerprint(newer), fingerprint(served)))

    assert (verdict.outcome, verdict.matched) == ("match", "previous")


def test_one_changed_byte_in_a_chunk_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")
    manifest = _manifest(fingerprint(root))
    with (root / "assets" / "lazy-b.js").open("a") as chunk:
        chunk.write(" ")

    verdict = _verdict(SiteBehaviour(root), manifest)

    assert verdict.outcome == "mismatch"
    assert verdict.findings == ("assets/lazy-b.js differs (HTTP 200)",)


def test_an_extra_script_in_index_html_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")
    manifest = _manifest(fingerprint(root))
    index = root / "index.html"
    index.write_text(
        index.read_text().replace("</head>", '<script src="/assets/x.js"></script></head>')
    )

    assert "index.html differs (HTTP 200)" in _verdict(SiteBehaviour(root), manifest).findings


def test_a_deep_link_serving_other_bytes_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")

    verdict = _verdict(
        SiteBehaviour(root, deep_link_body=b"<html>other</html>"), _manifest(fingerprint(root))
    )

    assert verdict.findings == (f"{DEEP_LINK} serves a different index.html",)


def test_a_weakened_policy_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")
    behaviour = SiteBehaviour(root, policy_headers={POLICY_HEADER: "default-src *"})

    verdict = _verdict(behaviour, _manifest(fingerprint(root)))

    assert verdict.outcome == "mismatch"
    assert verdict.findings[0].startswith("the policy header on / differs")


def test_a_deep_link_without_the_policy_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")

    verdict = _verdict(SiteBehaviour(root, deep_link_headers={}), _manifest(fingerprint(root)))

    assert verdict.findings == (f"the policy header on {DEEP_LINK} differs: []",)


def test_a_missing_policy_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")

    assert (
        _verdict(SiteBehaviour(root, policy_headers={}), _manifest(fingerprint(root))).outcome
        == "mismatch"
    )


def test_report_only_where_enforcement_was_recorded_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")
    behaviour = SiteBehaviour(root, policy_headers={"Content-Security-Policy-Report-Only": POLICY})

    assert _verdict(behaviour, _manifest(fingerprint(root))).outcome == "mismatch"


def test_a_missing_file_is_a_mismatch(tmp_path):
    root = write_site(tmp_path / "site")
    manifest = _manifest(fingerprint(root))
    shutil.rmtree(root / "assets")

    verdict = _verdict(SiteBehaviour(root), manifest)

    assert "assets/index-a.js differs (HTTP 404)" in verdict.findings


def test_without_a_recorded_version_nothing_matches(tmp_path):
    root = write_site(tmp_path / "site")

    verdict = _verdict(SiteBehaviour(root), {"schema": 1, "current": None, "previous": None})

    assert (verdict.outcome, verdict.findings) == ("mismatch", ("no version is recorded",))


def test_a_closed_port_is_unreachable(tmp_path):
    root = write_site(tmp_path / "site")

    verdict = check(
        closed_port_url(),
        _manifest(fingerprint(root)),
        lambda url: fetch(url, wait=lambda _s: None),
    )

    assert verdict.outcome == "unreachable"


def test_a_difference_that_clears_before_the_second_look_is_a_match(tmp_path):
    root = write_site(tmp_path / "site")
    behaviour = SiteBehaviour(root, policy_headers={})
    waits = []

    def deploy_finishes(seconds: float) -> None:
        waits.append(seconds)
        behaviour.policy_headers = {POLICY_HEADER: POLICY}

    with FrontendServer(behaviour) as base:
        verdict = confirmed(base, _manifest(fingerprint(root)), wait=deploy_finishes)

    assert (verdict.outcome, waits) == ("match", [120])


def test_a_difference_still_there_on_the_second_look_is_reported(tmp_path):
    root = write_site(tmp_path / "site")
    waits = []

    with FrontendServer(SiteBehaviour(root, policy_headers={})) as base:
        verdict = confirmed(base, _manifest(fingerprint(root)), wait=waits.append)

    assert (verdict.outcome, waits) == ("mismatch", [120])


def test_a_match_is_not_looked_at_twice(tmp_path):
    root = write_site(tmp_path / "site")
    waits = []

    with FrontendServer(SiteBehaviour(root)) as base:
        confirmed(base, _manifest(fingerprint(root)), wait=waits.append)

    assert waits == []


def test_the_verdict_serialises_for_the_alert_step(tmp_path):
    root = write_site(tmp_path / "site")

    verdict = _verdict(SiteBehaviour(root), _manifest(fingerprint(root)))

    assert verdict.as_json() == {"outcome": "match", "matched": "current", "findings": []}

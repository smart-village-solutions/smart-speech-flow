"""The consent text the gateway serves: Studio's or the bundled one (spec §6, D9)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services.api_gateway.message_models import SUPPORTED_LANGUAGES
from services.api_gateway.recording import consent_text as ct
from services.api_gateway.recording.consent_text import (
    BUNDLED_VERSION,
    consent_text,
    german_text,
)
from services.api_gateway.studio_html import safe_html
from services.api_gateway.studio_v2 import RecordingPolicy, RecordingTexts
from tests.test_recording_session_service import POLICY_FIELDS

BUNDLED = Path(ct.__file__).with_name("consent_texts")
# Archived records cite BUNDLED_VERSION: a changed text needs a new version.
BUNDLED_DIGEST = {
    "bundled-1": "fea1434bdbbae1d01aedad86907bd6d173206c40eb799ff488667e9018f9e269",
}


def _policy(*texts: RecordingTexts, basis: str = "consent") -> RecordingPolicy:
    policy = RecordingPolicy.model_validate(POLICY_FIELDS | {"legalBasis": basis})
    return policy.model_copy(update={"texts": texts, "configuration_revision": "rev-7"})


def _studio(locale: str, consent: str = "<p>Studio yes</p>", resume: str = "<p>Studio again</p>"):
    return RecordingTexts(locale=locale, consent_html=consent, resume_prompt_html=resume)


def _bundled_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(BUNDLED.glob("*.json")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def test_every_language_has_both_texts_for_both_legal_bases() -> None:
    assert {path.stem for path in BUNDLED.glob("*.json")} == set(SUPPORTED_LANGUAGES)
    for language in SUPPORTED_LANGUAGES:
        for basis in ("consent", "statutory"):
            policy = _policy(basis=basis)
            first = consent_text(policy, language, "first")
            resume = consent_text(policy, language, "resume")
            assert (first.language, first.source, first.version) == (
                language,
                "bundled",
                BUNDLED_VERSION,
            )
            assert first.html.startswith("<p>") and resume.html.startswith("<p>")
            assert first.html != resume.html
            # Served as written: the stored text is the very string the hash covers.
            assert safe_html(first.html) == first.html


def test_the_bundled_files_match_their_version() -> None:
    assert BUNDLED_DIGEST == {BUNDLED_VERSION: _bundled_digest()}


def test_the_legal_basis_selects_the_bundled_text() -> None:
    consent = consent_text(_policy(basis="consent"), "en", "first")
    statutory = consent_text(_policy(basis="statutory"), "en", "first")
    assert "voluntary" in consent.html and "legal basis" not in consent.html
    assert "legal basis" in statutory.html and "voluntary" not in statutory.html


def test_studio_text_wins_for_its_language_sanitised_and_versioned_by_revision() -> None:
    policy = _policy(_studio("ar-SY", consent="<p>نص</p><script>x()</script>"))
    served = consent_text(policy, "ar", "first")
    assert (served.source, served.version, served.html) == ("studio", "rev-7", "<p>نص</p>")
    assert consent_text(policy, "ar", "resume").html == "<p>Studio again</p>"
    assert consent_text(policy, "tr", "first").source == "bundled"


def test_the_first_studio_entry_for_a_language_wins() -> None:
    policy = _policy(_studio("kmr", consent="<p>one</p>"), _studio("ku", consent="<p>two</p>"))
    assert consent_text(policy, "ku", "first").html == "<p>one</p>"


def test_a_language_without_a_bundled_file_falls_back_to_german() -> None:
    served = consent_text(_policy(), "xx", "first")
    assert (served.language, served.html) == ("de", consent_text(_policy(), "de", "first").html)


@pytest.mark.parametrize(
    ("texts", "guest_source", "german"),
    [
        (
            (_studio("ar"), _studio("de-DE", consent="<p>Studio ja</p>")),
            "studio",
            "<p>Studio ja</p>",
        ),
        ((_studio("ar"),), "studio", None),
        ((_studio("de", consent="<p>Studio ja</p>"),), "bundled", None),
    ],
    ids=["studio-german", "studio-without-german", "bundled-guest-text"],
)
def test_the_german_text_comes_from_the_same_source_where_it_can(
    texts, guest_source, german
) -> None:
    policy = _policy(*texts)
    served = consent_text(policy, "ar", "first")
    assert served.source == guest_source
    expected = german or consent_text(_policy(), "de", "first").html
    assert german_text(policy, served).html == expected


def test_the_hash_covers_the_served_bytes() -> None:
    served = consent_text(_policy(_studio("fa", consent="<p>متن</p>")), "fa", "first")
    assert served.sha256 == hashlib.sha256("<p>متن</p>".encode()).hexdigest()
    assert served.record()["sha256"] == served.sha256
    assert served.record()["html"] == served.html


def test_read_aloud_text_has_one_paragraph_per_line_and_no_markup() -> None:
    policy = _policy(_studio("en", consent="<p>One &amp; two.</p><ul><li>A</li><li>B</li></ul>"))
    assert consent_text(policy, "en", "first").plain() == "One & two.\nA\nB"

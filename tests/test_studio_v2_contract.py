"""Studio contract v2: strict policy, lenient content (tasks.md 1.1, 1.2)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

import pytest

from services.api_gateway.studio_v2 import (
    RuntimeRead,
    StudioContractError,
    parse_installation_content_v2,
    parse_runtime_configuration_v2,
)
from tests.studio_v2_fixtures import INSTALLATION, KASSEL, LABOR, load_fixture

Mutation = Callable[[dict[str, Any]], Any]


def parse(body: object, tenant: str = "tenant-kassel") -> RuntimeRead:
    return parse_runtime_configuration_v2(body, expected_tenant_id=tenant)


def _set(path: str, value: Any) -> Mutation:
    def mutate(body: dict[str, Any]) -> None:
        *parents, leaf = path.split(".")
        target = body
        for key in parents:
            target = target[key]
        target[leaf] = value

    return mutate


def _drop(key: str) -> Mutation:
    return lambda body: body.pop(key)


def _disabled_with(hours: Any) -> Mutation:
    def mutate(body: dict[str, Any]) -> None:
        body["conversationContentStorage"] = {"mode": "disabled", "retentionHours": hours}
        body["guestLanguages"][0]["guest"]["storageQuestionHtml"] = None

    return mutate


def _guest(body: dict[str, Any]) -> dict[str, Any]:
    return body["guestLanguages"][0]


def _form(owner: dict[str, Any]) -> dict[str, Any]:
    return owner["feedback"]


def _question(owner: dict[str, Any], index: int) -> dict[str, Any]:
    return _form(owner)["questions"][index]


@pytest.mark.parametrize(
    ("name", "tenant"), [(KASSEL, "tenant-kassel"), (LABOR, "smart-city-labor")]
)
def test_production_runtime_bodies_parse_completely(name: str, tenant: str) -> None:
    read = parse(load_fixture(name), tenant)

    assert read.policy.tenant_id == tenant
    assert read.policy.contract_version == "2.0"
    assert read.policy.mode == "ask"
    assert read.policy.retention_hours == 4320
    assert read.policy.configuration_revision.startswith("sha256:")
    assert read.content.time_zone == "Europe/Berlin"
    assert read.content.branding.logo is not None
    assert read.content.branding.icon is not None
    staff = read.content.staff
    assert staff is not None
    assert staff.locale == "de-DE"
    assert staff.feedback is not None
    assert [question.type for question in staff.feedback.questions] == [
        "rating",
        "rating",
        "rating",
        "scale",
        "longText",
    ]
    assert [language.locale for language in read.content.guest_languages] == ["en"]
    english = read.content.guest_languages[0]
    assert english.native_name == "English"
    assert english.icon is not None
    assert english.storage_question_html is not None
    assert english.feedback is not None


def test_accepts_a_later_minor_version_and_ignores_unknown_fields() -> None:
    body = load_fixture(KASSEL)
    body["contractVersion"] = "2.7"
    body["futureSection"] = {"x": 1}
    body["staff"]["futureField"] = "y"
    _guest(body)["guest"]["futureField"] = "z"

    read = parse(body)

    assert read.policy.contract_version == "2.7"
    assert read.content.staff is not None
    assert len(read.content.guest_languages) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        _set("contractVersion", "1.0"),
        _set("contractVersion", "3.0"),
        _set("contractVersion", "2.01"),
        _set("configurationRevision", "sha256:ABC"),
        _drop("configurationRevision"),
        _set("tenant.id", ""),
        _set("tenant.id", 42),
        _set("conversationContentStorage.mode", "always"),
        _set("conversationContentStorage.retentionHours", None),
        _set("conversationContentStorage.retentionHours", -1),
        _set("conversationContentStorage.retentionHours", 8761),
        _set("conversationContentStorage.retentionHours", 4320.0),
        _set("conversationContentStorage.retentionHours", True),
        _set("conversationContentStorage.retentionHours", "4320"),
        _disabled_with(4320),
        _drop("conversationContentStorage"),
        _drop("tenant"),
    ],
    ids=[
        "version-1",
        "version-3",
        "version-leading-zero",
        "revision-pattern",
        "revision-missing",
        "tenant-id-empty",
        "tenant-id-not-a-string",
        "mode-unknown",
        "ask-null-retention",
        "retention-negative",
        "retention-over-8760",
        "retention-float",
        "retention-bool",
        "retention-string",
        "disabled-with-retention",
        "storage-missing",
        "tenant-missing",
    ],
)
def test_an_invalid_policy_fails_the_read(mutate: Mutation) -> None:
    body = load_fixture(KASSEL)
    mutate(body)

    with pytest.raises(StudioContractError) as caught:
        parse(body)

    assert caught.value.reason == "response_invalid"


@pytest.mark.parametrize("body", [None, [], "text", 42])
def test_a_non_object_body_fails_the_read(body: object) -> None:
    with pytest.raises(StudioContractError) as caught:
        parse(body)

    assert caught.value.reason == "response_invalid"


@pytest.mark.parametrize("hours", [0, 8760])
def test_retention_bounds_are_inclusive(hours: int) -> None:
    body = load_fixture(KASSEL)
    body["conversationContentStorage"]["retentionHours"] = hours

    assert parse(body).policy.retention_hours == hours


def test_disabled_requires_null_retention() -> None:
    body = load_fixture(KASSEL)
    _disabled_with(None)(body)

    read = parse(body)

    assert read.policy.mode == "disabled"
    assert read.policy.retention_hours is None
    assert [language.locale for language in read.content.guest_languages] == ["en"]


@pytest.mark.parametrize("requested", ["tenant-fulda", "tenant-kässel", "TENANT-KASSEL"])
def test_a_tenant_mismatch_fails_the_read(requested: str) -> None:
    with pytest.raises(StudioContractError) as caught:
        parse(load_fixture(KASSEL), requested)

    assert caught.value.reason == "tenant_mismatch"


GUEST_LANGUAGE_DEFECTS: dict[str, Mutation] = {
    "unknown-question-type": lambda g: _question(g, 0).update(type="multipleChoice"),
    "duplicate-question-id": lambda g: _question(g, 1).update(id="translationQuality"),
    "question-id-pattern": lambda g: _question(g, 0).update(id="1st"),
    "question-id-too-long": lambda g: _question(g, 0).update(id="q" * 65),
    "rating-min-zero": lambda g: _question(g, 0).update(min=0),
    "rating-min-not-below-max": lambda g: _question(g, 0).update(min=5, max=5),
    "scale-min-above-max": lambda g: _question(g, 3).update(min=7, max=3),
    "scale-max-over-10": lambda g: _question(g, 3).update(max=11),
    "range-as-string": lambda g: _question(g, 0).update(min="1"),
    "required-as-string": lambda g: _question(g, 0).update(required="true"),
    "long-text-max-length": lambda g: _question(g, 4).update(maxLength=4001),
    "long-text-max-length-zero": lambda g: _question(g, 4).update(maxLength=0),
    "no-questions": lambda g: _form(g).update(questions=[]),
    "too-many-questions": lambda g: _form(g).update(
        questions=[{**_question(g, 4), "id": f"q{index}"} for index in range(21)]
    ),
    "form-button-empty": lambda g: _form(g).update(button=""),
    "notice-html-too-long": lambda g: _form(g).update(noticeHtml="x" * 65_537),
    "explanation-html-empty": lambda g: g["guest"].update(explanationHtml=""),
    "explanation-html-too-long": lambda g: g["guest"].update(explanationHtml="x" * 65_537),
    "storage-question-missing": lambda g: g["guest"].pop("storageQuestionHtml"),
    "storage-question-null-for-ask": lambda g: g["guest"].update(storageQuestionHtml=None),
    "native-name-too-long": lambda g: g.update(nativeName="x" * 501),
    "staff-name-empty": lambda g: g.update(staffName=""),
    "locale-not-bcp47": lambda g: g.update(locale="english"),
    "locale-too-long": lambda g: g.update(locale="en-" + "-".join(["abcdefgh"] * 4)),
    "guest-texts-missing": lambda g: g.pop("guest"),
}


@pytest.mark.parametrize("defect", GUEST_LANGUAGE_DEFECTS.values(), ids=GUEST_LANGUAGE_DEFECTS)
def test_an_invalid_guest_language_is_dropped_alone(defect: Mutation) -> None:
    body = load_fixture(KASSEL)
    body["guestLanguages"].append(deepcopy(_guest(body)) | {"locale": "tr"})
    defect(_guest(body))

    read = parse(body)

    assert [language.locale for language in read.content.guest_languages] == ["tr"]
    assert read.policy.mode == "ask"
    assert read.policy.retention_hours == 4320
    assert read.content.staff is not None


def test_an_unknown_question_type_keeps_the_policy_usable() -> None:
    body = load_fixture(KASSEL)
    _question(_guest(body), 2)["type"] = "emoji"

    read = parse(body)

    assert read.content.guest_languages == ()
    assert read.policy.mode == "ask"
    assert read.policy.retention_hours == 4320


def test_a_disabled_mode_drops_a_language_that_still_asks() -> None:
    body = load_fixture(KASSEL)
    body["conversationContentStorage"] = {"mode": "disabled", "retentionHours": None}

    read = parse(body)

    assert read.policy.mode == "disabled"
    assert read.content.guest_languages == ()


@pytest.mark.parametrize(
    "url",
    [
        "http://dialog.kassel.de/flags/gb.png",
        "javascript:alert(1)",
        "https://",
        "https://a b.de/x",
        "https://user:pw@dialog.kassel.de/x",
        "https://dialog.kassel.de:99999/x",
        "https://dialog.kassel.de/" + "x" * 2048,
    ],
    ids=["http", "javascript", "no-host", "whitespace", "userinfo", "bad-port", "too-long"],
)
def test_a_non_https_media_url_drops_only_that_medium(url: str) -> None:
    body = load_fixture(KASSEL)
    body["branding"]["logo"]["url"] = url
    _guest(body)["icon"]["url"] = url

    read = parse(body)

    assert read.content.branding.logo is None
    assert read.content.branding.icon is not None
    assert read.content.guest_languages[0].icon is None
    assert read.content.guest_languages[0].locale == "en"


def test_alternative_text_may_be_empty_but_not_over_500() -> None:
    body = load_fixture(KASSEL)
    body["branding"]["logo"]["alternativeText"] = ""
    body["branding"]["icon"]["alternativeText"] = "x" * 501

    read = parse(body)

    assert read.content.branding.logo is not None
    assert read.content.branding.icon is None


def test_an_invalid_staff_form_becomes_none_and_keeps_staff_texts() -> None:
    body = load_fixture(KASSEL)
    _question(body["staff"], 0)["type"] = "emoji"

    staff = parse(body).content.staff

    assert staff is not None
    assert staff.feedback is None
    assert staff.dashboard.load.green == "Ausreichend Kapazitäten verfügbar"


@pytest.mark.parametrize(
    "defect",
    [
        lambda staff: staff["dashboard"].update(headline="x" * 501),
        lambda staff: staff["dashboard"].update(callToAction=""),
        lambda staff: staff["dashboard"]["load"].pop("red"),
        lambda staff: staff["newConversation"].update(descriptionHtml="x" * 65_537),
        lambda staff: staff.update(locale="de_DE"),
    ],
    ids=["headline-too-long", "cta-empty", "load-label-missing", "html-too-long", "locale"],
)
def test_invalid_staff_texts_make_staff_none(defect: Mutation) -> None:
    body = load_fixture(KASSEL)
    defect(body["staff"])

    read = parse(body)

    assert read.content.staff is None
    assert [language.locale for language in read.content.guest_languages] == ["en"]


@pytest.mark.parametrize("key", ["branding", "staff", "guestLanguages"])
def test_a_missing_content_section_does_not_fail_the_read(key: str) -> None:
    body = load_fixture(KASSEL)
    body.pop(key)

    read = parse(body)

    assert read.policy.retention_hours == 4320


def test_html_and_text_limits_are_inclusive() -> None:
    body = load_fixture(KASSEL)
    _guest(body)["guest"]["explanationHtml"] = "x" * 65_536
    _guest(body)["nativeName"] = "x" * 500

    assert len(parse(body).content.guest_languages) == 1


def test_long_text_max_length_defaults_to_4000() -> None:
    body = load_fixture(KASSEL)
    _question(_guest(body), 4).pop("maxLength")

    form = parse(body).content.guest_languages[0].feedback

    assert form is not None
    assert form.questions[4].type == "longText"
    assert form.questions[4].max_length == 4000


def test_dropped_content_is_logged_without_studio_text(caplog: pytest.LogCaptureFixture) -> None:
    body = load_fixture(KASSEL)
    _guest(body)["nativeName"] = "SECRET-" + "x" * 500
    body["branding"]["logo"]["url"] = "http://SECRET.example/logo.png"

    with caplog.at_level("WARNING", logger="services.api_gateway.studio_v2"):
        parse(body)

    assert "guestLanguages.0 " in caplog.text
    assert "SECRET" not in caplog.text


def test_dropped_fields_are_logged_with_their_section(caplog: pytest.LogCaptureFixture) -> None:
    body = load_fixture(KASSEL)
    body["guestLanguages"].append(deepcopy(_guest(body)) | {"locale": "tr"})
    body["guestLanguages"][1]["icon"]["url"] = "http://insecure.example/tr.png"
    body["branding"]["logo"]["url"] = "http://insecure.example/logo.png"
    _question(body["staff"], 0)["type"] = "emoji"
    body["tenant"]["timeZone"] = "Not/AZone"

    with caplog.at_level("WARNING", logger="services.api_gateway.studio_v2"):
        parse(body)

    assert "guestLanguages.1.icon" in caplog.text
    assert "branding.logo" in caplog.text
    assert "staff.feedback" in caplog.text
    assert "tenant.time_zone" in caplog.text


def test_dropped_installation_fields_are_logged_with_their_section(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = load_fixture(INSTALLATION)
    body["branding"]["icon"]["url"] = "http://insecure.example/icon.png"
    body["localization"]["feedback"]["questions"][0]["type"] = "emoji"

    with caplog.at_level("WARNING", logger="services.api_gateway.studio_v2"):
        parse_installation_content_v2(body)

    assert "installation.icon" in caplog.text
    assert "installation.feedback" in caplog.text


@pytest.mark.parametrize(
    "mutate",
    [
        _set("tenant.timeZone", "Not/AZone"),
        _set("tenant.timeZone", "../etc/passwd"),
        _set("tenant.timeZone", ""),
        _set("tenant.timeZone", 1),
        lambda body: body["tenant"].pop("timeZone"),
    ],
    ids=["unknown", "path", "empty", "not-a-string", "missing"],
)
def test_an_unusable_time_zone_is_dropped_and_the_policy_still_works(mutate: Mutation) -> None:
    body = load_fixture(KASSEL)
    mutate(body)

    read = parse(body)

    assert read.content.time_zone is None
    assert read.content.display_name == "Smart City Kassel"
    assert read.policy.mode == "ask"
    assert read.policy.retention_hours == 4320


@pytest.mark.parametrize(
    "mutate",
    [
        _set("tenant.displayName", ""),
        _set("tenant.displayName", "x" * 201),
        lambda body: body["tenant"].pop("displayName"),
    ],
    ids=["empty", "too-long", "missing"],
)
def test_an_unusable_display_name_is_dropped_and_the_policy_still_works(mutate: Mutation) -> None:
    body = load_fixture(KASSEL)
    mutate(body)

    read = parse(body)

    assert read.content.display_name is None
    assert read.content.time_zone == "Europe/Berlin"
    assert read.policy.retention_hours == 4320


def test_production_installation_body_parses() -> None:
    content = parse_installation_content_v2(load_fixture(INSTALLATION))

    assert content.configuration_revision.startswith("sha256:")
    assert content.legal.imprint_url == "https://www.kassel.de/impressum.php"
    assert content.legal.accessibility_statement_url is not None
    assert content.locale == "de-DE"
    assert content.startpage.enter_code == "Code eingeben"
    assert content.login.description_html.endswith("<p></p>")
    assert content.branding.icon is not None
    assert content.feedback is not None
    assert len(content.feedback.questions) == 5


def test_accessibility_statement_may_be_null() -> None:
    body = load_fixture(INSTALLATION)
    body["legal"]["accessibilityStatementUrl"] = None

    assert parse_installation_content_v2(body).legal.accessibility_statement_url is None


@pytest.mark.parametrize(
    "mutate",
    [
        _set("contractVersion", "1.0"),
        _drop("contractVersion"),
        _set("configurationRevision", "sha256:x"),
        _set("legal.imprintUrl", "http://www.kassel.de/impressum.php"),
        _set("legal.privacyPolicyUrl", "/datenschutz"),
        _set("legal.accessibilityStatementUrl", "ftp://kassel.de/a"),
        _set("localization.locale", "deutsch"),
        _set("localization.startpage", {"enterCode": "Code", "send": ""}),
        _set("localization.login", {"headline": "Login", "descriptionHtml": ""}),
        _drop("legal"),
        _drop("localization"),
    ],
    ids=[
        "version",
        "version-missing",
        "revision",
        "imprint-http",
        "privacy-relative",
        "a11y-ftp",
        "locale",
        "startpage",
        "login-html-empty",
        "legal-missing",
        "localization-missing",
    ],
)
def test_invalid_installation_content_fails(mutate: Mutation) -> None:
    body = load_fixture(INSTALLATION)
    mutate(body)

    with pytest.raises(StudioContractError) as caught:
        parse_installation_content_v2(body)

    assert caught.value.reason == "response_invalid"


@pytest.mark.parametrize("body", [None, [], "text"])
def test_a_non_object_installation_body_fails(body: object) -> None:
    with pytest.raises(StudioContractError):
        parse_installation_content_v2(body)


def test_installation_media_and_form_are_lenient() -> None:
    body = load_fixture(INSTALLATION)
    body["branding"]["logo"]["url"] = "http://insecure.example/logo.png"
    body["localization"]["feedback"]["questions"][0]["type"] = "emoji"

    content = parse_installation_content_v2(body)

    assert content.branding.logo is None
    assert content.branding.icon is not None
    assert content.feedback is None


def test_installation_without_branding_still_parses() -> None:
    body = load_fixture(INSTALLATION)
    body.pop("branding")

    content = parse_installation_content_v2(body)

    assert content.branding.logo is None
    assert content.branding.icon is None


def test_localization_cannot_replace_top_level_installation_fields() -> None:
    body = load_fixture(INSTALLATION)
    revision = body["configurationRevision"]
    body["localization"]["configurationRevision"] = f"sha256:{'0' * 64}"
    body["localization"]["legal"] = {
        "imprintUrl": "https://attacker.example/imprint",
        "privacyPolicyUrl": "https://attacker.example/privacy",
        "accessibilityStatementUrl": None,
    }

    content = parse_installation_content_v2(body)

    assert content.configuration_revision == revision
    assert content.legal.imprint_url == "https://www.kassel.de/impressum.php"


def test_localization_texts_come_only_from_the_localization_block() -> None:
    body = load_fixture(INSTALLATION)
    body["startpage"] = body["localization"].pop("startpage")

    with pytest.raises(StudioContractError):
        parse_installation_content_v2(body)


def test_guest_texts_come_only_from_the_guest_block() -> None:
    body = load_fixture(KASSEL)
    guest = _guest(body)
    guest["explanationHtml"] = guest["guest"].pop("explanationHtml")

    assert parse(body).content.guest_languages == ()

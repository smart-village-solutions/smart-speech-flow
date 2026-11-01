"""The four browser content routes, against the Studio mock through the real clients.

The JSON shapes are the contract the frontend PRs build on: see "Browser
routes (PR 5)" in the Studio v2 roadmap.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from services.studio_mock import contract_fixtures

KASSEL = "tenant-kassel"
FULDA = "tenant-fulda"
DISPLAY_NAMES = ("Kassel Test Municipality", "Fulda Test Municipality")
INSTALLATION = "/api/content/installation"
STAFF = "/api/admin/content"
BUNDLED = {
    "ru": ("Russian", "Русский"),
    "uk": ("Ukrainian", "Українська"),
    "am": ("Amharic", "አማርኛ"),
    "fa": ("Persian", "فارسی"),
    "it": ("Italian", "Italiano"),
    "ro": ("Romanian", "Română"),
    "pl": ("Polish", "Polski"),
    "bg": ("Bulgarian", "Български"),
    "el": ("Greek", "Ελληνικά"),
    "fr": ("French", "Français"),
    "es": ("Spanish", "Español"),
    "sq": ("Albanian", "Shqip"),
    "hu": ("Hungarian", "Magyar"),
    "zh": ("Chinese", "中文"),
    "hi": ("Hindi", "हिन्दी"),
}

pytestmark = pytest.mark.usefixtures("studio_mock")


def languages_path(session_id: str) -> str:
    return f"/api/customer/session/{session_id}/languages"


def content_path(session_id: str, language: str) -> str:
    return f"/api/customer/session/{session_id}/content/{language}"


def runtime_body(tenant_id: str = KASSEL, scenario: str | None = None) -> dict[str, Any]:
    return contract_fixtures.runtime_configuration_v2(tenant_id, scenario)


def guest_language(tenant_id: str, locale: str) -> dict[str, Any]:
    return next(
        language
        for language in runtime_body(tenant_id)["guestLanguages"]
        if language["locale"] == locale
    )


def expected_installation() -> dict[str, Any]:
    body = contract_fixtures.installation_content_v2(None)
    localization = body["localization"]
    return {
        "revision": body["configurationRevision"],
        "branding": body["branding"],
        "legal": body["legal"],
        "locale": localization["locale"],
        "startpage": localization["startpage"],
        "login": localization["login"],
        "feedback": localization["feedback"],
    }


def assert_no_display_name(response) -> None:
    for name in DISPLAY_NAMES:
        assert name not in response.text
    assert "displayName" not in response.text


# Installation content


def test_installation_content_is_anonymous_cacheable_and_tagged(client, identity):
    identity.unauthenticated()

    response = client.get(INSTALLATION)

    assert response.status_code == 200
    assert response.json() == expected_installation()
    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert response.headers["ETag"].startswith(f'"{expected_installation()["revision"]}.')
    assert_no_display_name(response)


@pytest.mark.parametrize("form", ["{tag}", "W/{tag}", '"sha256:other", {tag}', "*"])
def test_a_current_etag_answers_not_modified(client, form):
    tag = client.get(INSTALLATION).headers["ETag"]

    response = client.get(INSTALLATION, headers={"If-None-Match": form.format(tag=tag)})

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["ETag"] == tag
    assert response.headers["Cache-Control"] == "public, max-age=60"


def test_a_tag_for_the_same_revision_but_another_body_gets_the_content(client):
    """A gateway release that changes this body must not leave browsers on the old one."""
    bare_revision = f'"{expected_installation()["revision"]}"'

    response = client.get(INSTALLATION, headers={"If-None-Match": bare_revision})

    assert response.status_code == 200


def test_another_etag_gets_the_content(client):
    response = client.get(INSTALLATION, headers={"If-None-Match": f'"sha256:{"0" * 64}"'})

    assert response.status_code == 200
    assert response.json() == expected_installation()


def test_installation_never_loaded_is_unavailable_and_not_cached(client, studio_mock):
    studio_mock.stopped = True

    response = client.get(INSTALLATION)

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"


def test_installation_is_served_stale_while_studio_is_down(client, studio_mock):
    client.get(INSTALLATION)
    studio_mock.age_content(3600)
    studio_mock.stopped = True

    response = client.get(INSTALLATION)

    assert response.status_code == 200
    assert response.json() == expected_installation()


def test_invalid_installation_feedback_drops_only_the_form(client, studio_mock):
    studio_mock.scenario = "invalid-content"

    body = client.get(INSTALLATION).json()

    assert body["feedback"] is None
    assert body["startpage"] == expected_installation()["startpage"]


# Guest languages


def test_guest_languages_need_the_session_key(client):
    assert client.get(languages_path("NOSUCH01")).status_code == 404


def test_guest_languages_are_ssfs_with_studio_names_and_icons(client, conversations):
    session_id = conversations.create(KASSEL)

    response = client.get(languages_path(session_id))

    assert response.status_code == 200
    languages = response.json()["languages"]
    assert [language["code"] for language in languages] == [
        "en", "ar", "tr", "ru", "uk", "am", "fa",
        "it", "ro", "pl", "bg", "el", "fr", "es", "pt", "sq", "hu", "zh", "hi",
    ]  # fmt: skip
    by_code = {language["code"]: language for language in languages}
    assert by_code["en"] == {
        "code": "en",
        "name": "English",
        "native": "English",
        "provided": True,
        "nativeName": "English",
        "icon": guest_language(KASSEL, "en")["icon"],
    }
    assert by_code["ar"]["provided"] is True
    assert by_code["ar"]["icon"] is None
    # Studio's pt-BR is SSF's Portuguese.
    assert by_code["pt"]["provided"] is True
    assert by_code["pt"]["nativeName"] == "Português (Brasil)"
    assert by_code["tr"]["nativeName"] == "Türkçe"
    for code, (name, native) in BUNDLED.items():
        assert by_code[code] == {"code": code, "name": name, "native": native, "provided": False}
    assert_no_display_name(response)


def test_invalid_content_withdraws_only_that_language(client, conversations, studio_mock):
    studio_mock.scenario = "invalid-content"
    session_id = conversations.create(KASSEL)

    by_code = {
        language["code"]: language
        for language in client.get(languages_path(session_id)).json()["languages"]
    }
    english = client.get(content_path(session_id, "en")).json()
    turkish = client.get(content_path(session_id, "tr")).json()

    assert by_code["en"]["provided"] is False
    assert all(by_code[code]["provided"] for code in ("ar", "tr"))
    assert english == {"provided": False, "recordingStatus": None, "legalInformation": None}
    assert turkish["provided"] is True


def test_languages_without_any_studio_content_are_all_bundled(client, conversations, studio_mock):
    session_id = conversations.create(KASSEL)
    studio_mock.restart_content()
    studio_mock.stopped = True

    languages = client.get(languages_path(session_id)).json()["languages"]
    content = client.get(content_path(session_id, "en")).json()

    assert [language["provided"] for language in languages] == [False] * 19
    assert content == {"provided": False, "recordingStatus": None, "legalInformation": None}


# Guest content


def test_guest_content_for_a_provided_language(client, conversations):
    session_id = conversations.create(KASSEL)
    english = guest_language(KASSEL, "en")

    response = client.get(content_path(session_id, "en"))

    assert response.status_code == 200
    assert response.json() == {
        "provided": True,
        "legalInformation": None,
        "recordingStatus": None,
        "revision": runtime_body()["configurationRevision"],
        "explanationHtml": english["guest"]["explanationHtml"],
        "feedback": english["feedback"],
    }
    assert_no_display_name(response)


def test_guest_content_for_a_language_studio_does_not_provide(client, conversations):
    session_id = conversations.create(KASSEL)

    response = client.get(content_path(session_id, "fa"))

    assert response.json() == {"provided": False, "recordingStatus": None, "legalInformation": None}


@pytest.mark.parametrize("language", ["de", "hr", "xx"])
def test_guest_content_only_for_ssfs_guest_languages(client, conversations, language):
    session_id = conversations.create(KASSEL)

    response = client.get(content_path(session_id, language))

    assert response.status_code == 404
    assert response.json() == {"detail": "Language not supported"}


def test_a_tenant_whose_studio_storage_is_disabled_gets_the_same_guest_content(
    client, conversations
):
    assert runtime_body(FULDA)["conversationContentStorage"]["mode"] == "disabled"
    session_id = conversations.create(FULDA)

    body = client.get(content_path(session_id, "en")).json()

    assert body == {
        "provided": True,
        "legalInformation": None,
        "recordingStatus": None,
        "revision": runtime_body(FULDA)["configurationRevision"],
        "explanationHtml": guest_language(FULDA, "en")["guest"]["explanationHtml"],
        "feedback": guest_language(FULDA, "en").get("feedback"),
    }


def test_guest_content_is_answered_from_the_cache_until_it_ages(client, conversations, studio_mock):
    session_id = conversations.create(KASSEL)
    # The scenario drops English: only a fresh Studio read would see it.
    studio_mock.scenario = "invalid-content"

    cached = client.get(content_path(session_id, "en")).json()
    studio_mock.age_content(61)
    refreshed = client.get(content_path(session_id, "en")).json()

    assert cached["provided"] is True
    assert cached["revision"] == runtime_body()["configurationRevision"]
    assert refreshed == {"provided": False, "recordingStatus": None, "legalInformation": None}


def test_a_failed_live_read_serves_the_last_content(client, conversations, studio_mock):
    session_id = conversations.create(KASSEL)
    studio_mock.age_content(3600)
    studio_mock.stopped = True

    body = client.get(content_path(session_id, "en")).json()

    assert body["provided"] is True
    assert body["revision"] == runtime_body()["configurationRevision"]
    assert body["explanationHtml"] == guest_language(KASSEL, "en")["guest"]["explanationHtml"]


def test_another_tenants_operator_cannot_read_guest_content(client, conversations, identity):
    session_id = conversations.create(KASSEL)
    identity.customer_bearer(FULDA)

    assert client.get(content_path(session_id, "en")).status_code == 404
    assert client.get(languages_path(session_id)).status_code == 404


# Feedback grace period


def test_guest_routes_answer_within_the_grace_period_after_the_end(
    client, conversations, session_clock, guest_grace_window
):
    guest_grace_window(timedelta(minutes=30))
    session_id = conversations.create(KASSEL)
    conversations.activate(session_id, "en")
    conversations.terminate(session_id)

    session_clock.advance(minutes=29)
    inside = [
        client.get(content_path(session_id, "en")).status_code,
        client.get(languages_path(session_id)).status_code,
    ]
    session_clock.advance(minutes=2)
    after = [
        client.get(content_path(session_id, "en")).status_code,
        client.get(languages_path(session_id)).status_code,
    ]

    assert inside == [200, 200]
    assert after == [404, 404]


def test_a_zero_grace_period_ends_guest_access_with_the_session(
    client, conversations, guest_grace_window
):
    guest_grace_window(timedelta(0))
    session_id = conversations.create(KASSEL)
    conversations.terminate(session_id)

    assert client.get(content_path(session_id, "en")).status_code == 404


# Staff content


def test_staff_content_needs_a_bearer(client, identity):
    identity.unauthenticated()

    response = client.get(STAFF)

    assert response.status_code == 401


def test_staff_content_for_the_tokens_tenant(client, identity):
    identity.act_as(KASSEL)
    body = runtime_body()

    response = client.get(STAFF)

    assert response.status_code == 200
    assert response.json() == {
        "revision": body["configurationRevision"],
        "timeZone": "Europe/Berlin",
        "legalInformation": None,
        "recordingStatus": None,
        "branding": body["branding"],
        "staff": body["staff"],
        "guestLanguageNames": {
            "en": "Englisch",
            "ar": "Arabisch",
            "tr": "Türkisch",
            "pt": "Portugiesisch (Brasilien)",
        },
    }
    assert_no_display_name(response)


def test_staff_content_never_read_with_studio_down_is_unavailable(client, identity, studio_mock):
    identity.act_as(KASSEL)
    studio_mock.stopped = True

    response = client.get(STAFF)

    assert response.status_code == 503
    assert response.json() == {"detail": "Studio content is temporarily unavailable"}
    assert response.headers["Cache-Control"] == "no-store"


def test_staff_content_is_served_stale_while_studio_is_down(client, identity, studio_mock):
    identity.act_as(KASSEL)
    client.get(STAFF)
    studio_mock.age_content(3600)
    studio_mock.stopped = True

    response = client.get(STAFF)

    assert response.status_code == 200
    assert response.json()["staff"] == runtime_body()["staff"]


def test_every_live_read_refreshes_the_content(client, conversations, studio_mock):
    # Session create reads the runtime configuration; nothing else reads Studio.
    conversations.create(KASSEL)
    studio_mock.age_content(3600)
    studio_mock.stopped = True

    response = client.get(STAFF)

    assert response.status_code == 200
    assert response.json()["revision"] == runtime_body()["configurationRevision"]


def test_reading_legal_information_does_not_activate_a_session_or_change_storage(
    client, conversations, identity, monkeypatch
):
    from tests.test_legal_information import legal_block

    original = contract_fixtures.runtime_configuration_v2

    def with_legal(tenant_id, scenario=None):
        body = original(tenant_id, scenario)
        if tenant_id == KASSEL:
            body["legalTexts"] = legal_block()
        return body

    monkeypatch.setattr(contract_fixtures, "runtime_configuration_v2", with_legal)
    session_id = conversations.create(KASSEL)
    before_response = client.get(f"/api/customer/session/{session_id}")
    assert before_response.status_code == 200
    before = before_response.json()
    response = client.get(content_path(session_id, "fa"))
    assert response.status_code == 200
    assert "storage" not in response.json()
    assert response.json()["provided"] is False
    assert response.json()["legalInformation"]["locale"] == "de-DE"
    assert len(response.json()["legalInformation"]["sections"]) == 4
    after = client.get(f"/api/customer/session/{session_id}").json()
    assert after == before
    identity.act_as(KASSEL)
    assert client.get(STAFF).json()["legalInformation"]["version"] == "synthetic-draft"

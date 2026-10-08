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
    "ti": ("Tigrinya", "ትግርኛ"),
    "fa": ("Persian", "فارسی"),
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
        "en",
        "ar",
        "tr",
        "ru",
        "uk",
        "am",
        "ti",
        "ku",
        "fa",
    ]
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
    assert by_code["ku"]["nativeName"] == "Kurmancî"
    assert by_code["ku"]["icon"] == guest_language(KASSEL, "kmr")["icon"]
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
    assert all(by_code[code]["provided"] for code in ("ar", "tr", "ku"))
    assert english == {"storage": {"mode": "ask"}, "provided": False}
    assert turkish["provided"] is True


def test_languages_without_any_studio_content_are_all_bundled(client, conversations, studio_mock):
    session_id = conversations.create(KASSEL)
    studio_mock.restart_content()
    studio_mock.stopped = True

    languages = client.get(languages_path(session_id)).json()["languages"]
    content = client.get(content_path(session_id, "en")).json()

    assert [language["provided"] for language in languages] == [False] * 9
    assert content == {"storage": {"mode": "unknown"}, "provided": False}


# Guest content


def test_guest_content_for_a_provided_language(client, conversations):
    session_id = conversations.create(KASSEL)
    english = guest_language(KASSEL, "en")

    response = client.get(content_path(session_id, "en"))

    assert response.status_code == 200
    assert response.json() == {
        "storage": {"mode": "ask"},
        "provided": True,
        "revision": runtime_body()["configurationRevision"],
        "explanationHtml": english["guest"]["explanationHtml"],
        "storageQuestionHtml": english["guest"]["storageQuestionHtml"],
        "feedback": english["feedback"],
    }
    assert_no_display_name(response)


def test_guest_content_for_a_language_studio_does_not_provide(client, conversations):
    session_id = conversations.create(KASSEL)

    response = client.get(content_path(session_id, "fa"))

    assert response.json() == {"storage": {"mode": "ask"}, "provided": False}


@pytest.mark.parametrize("language", ["de", "pt", "xx"])
def test_guest_content_only_for_ssfs_guest_languages(client, conversations, language):
    session_id = conversations.create(KASSEL)

    response = client.get(content_path(session_id, language))

    assert response.status_code == 404
    assert response.json() == {"detail": "Language not supported"}


def test_a_disabled_tenant_reports_disabled_without_a_storage_question(client, conversations):
    session_id = conversations.create(FULDA)

    body = client.get(content_path(session_id, "en")).json()

    assert body["storage"] == {"mode": "disabled"}
    assert body["provided"] is True
    assert body["storageQuestionHtml"] is None


def test_the_mode_is_read_live_on_every_request(client, conversations, studio_mock):
    session_id = conversations.create(KASSEL)
    first = client.get(content_path(session_id, "en")).json()

    studio_mock.scenario = "storage-disabled"
    second = client.get(content_path(session_id, "en")).json()

    assert first["storage"] == {"mode": "ask"}
    assert second["storage"] == {"mode": "disabled"}


def test_a_failed_live_read_reports_unknown_with_the_last_content(
    client, conversations, studio_mock
):
    session_id = conversations.create(KASSEL)
    studio_mock.stopped = True

    body = client.get(content_path(session_id, "en")).json()

    assert body["storage"] == {"mode": "unknown"}
    assert body["provided"] is True
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
        "branding": body["branding"],
        "staff": body["staff"],
        "guestLanguageNames": {
            "en": "Englisch",
            "ar": "Arabisch",
            "tr": "Türkisch",
            "ku": "Kurmandschi",
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

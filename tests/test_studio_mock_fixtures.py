"""The mock's v2 fixtures are complete contract bodies the gateway parses without loss."""

from __future__ import annotations

import hashlib
import json
import logging

import pytest

from services.api_gateway.studio_v2 import (
    parse_installation_content_v2,
    parse_runtime_configuration_v2,
)
from services.studio_mock import fixtures

DROPPED = "Studio content dropped"


def _canonical_sha(body: dict) -> str:
    unstamped = {key: value for key, value in body.items() if key != "configurationRevision"}
    encoded = json.dumps(unstamped, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _dropped(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if DROPPED in record.getMessage()]


def test_every_runtime_fixture_is_named_after_its_tenant() -> None:
    for tenant_id in fixtures.RUNTIME_V2_TENANTS:
        raw = json.loads((fixtures.FIXTURES / f"runtime-{tenant_id}.json").read_text("utf-8"))
        assert raw["tenant"]["id"] == tenant_id
        assert "configurationRevision" not in raw
        assert "authorizationRevision" not in raw


def test_the_three_tenants_cover_ask_disabled_and_zero_retention() -> None:
    storage = {
        tenant: fixtures.runtime_configuration_v2(tenant, None)["conversationContentStorage"]
        for tenant in fixtures.RUNTIME_V2_TENANTS
    }

    assert storage == {
        "tenant-fulda": {"mode": "disabled", "retentionHours": None},
        "tenant-kassel": {"mode": "ask", "retentionHours": 4320},
        "tenant-marburg": {"mode": "ask", "retentionHours": 0},
    }


@pytest.mark.parametrize("tenant_id", fixtures.RUNTIME_V2_TENANTS)
@pytest.mark.parametrize("scenario", [None, "storage-disabled"])
def test_every_runtime_body_parses_without_dropping_content(
    tenant_id: str, scenario: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    body = fixtures.runtime_configuration_v2(tenant_id, scenario)

    with caplog.at_level(logging.WARNING, logger="services.api_gateway.studio_v2"):
        read = parse_runtime_configuration_v2(body, expected_tenant_id=tenant_id)

    assert _dropped(caplog) == []
    assert len(read.content.guest_languages) == len(body["guestLanguages"])
    assert read.content.staff is not None
    assert read.content.staff.feedback is not None
    assert read.content.display_name is not None
    assert read.content.time_zone == "Europe/Berlin"


def test_the_installation_body_parses_without_dropping_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = fixtures.installation_content_v2(None)

    with caplog.at_level(logging.WARNING, logger="services.api_gateway.studio_v2"):
        content = parse_installation_content_v2(body)

    assert _dropped(caplog) == []
    assert content.legal.imprint_url == "https://example.org/impressum"
    assert content.legal.privacy_policy_url == "https://example.org/datenschutz"
    assert content.legal.accessibility_statement_url == "https://example.org/barrierefreiheit"
    assert content.branding.logo is not None
    assert content.branding.icon is not None
    assert content.feedback is not None
    assert {question.type for question in content.feedback.questions} == {
        "rating",
        "scale",
        "longText",
    }


def test_revisions_are_canonical_sha256_and_follow_the_body() -> None:
    plain = fixtures.runtime_configuration_v2("tenant-kassel", None)
    again = fixtures.runtime_configuration_v2("tenant-kassel", None)
    disabled = fixtures.runtime_configuration_v2("tenant-kassel", "storage-disabled")
    installation = fixtures.installation_content_v2(None)

    assert plain == again
    assert plain["configurationRevision"] == _canonical_sha(plain)
    assert disabled["configurationRevision"] == _canonical_sha(disabled)
    assert installation["configurationRevision"] == _canonical_sha(installation)
    assert disabled["configurationRevision"] != plain["configurationRevision"]


def test_a_served_body_is_a_copy_the_caller_may_mutate() -> None:
    fixtures.runtime_configuration_v2("tenant-kassel", None)["guestLanguages"].clear()
    fixtures.login_directory_tenants().clear()

    assert fixtures.runtime_configuration_v2("tenant-kassel", None)["guestLanguages"]
    assert fixtures.login_directory_tenants()


def test_an_unknown_tenant_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        fixtures.runtime_configuration_v2("tenant-unknown", None)


def test_every_directory_tenant_has_a_v2_fixture() -> None:
    directory_ids = {tenant["id"] for tenant in fixtures.login_directory_tenants()}

    assert directory_ids == {"tenant-kassel", "tenant-fulda"}
    assert directory_ids <= set(fixtures.RUNTIME_V2_TENANTS)


def test_storage_disabled_flips_the_policy_and_every_question() -> None:
    body = fixtures.runtime_configuration_v2("tenant-kassel", "storage-disabled")

    read = parse_runtime_configuration_v2(body, expected_tenant_id="tenant-kassel")

    assert (read.policy.mode, read.policy.retention_hours) == ("disabled", None)
    assert len(read.content.guest_languages) == 5
    assert all(language.storage_question_html is None for language in read.content.guest_languages)


def test_invalid_content_drops_only_the_affected_guest_language() -> None:
    body = fixtures.runtime_configuration_v2("tenant-kassel", "invalid-content")

    read = parse_runtime_configuration_v2(body, expected_tenant_id="tenant-kassel")

    assert fixtures.UNSUPPORTED_QUESTION in body["guestLanguages"][0]["feedback"]["questions"]
    assert (read.policy.mode, read.policy.retention_hours) == ("ask", 4320)
    assert [language.locale for language in read.content.guest_languages] == [
        "tr",
        "ar",
        "kmr",
        "pt-BR",
    ]
    assert read.content.staff is not None and read.content.staff.feedback is not None


@pytest.mark.parametrize("tenant_id", fixtures.RUNTIME_V2_TENANTS)
def test_invalid_content_drops_the_first_guest_language_of_every_tenant(tenant_id: str) -> None:
    plain = parse_runtime_configuration_v2(
        fixtures.runtime_configuration_v2(tenant_id, None), expected_tenant_id=tenant_id
    )
    body = fixtures.runtime_configuration_v2(tenant_id, "invalid-content")

    read = parse_runtime_configuration_v2(body, expected_tenant_id=tenant_id)

    assert fixtures.UNSUPPORTED_QUESTION in body["guestLanguages"][0]["feedback"]["questions"]
    assert read.policy.mode == plain.policy.mode
    assert read.policy.retention_hours == plain.policy.retention_hours
    assert read.content.guest_languages == plain.content.guest_languages[1:]


def test_invalid_installation_content_drops_only_the_form() -> None:
    body = fixtures.installation_content_v2("invalid-content")

    content = parse_installation_content_v2(body)

    assert fixtures.UNSUPPORTED_QUESTION in body["localization"]["feedback"]["questions"]
    assert content.feedback is None
    assert content.legal.imprint_url == "https://example.org/impressum"


def test_unknown_scenarios_serve_the_plain_body() -> None:
    assert fixtures.runtime_configuration_v2("tenant-kassel", "no-such-scenario") == (
        fixtures.runtime_configuration_v2("tenant-kassel", None)
    )
    assert fixtures.installation_content_v2("storage-disabled") == (
        fixtures.installation_content_v2(None)
    )


def _kassel_with_guest_languages(monkeypatch: pytest.MonkeyPatch, languages: list[dict]) -> None:
    template = fixtures.runtime_configuration_v2("tenant-kassel", None)
    del template["configurationRevision"]
    template["guestLanguages"] = languages
    monkeypatch.setitem(fixtures._RUNTIME, "tenant-kassel", template)


def test_invalid_content_replaces_an_explicit_null_guest_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    languages = fixtures.runtime_configuration_v2("tenant-kassel", None)["guestLanguages"]
    languages[0]["feedback"] = None
    _kassel_with_guest_languages(monkeypatch, languages)

    body = fixtures.runtime_configuration_v2("tenant-kassel", "invalid-content")
    read = parse_runtime_configuration_v2(body, expected_tenant_id="tenant-kassel")

    assert body["guestLanguages"][0]["feedback"]["questions"] == [fixtures.UNSUPPORTED_QUESTION]
    assert [language.locale for language in read.content.guest_languages] == [
        "tr",
        "ar",
        "kmr",
        "pt-BR",
    ]


def test_invalid_content_without_guest_languages_serves_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _kassel_with_guest_languages(monkeypatch, [])

    body = fixtures.runtime_configuration_v2("tenant-kassel", "invalid-content")

    assert body["guestLanguages"] == []
    assert body["conversationContentStorage"] == {"mode": "ask", "retentionHours": 4320}


def _write_runtime(directory, file_tenant: str, body_tenant: str) -> None:
    body = {"contractVersion": "2.0", "tenant": {"id": body_tenant}}
    (directory / f"runtime-{file_tenant}.json").write_text(json.dumps(body), encoding="utf-8")


def test_runtime_templates_are_keyed_by_the_tenant_id_in_the_body(tmp_path) -> None:
    _write_runtime(tmp_path, "tenant-a", "tenant-a")
    _write_runtime(tmp_path, "tenant-b", "tenant-b")

    templates = fixtures.load_runtime_templates(tmp_path)

    assert sorted(templates) == ["tenant-a", "tenant-b"]
    assert templates["tenant-a"]["tenant"]["id"] == "tenant-a"


def test_a_runtime_fixture_named_after_another_tenant_fails_at_load(tmp_path) -> None:
    _write_runtime(tmp_path, "tenant-giessen", "tenant-gießen")

    with pytest.raises(ValueError, match="runtime-tenant-giessen.json"):
        fixtures.load_runtime_templates(tmp_path)

"""The stored snapshot carries no value that could authorise persistence."""

import json

import pytest

from services.api_gateway.presentation_configuration import PresentationConfiguration
from services.api_gateway.studio_runtime_client import RuntimeConfiguration
from services.api_gateway.tenant_session import RuntimeConfigurationSnapshot

REVISION = "sha256:" + "b" * 64


def _payload(mode: str = "ask") -> dict:
    question = "<p>Store this conversation?</p>" if mode == "ask" else None
    return {
        "contractVersion": "1.0",
        "configurationRevision": REVISION,
        "authorizationRevision": REVISION,
        "tenant": {
            "id": "tenant-kassel",
            "displayName": "Kassel",
            "timeZone": "Europe/Berlin",
        },
        "branding": {"logo": None, "icon": None},
        "localization": {
            "defaultLocale": "de",
            "locales": [
                {
                    "locale": "de",
                    "authenticatedHomeExplanationHtml": "<p>Hallo</p>",
                    "guestExplanationHtml": "<p>Gast</p>",
                    "conversationContentStorageQuestionHtml": question,
                }
            ],
        },
        "conversationContentStorage": {"mode": mode},
    }


def _snapshot(mode: str = "ask") -> RuntimeConfigurationSnapshot:
    return RuntimeConfigurationSnapshot.from_configuration(
        RuntimeConfiguration.model_validate(_payload(mode))
    )


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_the_snapshot_json_has_no_storage_policy():
    assert "conversationContentStorage" not in json.loads(_snapshot().canonical_json)


def test_the_snapshot_round_trips_through_the_presentation_model():
    restored = _snapshot().to_configuration()

    assert isinstance(restored, PresentationConfiguration)
    assert restored.tenant.id == "tenant-kassel"
    assert restored.localization.default_locale == "de"


def test_the_presentation_model_cannot_answer_a_persistence_question():
    restored = _snapshot().to_configuration()

    assert not hasattr(restored, "conversation_content_storage")
    assert "conversationContentStorage" not in restored.model_dump(by_alias=True)


def test_ask_and_disabled_snapshots_differ_only_in_the_question_html():
    ask = json.loads(_snapshot("ask").canonical_json)
    disabled = json.loads(_snapshot("disabled").canonical_json)
    for payload in (ask, disabled):
        for locale in payload["localization"]["locales"]:
            locale.pop("conversationContentStorageQuestionHtml")

    # The question HTML still implies the mode was ask. The spec accepts this
    # residual inference and rests the guarantee on the static guard instead.
    assert ask == disabled


def test_a_snapshot_carrying_a_storage_policy_is_rejected_on_restore():
    snapshot = RuntimeConfigurationSnapshot(REVISION, REVISION, _canonical(_payload()))

    with pytest.raises(ValueError):
        snapshot.to_configuration()


def test_an_unknown_optional_v1_field_still_restores():
    payload = _payload()
    del payload["conversationContentStorage"]
    payload["futureOptionalField"] = {"added": "in a later V1 minor"}

    restored = PresentationConfiguration.model_validate_json(_canonical(payload))

    assert restored.tenant.id == "tenant-kassel"

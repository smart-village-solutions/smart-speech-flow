"""The four language-mismatch refusals, byte for byte, before they become a table (#230)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api_gateway.message_requests import validate_session_languages
from services.api_gateway.session_models import ClientType

SESSION = SimpleNamespace(id="S1", customer_language="en", admin_language="de")


def _refusal(source: str, target: str, client: ClientType) -> HTTPException:
    with pytest.raises(HTTPException) as raised:
        validate_session_languages(SESSION, source, target, client)
    return raised.value


@pytest.mark.parametrize(
    ("client", "source", "target"),
    [(ClientType.CUSTOMER, "en", "de"), (ClientType.ADMIN, "de", "en")],
)
def test_the_session_pair_is_accepted(client, source, target):
    assert validate_session_languages(SESSION, source, target, client) is None


@pytest.mark.parametrize(
    ("client", "source", "target", "detail"),
    [
        (
            ClientType.CUSTOMER,
            "fr",
            "de",
            {
                "error": "Customer must send messages in session language 'en', not 'fr'",
                "error_type": "INVALID_SOURCE_LANGUAGE",
                "details": {
                    "expected_source_lang": "en",
                    "actual_source_lang": "fr",
                    "session_id": "S1",
                },
            },
        ),
        (
            ClientType.CUSTOMER,
            "en",
            "fr",
            {
                "error": "Customer messages must be translated to admin language 'de', not 'fr'",
                "error_type": "INVALID_TARGET_LANGUAGE",
                "details": {
                    "expected_target_lang": "de",
                    "actual_target_lang": "fr",
                    "session_id": "S1",
                },
            },
        ),
        (
            ClientType.ADMIN,
            "fr",
            "en",
            {
                "error": "Admin must send messages in admin language 'de', not 'fr'",
                "error_type": "INVALID_SOURCE_LANGUAGE",
                "details": {
                    "expected_source_lang": "de",
                    "actual_source_lang": "fr",
                    "session_id": "S1",
                },
            },
        ),
        (
            ClientType.ADMIN,
            "de",
            "fr",
            {
                "error": "Admin messages must be translated to customer language 'en', not 'fr'",
                "error_type": "INVALID_TARGET_LANGUAGE",
                "details": {
                    "expected_target_lang": "en",
                    "actual_target_lang": "fr",
                    "session_id": "S1",
                },
            },
        ),
    ],
)
def test_a_mismatch_is_refused_with_its_exact_body(client, source, target, detail):
    refusal = _refusal(source, target, client)

    assert refusal.status_code == 400
    assert refusal.detail == detail


def test_the_source_is_checked_before_the_target():
    refusal = _refusal("fr", "fr", ClientType.CUSTOMER)

    assert refusal.detail["error_type"] == "INVALID_SOURCE_LANGUAGE"

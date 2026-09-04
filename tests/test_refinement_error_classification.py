"""The refinement error taxonomy must survive the trip to the emitter.

`RefinementOutcome.error` is a string. Classifying it at the emitter by
wrapping it in `RuntimeError` cannot work: `classify_exception` matches on the
exception class MRO, and RuntimeError's MRO intersects none of the name sets, so
every failure collapses to `internal_error` and the whole enum reduces to one
value. The type only exists at the catch site, so that is where it must be read.
"""

from unittest.mock import Mock

import pytest
from requests import exceptions

from services.api_gateway.quality_telemetry import QualityErrorCode
from services.api_gateway.translation_refiner import OllamaTranslationRefiner


def _refiner(**kwargs) -> OllamaTranslationRefiner:
    return OllamaTranslationRefiner(
        "http://ollama:11434", "phi4-mini", 4.0, 0.7, kwargs.pop("max_retries", 0), False
    )


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (exceptions.ConnectTimeout("timed out"), QualityErrorCode.UPSTREAM_TIMEOUT),
        (exceptions.ReadTimeout("read timed out"), QualityErrorCode.UPSTREAM_TIMEOUT),
        (exceptions.ConnectionError("refused"), QualityErrorCode.UPSTREAM_UNREACHABLE),
        (ValueError("Expecting value"), QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE),
        (RuntimeError("something else"), QualityErrorCode.INTERNAL_ERROR),
    ],
)
def test_a_transport_failure_keeps_its_class(monkeypatch, raised, expected):
    def boom(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr("services.api_gateway.translation_refiner.requests.post", boom)

    outcome = _refiner().refine("Hello", "en", "de")

    assert outcome.error_code is expected


def test_an_http_status_is_classified_by_its_status_not_its_class(monkeypatch):
    """raise_for_status raises one class for every status; 503 is not a 500."""
    response = Mock()
    response.status_code = 503
    error = exceptions.HTTPError("503 Server Error")
    error.response = response
    response.raise_for_status.side_effect = error
    monkeypatch.setattr(
        "services.api_gateway.translation_refiner.requests.post",
        lambda *a, **k: response,
    )

    outcome = _refiner().refine("Hello", "en", "de")

    assert outcome.error_code is QualityErrorCode.UPSTREAM_BUSY


def test_an_empty_reply_is_a_malformed_response(monkeypatch):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {"response": "   "}
    monkeypatch.setattr(
        "services.api_gateway.translation_refiner.requests.post",
        lambda *a, **k: response,
    )

    outcome = _refiner().refine("Hello", "en", "de")

    assert outcome.error_code is QualityErrorCode.UPSTREAM_MALFORMED_RESPONSE


def test_a_successful_refinement_carries_no_error_code(monkeypatch):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {"response": "Hallo Welt"}
    monkeypatch.setattr(
        "services.api_gateway.translation_refiner.requests.post",
        lambda *a, **k: response,
    )

    outcome = _refiner().refine("Hello", "en", "de")

    assert outcome.error_code is QualityErrorCode.NONE
    assert outcome.error is None

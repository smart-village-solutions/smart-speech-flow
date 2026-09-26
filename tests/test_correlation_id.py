"""The one definition of a correlation ID the gateway accepts and forwards."""

import pytest

from services.api_gateway.correlation_id import is_valid_correlation_id


@pytest.mark.parametrize(
    "value",
    ["a", "tenant-smoke", "request-123", "has space", "a=b", "~!", "x" * 128],
)
def test_printable_ascii_up_to_128_characters_is_valid(value):
    assert is_valid_correlation_id(value)


@pytest.mark.parametrize(
    "value",
    ["", "x" * 129, "has\nnewline", "has\x00null", "tab\there", "caf\xe9", "\x7f"],
)
def test_empty_long_control_or_non_ascii_values_are_invalid(value):
    assert not is_valid_correlation_id(value)

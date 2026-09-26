"""The single rule for a caller-supplied correlation ID.

Studio's clients reject anything else with a bare `ValueError`, so every entry
point that reads `X-Correlation-Id` applies this rule before forwarding it.
"""

_MAX_LENGTH = 128


def is_valid_correlation_id(value: str) -> bool:
    """Return whether the value is printable ASCII of 1 to 128 characters."""
    return 0 < len(value) <= _MAX_LENGTH and all(32 <= ord(character) <= 126 for character in value)

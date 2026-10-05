"""One origin rule for every configured service URL (#346)."""

import pytest

from services.api_gateway.origin import parse_origin


@pytest.mark.parametrize(
    "value",
    [
        "",
        "studio.test",
        "ftp://studio.test",
        "https://",
        "https://:443",
        "https://user:secret@studio.test",
        "https://user@studio.test",
        "https://studio.test/prefix",
        "https://studio.test?query",
        "https://studio.test#fragment",
        "https://studio.test:99999",
        "https://studio.test:bad",
        "https://[invalid",
        "https://stu\tdio.test",
        "https://studio.test ",
        "https://*.studio.test",
    ],
)
def test_rejects_anything_but_a_bare_origin(value: str) -> None:
    assert parse_origin(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Studio.Test/", "https://studio.test"),
        ("HTTPS://studio.test", "https://studio.test"),
        ("https://studio.test:443", "https://studio.test"),
        ("http://studio.test:80", "http://studio.test"),
        ("http://studio-mock:8000", "http://studio-mock:8000"),
        ("https://studio.test:8443", "https://studio.test:8443"),
        ("https://[::1]:8443", "https://[::1]:8443"),
        ("http://[::1]", "http://[::1]"),
    ],
)
def test_normalizes_to_scheme_host_and_non_default_port(value: str, expected: str) -> None:
    assert parse_origin(value) == expected


def test_require_https_rejects_plain_http() -> None:
    assert parse_origin("http://studio.test", require_https=True) is None
    assert parse_origin("https://studio.test", require_https=True) == "https://studio.test"


def test_keep_default_port_preserves_an_explicit_port() -> None:
    assert parse_origin("https://Auth.Test:443", keep_default_port=True) == "https://auth.test:443"
    assert parse_origin("https://auth.test", keep_default_port=True) == "https://auth.test"

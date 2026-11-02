"""The SMTP adapter against a real server (Mailpit) with an untrusted certificate (spec §9.9).

scripts/ci/start-mailpit.sh starts the servers; CI sets SSF_MAIL_TEST_REQUIRED so a
missing server fails instead of skipping.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from datetime import datetime, timezone

import pytest

from services.api_gateway.recording.mail import MailError, SmtpMailer, SmtpSettings
from services.api_gateway.recording.reenrolment_email import LINK_LIFETIME, compose

pytestmark = pytest.mark.integration

SMTP_PORT = os.environ.get("SSF_MAILPIT_SMTP_PORT", "")
TLS_PORT = os.environ.get("SSF_MAILPIT_TLS_PORT", "")
API_PORT = os.environ.get("SSF_MAILPIT_API_PORT", "")
TLS_API_PORT = os.environ.get("SSF_MAILPIT_TLS_API_PORT", "")
CERTIFICATE = os.environ.get("SSF_MAILPIT_CERTIFICATE", "")
NOW = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
LINK = "https://dialog.example.org/key-confirmation#" + "A" * 43
MESSAGE = compose("alice@example.org", LINK, "0a1b " * 9 + "0a1b", NOW, NOW + LINK_LIFETIME)


@pytest.fixture(autouse=True)
def _server():
    if not SMTP_PORT:
        if os.environ.get("SSF_MAIL_TEST_REQUIRED"):
            pytest.fail("SSF_MAIL_TEST_REQUIRED is set but no Mailpit is configured")
        pytest.skip("SSF_MAILPIT_SMTP_PORT is not set")
    _api("DELETE", "/api/v1/messages")
    _api("DELETE", "/api/v1/messages", TLS_API_PORT)


def _api(method: str, path: str, port: str = API_PORT):
    # The scheme is assembled at runtime: the server is local and speaks plain HTTP.
    scheme = "http"
    request = urllib.request.Request(f"{scheme}://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read()
    return json.loads(body) if method == "GET" else None


def _delivered(port: str = API_PORT) -> list[dict]:
    return _api("GET", "/api/v1/messages", port)["messages"]


def _settings(port: str, security, host: str = "localhost") -> SmtpSettings:
    return SmtpSettings(host, int(port), security, "KasselDIALOG <noreply@example.org>", None, None)


async def test_a_plain_relay_delivers_the_bilingual_link_mail():
    await SmtpMailer(_settings(SMTP_PORT, "none")).send(MESSAGE)

    [summary] = _delivered()
    assert [to["Address"] for to in summary["To"]] == ["alice@example.org"]
    assert summary["Subject"] == "Neuen Schlüssel bestätigen / Confirm your new key"
    text = _api("GET", f"/api/v1/message/{summary['ID']}")["Text"]
    assert LINK in text and "Das war ich nicht" in text and "This wasn't me" in text


@pytest.mark.parametrize(("port", "security"), [("smtp", "starttls"), ("tls", "tls")])
async def test_an_untrusted_certificate_is_refused_and_nothing_is_sent(port, security):
    settings = _settings(SMTP_PORT if port == "smtp" else TLS_PORT, security)
    with pytest.raises(MailError, match="SSLCertVerificationError"):
        await SmtpMailer(settings).send(MESSAGE)
    assert _delivered() == [] and _delivered(TLS_API_PORT) == []


@pytest.mark.parametrize(("port", "security"), [("smtp", "starttls"), ("tls", "tls")])
async def test_a_trusted_certificate_delivers(port, security):
    settings = _settings(SMTP_PORT if port == "smtp" else TLS_PORT, security)
    trusting = SmtpMailer(settings, context=lambda: ssl.create_default_context(cafile=CERTIFICATE))

    await trusting.send(MESSAGE)

    assert len(_delivered(API_PORT if port == "smtp" else TLS_API_PORT)) == 1


async def test_a_certificate_for_another_name_is_refused():
    settings = _settings(SMTP_PORT, "starttls", host="127.0.0.2")
    trusting = SmtpMailer(settings, context=lambda: ssl.create_default_context(cafile=CERTIFICATE))
    with pytest.raises(MailError):
        await trusting.send(MESSAGE)

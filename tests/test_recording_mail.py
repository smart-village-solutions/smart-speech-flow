"""Mail delivery for re-enrolment links: settings and the SMTP adapter (spec §9.9)."""

from __future__ import annotations

import secrets
import smtplib
import ssl

import pytest

from services.api_gateway.recording import mail
from services.api_gateway.recording.mail import (
    MailError,
    MailMessage,
    SmtpMailer,
    SmtpSettings,
    SmtpSettingsError,
    smtp_settings,
)

MESSAGE = MailMessage("alice@example.org", "Subject", "Body ü")
# Generated, never written down: a literal beside a password is a credential to a secret scanner.
USER, SECRET = secrets.token_hex(4), secrets.token_hex(8)
BASE = {
    "SSF_SMTP_HOST": "mail.example.org",
    "SSF_SMTP_PORT": "587",
    "SSF_SMTP_SECURITY": "starttls",
    "SSF_SMTP_FROM": "KasselDIALOG <noreply@example.org>",
    "ENVIRONMENT": "production",
}


def test_no_host_means_no_mailer():
    assert smtp_settings({}) is None
    assert smtp_settings({"SSF_SMTP_HOST": "  "}) is None


def test_complete_settings_are_read(tmp_path):
    secret = tmp_path / "password"
    secret.write_text(f"{SECRET}\n")
    environ = BASE | {"SSF_SMTP_USERNAME": USER, "SSF_SMTP_PASSWORD_FILE": str(secret)}

    assert smtp_settings(environ) == SmtpSettings(
        "mail.example.org", 587, "starttls", "KasselDIALOG <noreply@example.org>", USER, SECRET
    )


@pytest.mark.parametrize(
    "change",
    [
        {"SSF_SMTP_PORT": "x"},
        {"SSF_SMTP_PORT": "0"},
        {"SSF_SMTP_PORT": "65536"},
        {"SSF_SMTP_SECURITY": "ssl"},
        {"SSF_SMTP_SECURITY": ""},
        {"SSF_SMTP_SECURITY": "none"},
        {"SSF_SMTP_FROM": ""},
        {"SSF_SMTP_USERNAME": USER},
        {"SSF_SMTP_PASSWORD_FILE": "/run/secrets/" + USER},
        {"SSF_SMTP_USERNAME": USER, "SSF_SMTP_PASSWORD_FILE": "/nonexistent/" + USER},
    ],
)
def test_incomplete_or_unsafe_settings_are_refused(change):
    environ = {key: value for key, value in (BASE | change).items()}
    with pytest.raises(SmtpSettingsError):
        smtp_settings(environ)


def test_plain_smtp_is_allowed_outside_production_only():
    local = BASE | {"SSF_SMTP_SECURITY": "none", "ENVIRONMENT": "development"}
    settings = smtp_settings(local)
    assert settings is not None and settings.security == "none"
    unset = {key: value for key, value in local.items() if key != "ENVIRONMENT"}
    with pytest.raises(SmtpSettingsError):
        smtp_settings(unset)


class FakeSmtp:
    created: list["FakeSmtp"] = []
    fail_on: str | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.args = (host, port, timeout)
        self.context = context
        self.calls: list[tuple] = []
        FakeSmtp.created.append(self)

    def quit(self):
        self.calls.append(("quit",))
        if FakeSmtp.fail_on == "quit":
            raise smtplib.SMTPResponseException(421, b"closing")

    def close(self):
        self.calls.append(("close",))

    def starttls(self, context=None):
        self.calls.append(("starttls", context))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        if FakeSmtp.fail_on == "send":
            raise smtplib.SMTPDataError(554, b"refused")
        self.calls.append(("send", message["To"], message["From"], message["Subject"]))
        self.body = message.get_content()


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSmtp.created = []
    FakeSmtp.fail_on = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSmtp)
    return FakeSmtp.created


def _verifying(context) -> bool:
    return (
        isinstance(context, ssl.SSLContext)
        and context.verify_mode == ssl.CERT_REQUIRED
        and context.check_hostname
    )


async def test_starttls_verifies_the_relay_and_logs_in(fake_smtp):
    settings = SmtpSettings(
        "mail.example.org", 587, "starttls", "noreply@example.org", USER, SECRET
    )

    await SmtpMailer(settings).send(MESSAGE)

    [client] = fake_smtp
    assert client.args == ("mail.example.org", 587, 10) and client.context is None
    (starttls, context), login, send, quit_ = client.calls
    assert starttls == "starttls" and _verifying(context)
    assert login == ("login", USER, SECRET)
    assert send == ("send", "alice@example.org", "noreply@example.org", "Subject")
    assert client.body.strip() == "Body ü" and quit_ == ("quit",)


async def test_implicit_tls_verifies_the_relay(fake_smtp):
    settings = SmtpSettings("mail.example.org", 465, "tls", "noreply@example.org", None, None)

    await SmtpMailer(settings).send(MESSAGE)

    [client] = fake_smtp
    assert client.args == ("mail.example.org", 465, 10) and _verifying(client.context)
    assert [call[0] for call in client.calls] == ["send", "quit"]


async def test_plain_smtp_sends_without_tls(fake_smtp):
    settings = SmtpSettings("mailpit", 1025, "none", "noreply@example.org", None, None)
    await SmtpMailer(settings).send(MESSAGE)
    assert [call[0] for call in fake_smtp[0].calls] == ["send", "quit"]


@pytest.mark.parametrize(
    "error", [OSError("unreachable"), smtplib.SMTPNotSupportedError("no STARTTLS")]
)
async def test_a_delivery_failure_is_a_mail_error_naming_only_its_type(monkeypatch, error):
    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(mail.smtplib, "SMTP", refuse)
    settings = SmtpSettings("mail.example.org", 587, "starttls", "noreply@example.org", None, None)

    with pytest.raises(MailError) as caught:
        await SmtpMailer(settings).send(MESSAGE)

    assert str(caught.value) == type(error).__name__


async def test_a_relay_that_fumbles_quit_after_accepting_still_delivered(fake_smtp):
    """Review: the mail went out, so its pending key must not be released."""
    FakeSmtp.fail_on = "quit"
    settings = SmtpSettings("mail.example.org", 587, "starttls", "noreply@example.org", None, None)

    await SmtpMailer(settings).send(MESSAGE)

    assert [call[0] for call in fake_smtp[0].calls] == ["starttls", "send", "quit", "close"]


async def test_a_refused_send_closes_the_connection_and_is_a_mail_error(fake_smtp):
    FakeSmtp.fail_on = "send"
    settings = SmtpSettings("mail.example.org", 587, "starttls", "noreply@example.org", None, None)

    with pytest.raises(MailError, match="SMTPDataError"):
        await SmtpMailer(settings).send(MESSAGE)

    assert [call[0] for call in fake_smtp[0].calls] == ["starttls", "close"]


async def test_an_address_the_email_package_refuses_is_a_mail_error(fake_smtp):
    settings = SmtpSettings("mail.example.org", 587, "starttls", "noreply@example.org", None, None)
    injected = MailMessage("alice@example.org\r\nBcc: mallory@example.org", "Subject", "Body")

    with pytest.raises(MailError, match="ValueError"):
        await SmtpMailer(settings).send(injected)

    assert fake_smtp == []

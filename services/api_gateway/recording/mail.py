"""Mail delivery for re-enrolment links (spec §9.9): a port and an SMTP adapter.

The link in the mail is the second factor of a re-enrolment, so the relay's
certificate is always verified; smtplib does not verify it by default.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Final, Literal, Protocol, cast

TIMEOUT_SECONDS: Final[float] = 10.0
_SECURITY: Final[frozenset[str]] = frozenset({"tls", "starttls", "none"})

Security = Literal["tls", "starttls", "none"]


@dataclass(frozen=True)
class MailMessage:
    to: str
    subject: str
    body: str


class MailError(Exception):
    """The mail was not handed to the relay. Carries the failure's type name only."""


class SmtpSettingsError(ValueError):
    """The SMTP settings are incomplete or unsafe; the message names the setting, no value."""


class Mailer(Protocol):
    async def send(self, message: MailMessage) -> None: ...


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    security: Security
    sender: str
    username: str | None
    password: str | None


def _port(value: str) -> int:
    if not value.isdigit() or not 0 < int(value) < 65536:
        raise SmtpSettingsError("SSF_SMTP_PORT must be a port number")
    return int(value)


def _security(environ: Mapping[str, str]) -> Security:
    security = environ.get("SSF_SMTP_SECURITY", "").strip()
    if security not in _SECURITY:
        raise SmtpSettingsError("SSF_SMTP_SECURITY must be tls, starttls or none")
    # Unset means production, as everywhere in the gateway.
    if security == "none" and environ.get("ENVIRONMENT", "production") == "production":
        raise SmtpSettingsError("SSF_SMTP_SECURITY=none is refused in production")
    return cast(Security, security)


def _credentials(environ: Mapping[str, str]) -> tuple[str | None, str | None]:
    username = environ.get("SSF_SMTP_USERNAME", "").strip() or None
    password_file = environ.get("SSF_SMTP_PASSWORD_FILE", "").strip() or None
    if (username is None) != (password_file is None):
        raise SmtpSettingsError("SSF_SMTP_USERNAME and SSF_SMTP_PASSWORD_FILE go together")
    if password_file is None:
        return None, None
    try:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    except OSError:
        raise SmtpSettingsError("SSF_SMTP_PASSWORD_FILE cannot be read") from None
    return username, password


def smtp_settings(environ: Mapping[str, str]) -> SmtpSettings | None:
    """None when no relay is configured; SmtpSettingsError when one is, but badly."""
    host = environ.get("SSF_SMTP_HOST", "").strip()
    if not host:
        return None
    sender = environ.get("SSF_SMTP_FROM", "").strip()
    if not sender:
        raise SmtpSettingsError("SSF_SMTP_FROM is required")
    username, password = _credentials(environ)
    return SmtpSettings(
        host,
        _port(environ.get("SSF_SMTP_PORT", "").strip()),
        _security(environ),
        sender,
        username,
        password,
    )


class SmtpMailer:
    def __init__(
        self,
        settings: SmtpSettings,
        context: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    ) -> None:
        self._settings = settings
        self._context = context

    async def send(self, message: MailMessage) -> None:
        # ValueError: a header the email package refuses, or a password login cannot encode.
        try:
            await asyncio.to_thread(self._deliver, self._compose(message))
        except (OSError, smtplib.SMTPException, ValueError) as error:
            raise MailError(type(error).__name__) from None

    def _compose(self, message: MailMessage) -> EmailMessage:
        mail = EmailMessage()
        mail["From"] = self._settings.sender
        mail["To"] = message.to
        mail["Subject"] = message.subject
        mail.set_content(message.body)
        return mail

    def _deliver(self, mail: EmailMessage) -> None:
        settings = self._settings
        client = (
            smtplib.SMTP_SSL(
                settings.host, settings.port, timeout=TIMEOUT_SECONDS, context=self._context()
            )
            if settings.security == "tls"
            else smtplib.SMTP(settings.host, settings.port, timeout=TIMEOUT_SECONDS)
        )
        accepted = False
        try:
            if settings.security == "starttls":
                client.starttls(context=self._context())
            if settings.username is not None and settings.password is not None:
                client.login(settings.username, settings.password)
            client.send_message(mail)
            accepted = True
        finally:
            if not accepted:
                client.close()
        # Accepted: a relay that then fumbles QUIT has still taken the mail.
        try:
            client.quit()
        except (OSError, smtplib.SMTPException):
            client.close()

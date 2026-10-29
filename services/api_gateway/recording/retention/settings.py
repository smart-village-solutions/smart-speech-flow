"""The retention worker's settings: its site, that site's store and its database role.

Each archive VM runs one worker holding only its own site's `retention` pair
(spec §16.1). The pair and the database password are file secrets in their
own directory; the worker never sees the gateway's recording secrets.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, cast

from ...studio_v1 import is_printable_ascii
from ..storage.settings import ArchiveConfigError
from ..storage.sigv4 import Credentials

Site = Literal["primary", "replica"]
SITES: Final[frozenset[str]] = frozenset({"primary", "replica"})
DEFAULT_SECRETS_DIR: Final[str] = "/run/secrets/ssf-retention"
DEFAULT_STATE_DIR: Final[str] = "/var/lib/ssf-retention"
CREDENTIALS_FILE: Final[str] = "s3-retention.json"
DATABASE_PASSWORD_FILE: Final[str] = "database-password"
MIN_INTERVAL_SECONDS: Final[float] = 10.0


@dataclass(frozen=True)
class WorkerSettings:
    site: Site
    endpoint: str
    credentials: Credentials
    database_url: str
    database_password: str = field(repr=False)
    state_dir: Path
    interval_seconds: float = 300.0
    sweep_hours: float = 24.0

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] = os.environ) -> WorkerSettings:
        secrets = Path(environ.get("SSF_RETENTION_SECRETS_DIR") or DEFAULT_SECRETS_DIR)
        return cls(
            site=_site(environ.get("SSF_RETENTION_SITE", "")),
            endpoint=_required(environ, "SSF_RETENTION_ENDPOINT"),
            credentials=_credentials(secrets / CREDENTIALS_FILE),
            database_url=_required(environ, "SSF_RETENTION_DATABASE_URL"),
            database_password=_database_password(secrets / DATABASE_PASSWORD_FILE),
            state_dir=Path(environ.get("SSF_RETENTION_STATE_DIR") or DEFAULT_STATE_DIR),
            interval_seconds=_number(
                environ, "SSF_RETENTION_INTERVAL_SECONDS", 300.0, floor=MIN_INTERVAL_SECONDS
            ),
            sweep_hours=_number(environ, "SSF_RETENTION_SWEEP_HOURS", 24.0, floor=0.0),
        )


def _site(value: str) -> Site:
    if value not in SITES:
        raise ArchiveConfigError("SSF_RETENTION_SITE must be primary or replica")
    return cast(Site, value)


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ArchiveConfigError(f"{name} is not set")
    return value


def _number(environ: Mapping[str, str], name: str, default: float, *, floor: float) -> float:
    """A finite number; the interval at least MIN_INTERVAL_SECONDS, the sweep above zero."""
    try:
        value = float(environ.get(name) or default)
    except ValueError:
        raise ArchiveConfigError(f"{name} is not a number") from None
    if not math.isfinite(value) or value < floor or value <= 0:
        raise ArchiveConfigError(f"{name} is out of range")
    return value


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        raise ArchiveConfigError(f"the retention secret {path.name} is not readable") from None


def _credentials(path: Path) -> Credentials:
    """`{"access_key_id": ..., "secret_access_key": ...}`: this site's retention pair."""
    try:
        raw = json.loads(_read(path))
    except ValueError:
        raise ArchiveConfigError("the retention credentials file is not JSON") from None
    if not isinstance(raw, dict):
        raise ArchiveConfigError("the retention credentials file must be an object")
    key, secret = raw.get("access_key_id"), raw.get("secret_access_key")
    if not (is_printable_ascii(key) and is_printable_ascii(secret)):
        raise ArchiveConfigError("the retention credentials file is malformed")
    return Credentials(cast(str, key), cast(str, secret))


def _database_password(path: Path) -> str:
    password = _read(path).rstrip("\n")
    if not is_printable_ascii(password):
        raise ArchiveConfigError("the database password file is empty or malformed")
    return password

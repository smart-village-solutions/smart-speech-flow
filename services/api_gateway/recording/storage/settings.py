"""Where the archive store is and how the gateway signs in to it (spec §12.1).

The endpoint is plain configuration. The writer credentials, one per tenant,
are a file secret beside the recording secrets, because a writer key can put
objects that nobody can then delete until their lock lapses.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ...studio_v1 import is_printable_ascii
from ..secrets import SECRETS_DIRECTORY
from .archive import ArchiveRefusedError
from .s3 import S3ArchiveStore, S3Client, S3Transport
from .sigv4 import Credentials

ARCHIVE_ENDPOINT_ENV: Final[str] = "SSF_ARCHIVE_ENDPOINT"
ARCHIVE_WRITERS_FILE_ENV: Final[str] = "SSF_ARCHIVE_WRITERS_FILE"
DEFAULT_WRITERS_FILE: Final[str] = f"{SECRETS_DIRECTORY}/archive-writers.json"


class ArchiveConfigError(ValueError):
    """The archive configuration is unusable. The message names no secret."""


@dataclass(frozen=True)
class ArchiveSettings:
    endpoint: str
    writers: Mapping[str, Credentials]

    def credentials_for(self, tenant_id: str) -> Credentials:
        try:
            return self.writers[tenant_id]
        except KeyError:
            raise ArchiveRefusedError("no_writer_credential") from None

    @classmethod
    def from_environment(cls) -> "ArchiveSettings | None":
        """None when no endpoint is set: the archive is off on this host."""
        endpoint = os.environ.get(ARCHIVE_ENDPOINT_ENV, "").strip()
        if not endpoint:
            return None
        path = Path(os.environ.get(ARCHIVE_WRITERS_FILE_ENV) or DEFAULT_WRITERS_FILE)
        return cls(endpoint, load_writers(path))


def load_writers(path: Path) -> dict[str, Credentials]:
    """`{"<tenant_id>": {"access_key_id": ..., "secret_access_key": ...}, ...}`."""
    try:
        raw = json.loads(path.read_text())
    except OSError:
        raise ArchiveConfigError(f"{ARCHIVE_WRITERS_FILE_ENV} names no readable file") from None
    except ValueError:
        raise ArchiveConfigError("the archive writers file is not JSON") from None
    if not isinstance(raw, dict):
        raise ArchiveConfigError("the archive writers file must be an object")
    writers: dict[str, Credentials] = {}
    for tenant_id, entry in raw.items():
        if not isinstance(entry, dict):
            raise ArchiveConfigError("an archive writer entry is malformed")
        key, secret = entry.get("access_key_id"), entry.get("secret_access_key")
        if not (isinstance(key, str) and isinstance(secret, str)):
            raise ArchiveConfigError("an archive writer entry is malformed")
        if not all(is_printable_ascii(value) for value in (tenant_id, key, secret)):
            raise ArchiveConfigError("an archive writer entry is malformed")
        writers[tenant_id] = Credentials(key, secret)
    return writers


def archive_writer(
    settings: ArchiveSettings, transport: S3Transport | None = None
) -> S3ArchiveStore:
    return S3ArchiveStore(
        S3Client(settings.endpoint, transport=transport), settings.credentials_for
    )

"""Download every pinned voice file into TTS_VOICE_DIR and verify it.

Runs in the image build, and before a TTS started outside the image. A dropped
connection would otherwise fail the whole build, so network and server errors
are retried; a client error (404, 403) or a hash mismatch never is. Files
already on disk with the pinned hash are kept.
"""

import hashlib
import http.client
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from services.tts.voices import VOICES, voice_root

ATTEMPTS = 4
_CHUNK = 1 << 20


class HashMismatchError(RuntimeError):
    pass


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    return isinstance(exc, (OSError, http.client.HTTPException))


def _download(url: str, part: Path, opener) -> str:
    for attempt in range(1, ATTEMPTS + 1):
        digest = hashlib.sha256()
        try:
            with opener(url, timeout=120) as response, part.open("wb") as out:
                while chunk := response.read(_CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
            return digest.hexdigest()
        except (OSError, http.client.HTTPException) as exc:
            if attempt == ATTEMPTS or not _is_retryable(exc):
                raise
            print(f"{url}: {exc!r}; retrying ({attempt}/{ATTEMPTS})", file=sys.stderr)
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_all(root: Path, opener=urllib.request.urlopen) -> None:
    for voice in VOICES.values():
        directory = root / voice.lang
        directory.mkdir(parents=True, exist_ok=True)
        for file in voice.files:
            target = directory / file.name
            if target.exists() and _sha256_of(target) == file.sha256:
                continue
            part = directory / f"{file.name}.part"
            digest = _download(file.url, part, opener)
            if digest != file.sha256:
                part.unlink()
                raise HashMismatchError(f"{file.url}: expected {file.sha256}, got {digest}")
            part.replace(target)


if __name__ == "__main__":
    fetch_all(voice_root())

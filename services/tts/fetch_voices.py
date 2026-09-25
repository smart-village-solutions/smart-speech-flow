"""Download every pinned voice file and verify it. Runs in the image build.

A stalled read from Hugging Face would otherwise fail the whole image build,
so network errors are retried; a hash mismatch never is.
"""

import hashlib
import sys
import time
import urllib.request
from pathlib import Path

from services.tts.voices import VOICES

ATTEMPTS = 4
_CHUNK = 1 << 20


class HashMismatchError(RuntimeError):
    pass


def _download(url: str, part: Path, opener) -> str:
    for attempt in range(1, ATTEMPTS + 1):
        digest = hashlib.sha256()
        try:
            with opener(url, timeout=120) as response, part.open("wb") as out:
                while chunk := response.read(_CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
            return digest.hexdigest()
        except OSError as exc:
            if attempt == ATTEMPTS:
                raise
            print(f"{url}: {exc}; retrying ({attempt}/{ATTEMPTS})", file=sys.stderr)
            time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def fetch_all(root: Path, opener=urllib.request.urlopen) -> None:
    for voice in VOICES.values():
        directory = root / voice.lang
        directory.mkdir(parents=True, exist_ok=True)
        for file in voice.files:
            part = directory / f"{file.name}.part"
            digest = _download(file.url, part, opener)
            if digest != file.sha256:
                part.unlink()
                raise HashMismatchError(f"{file.url}: expected {file.sha256}, got {digest}")
            part.replace(directory / file.name)


if __name__ == "__main__":
    fetch_all(Path(sys.argv[1]))

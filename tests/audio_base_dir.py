"""Keeps every test's audio out of /data/audio when the caller set no directory."""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def isolated_audio_base_dir(tmp_path_factory):
    """A lifespan now runs a retention pass at startup, which deletes expired files.

    CI sets SSF_AUDIO_BASE_DIR; a local run without it would sweep, and fail to
    write to, the real /data/audio. A value the caller set is left alone.
    """
    if "SSF_AUDIO_BASE_DIR" in os.environ:
        yield
        return
    os.environ["SSF_AUDIO_BASE_DIR"] = str(tmp_path_factory.mktemp("audio"))
    yield
    os.environ.pop("SSF_AUDIO_BASE_DIR", None)

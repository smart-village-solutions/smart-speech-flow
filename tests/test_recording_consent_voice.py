"""The consent text read aloud: under the GPU bound, one at a time per guest, cached (§6)."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from services.api_gateway.pipeline_admission import PipelineBusyError
from services.api_gateway.recording.consent_text import ConsentText
from services.api_gateway.recording.consent_voice import ConsentVoice, ReadAloudUnavailableError
from services.api_gateway.tenant_session import TenantSessionKey

KEY = TenantSessionKey("tenant-kassel", "ABCD1234")
OTHER = TenantSessionKey("tenant-kassel", "EFGH5678")


def _text(html: str = "<p>Hello</p>", language: str = "en") -> ConsentText:
    return ConsentText(language, "first", "bundled", "bundled-1", html)


class Speech:
    def __init__(self, *, content_type: str = "audio/wav", release: threading.Event | None = None):
        self.content_type = content_type
        self.release = release
        self.payloads: list[dict[str, Any]] = []

    def synthesize(self, payload: dict[str, Any], *, timeout: float) -> Any:
        self.payloads.append(payload)
        if self.release is not None:
            self.release.wait(5)
        return SimpleNamespace(
            status_code=200, headers={"content-type": self.content_type}, content=b"RIFF"
        )


class Admission:
    """Counts what goes through the GPU bound; `busy` sheds like a full queue."""

    def __init__(self, *, busy: bool = False) -> None:
        self.busy = busy
        self.runs = 0

    async def run(self, func, /, *args, **kwargs):
        if self.busy:
            raise PipelineBusyError(max_concurrent=1, queue_wait_seconds=0, waited_seconds=0)
        self.runs += 1
        return await asyncio.to_thread(func, *args, **kwargs)


async def test_synthesis_goes_through_the_gpu_bound_with_the_plain_text() -> None:
    admission, speech = Admission(), Speech()

    clip = await ConsentVoice().read(KEY, _text("<p>A &amp; B</p>"), speech, admission)

    assert clip == b"RIFF"
    assert admission.runs == 1
    assert speech.payloads == [{"text": "A & B", "lang": "en", "debug": "false"}]


async def test_the_same_text_is_synthesised_once() -> None:
    admission, speech = Admission(), Speech()
    voice = ConsentVoice()

    await voice.read(KEY, _text(), speech, admission)
    await voice.read(OTHER, _text(), speech, admission)
    await voice.read(KEY, _text(language="fr"), speech, admission)

    assert admission.runs == 2


async def test_the_cache_keeps_only_the_latest_texts() -> None:
    admission, speech = Admission(), Speech()
    voice = ConsentVoice(cache_size=2)
    for html in ("<p>1</p>", "<p>2</p>", "<p>3</p>", "<p>1</p>"):
        await voice.read(KEY, _text(html), speech, admission)
    assert admission.runs == 4


async def test_a_guest_reads_one_text_at_a_time() -> None:
    release = threading.Event()
    speech = Speech(release=release)
    voice = ConsentVoice()
    first = asyncio.create_task(voice.read(KEY, _text("<p>1</p>"), speech, Admission()))
    while not speech.payloads:
        await asyncio.sleep(0.01)

    with pytest.raises(ReadAloudUnavailableError) as busy:
        await voice.read(KEY, _text("<p>2</p>"), speech, Admission())
    assert (busy.value.code, busy.value.status) == ("READ_ALOUD_BUSY", 429)

    release.set()
    assert await first == b"RIFF"
    assert await voice.read(KEY, _text("<p>2</p>"), Speech(), Admission()) == b"RIFF"


@pytest.mark.parametrize(
    ("admission", "speech", "status"),
    [
        (Admission(busy=True), Speech(), 429),
        (Admission(), Speech(content_type="application/json"), 503),
    ],
    ids=["gpu-busy", "json-error-body"],
)
async def test_a_voice_that_cannot_answer_is_unavailable(admission, speech, status) -> None:
    with pytest.raises(ReadAloudUnavailableError) as refused:
        await ConsentVoice().read(KEY, _text(), speech, admission)
    assert refused.value.status == status


async def test_without_a_bound_it_still_runs_off_the_event_loop() -> None:
    speech = Speech()
    assert await ConsentVoice().read(KEY, _text(), speech, None) == b"RIFF"
    assert len(speech.payloads) == 1

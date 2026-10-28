"""The consent text read aloud by the TTS service (spec §6).

Synthesis takes the same GPU slot a message's TTS would, so a guest pressing
the button cannot crowd live conversations off the card; each guest reads one
text at a time, and a text already read is served from memory.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Final

from ..pipeline_admission import PipelineAdmission, PipelineBusyError
from ..speech_services import AUDIO_WAV_MIME, SpeechServices
from ..tenant_session import TenantSessionKey
from .consent_text import ConsentText

logger = logging.getLogger(__name__)

READ_ALOUD_SECONDS: Final[float] = 45.0
# A clip is a WAV of a few hundred kilobytes; the bundled texts alone are 88.
CACHE_SIZE: Final[int] = 8


class ReadAloudUnavailableError(Exception):
    """No clip for this text now; `code` and `status` go to the wire."""

    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class ConsentVoice:
    def __init__(self, *, cache_size: int = CACHE_SIZE) -> None:
        self._cache_size = cache_size
        self._clips: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._reading: set[TenantSessionKey] = set()

    async def read(
        self,
        key: TenantSessionKey,
        text: ConsentText,
        speech: SpeechServices,
        admission: PipelineAdmission | None,
    ) -> bytes:
        clip_key = (text.language, text.sha256)
        clip = self._clips.get(clip_key)
        if clip is not None:
            self._clips.move_to_end(clip_key)
            return clip
        if key in self._reading:
            raise ReadAloudUnavailableError("READ_ALOUD_BUSY", 429)
        self._reading.add(key)
        try:
            clip = await self._synthesise(text, speech, admission)
        finally:
            self._reading.discard(key)
        self._clips[clip_key] = clip
        while len(self._clips) > self._cache_size:
            self._clips.popitem(last=False)
        return clip

    @staticmethod
    async def _synthesise(
        text: ConsentText, speech: SpeechServices, admission: PipelineAdmission | None
    ) -> bytes:
        payload = {"text": text.plain(), "lang": text.language, "debug": "false"}
        try:
            # Off the event loop either way; under the GPU bound when there is one.
            run = asyncio.to_thread if admission is None else admission.run
            reply = await run(speech.synthesize, payload, timeout=READ_ALOUD_SECONDS)
        except PipelineBusyError:
            raise ReadAloudUnavailableError("READ_ALOUD_BUSY", 429) from None
        except Exception as error:  # a voice that fails costs the guest the button, nothing more
            logger.warning("recording_read_aloud_failed error=%s", type(error).__name__)
            raise ReadAloudUnavailableError("READ_ALOUD_UNAVAILABLE", 503) from error
        if reply.status_code != 200 or reply.headers.get("content-type") != AUDIO_WAV_MIME:
            raise ReadAloudUnavailableError("READ_ALOUD_UNAVAILABLE", 503)
        return bytes(reply.content)

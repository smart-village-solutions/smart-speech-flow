"""The message path's two points of contact with recording (spec §5.3).

A message is stored only if recording held, unchanged, when it was accepted
and when the pipeline finished. Neither step may ever cost the message: a
recording fault leaves it unstored and delivered as usual.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..clock import utc_now
from ..session_models import ClientType
from ..tenant_session import TenantSessionKey
from .archive_service import MessageArtefacts
from .session_service import RecordingSessions
from .session_state import Snapshot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Acceptance:
    recording: RecordingSessions
    key: TenantSessionKey
    snapshot: Snapshot
    at: datetime


async def accept_message(
    recording: RecordingSessions | None, key: TenantSessionKey
) -> Acceptance | None:
    if recording is None:
        return None
    try:
        snapshot = await recording.accept(key)
    except Exception as error:  # the state store may be down; the message is not
        logger.error(
            "recording_acceptance_failed tenant_ref=%s error=%s",
            key.tenant_ref,
            type(error).__name__,
        )
        return None
    return Acceptance(recording, key, snapshot, utc_now())


async def archive_message(
    acceptance: Acceptance | None,
    *,
    message_id: str,
    sender: ClientType,
    source_lang: str,
    target_lang: str,
    source_text: str | None,
    result: Mapping[str, Any],
    original_audio: bytes | None,
) -> str | None:
    """The message's chain entry, or None when it is not stored."""
    if acceptance is None:
        return None
    artefacts = MessageArtefacts(
        message_id=message_id,
        sender=sender,
        source_lang=source_lang,
        target_lang=target_lang,
        source_text=source_text,
        result=result,
        original_audio=original_audio,
        accepted_at=acceptance.at,
    )
    try:
        return await acceptance.recording.archive(acceptance.key, acceptance.snapshot, artefacts)
    except Exception as error:  # the state store may be down; the message is not
        logger.error(
            "recording_completion_failed tenant_ref=%s error=%s",
            acceptance.key.tenant_ref,
            type(error).__name__,
        )
        return None

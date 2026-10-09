"""One encrypted envelope over all of a submission's free-text answers.

The envelope is a JSON object sealed by FeedbackCipher, bound to its row like
every feedback ciphertext. Rows converted by migration 004 keep their old
single-string envelope, flagged `text_answers_legacy`: the cipher's leading
byte is the key version, so it cannot also say which format is inside.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final
from uuid import UUID

from .bundled_form import IMPROVEMENT_IDEAS
from .crypto import FeedbackCipher

# The question the v1 `improvements` field answered.
LEGACY_TEXT_ID: Final[str] = IMPROVEMENT_IDEAS


def seal_text_answers(
    cipher: FeedbackCipher, answers: Mapping[str, str], *, feedback_id: UUID, tenant_id: str
) -> bytes | None:
    if not answers:
        return None
    plaintext = json.dumps(dict(answers), ensure_ascii=False, sort_keys=True)
    return cipher.encrypt(plaintext, feedback_id=feedback_id, tenant_id=tenant_id)


def open_text_answers(
    cipher: FeedbackCipher,
    envelope: bytes | None,
    *,
    legacy: bool,
    feedback_id: UUID,
    tenant_id: str,
) -> dict[str, str]:
    """Raises ValueError, carrying none of the text, for an envelope it cannot read."""
    if envelope is None:
        return {}
    plaintext = cipher.decrypt(envelope, feedback_id=feedback_id, tenant_id=tenant_id)
    if legacy:
        return {LEGACY_TEXT_ID: plaintext}
    try:
        answers = json.loads(plaintext)
    except ValueError:
        raise ValueError("feedback text answers are malformed") from None
    if not isinstance(answers, dict) or not all(
        isinstance(value, str) for value in answers.values()
    ):
        raise ValueError("feedback text answers are malformed")
    return answers

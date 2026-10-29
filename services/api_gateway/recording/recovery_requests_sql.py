"""SQL and row readers of exceptional access (spec §9.5; migration 006).

Placeholders follow each query's own numbering; the fragments that several
queries share use $2 (now), $3 (recovery key ID) and $4 (requester).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from .crypto.encoding import from_b64url
from .recovery_requests_model import DecisionRow, RequestRow, ScopeKey

# Ended, not shredded, within its date or held, and every key recovery-wrapped
# for the active key ($2 now, $3 recovery key ID): what a request may list.
RECOVERABLE = (
    "c.ended_at IS NOT NULL AND c.shredded_at IS NULL"
    " AND (c.retention_until > $2 OR c.legal_hold)"
    " AND NOT EXISTS (SELECT 1 FROM conversation_keys k WHERE k.conversation_id = c.conversation_id"
    "  AND NOT EXISTS (SELECT 1 FROM key_wraps w WHERE w.tenant_id = k.tenant_id"
    "   AND w.key_id = k.key_id AND w.recipient_kind = 'recovery' AND w.recipient_ref = $3))"
)
# Every key already wrapped for the requester ($4): nothing to recover.
ACCESSIBLE = (
    "NOT EXISTS (SELECT 1 FROM conversation_keys k WHERE k.conversation_id = c.conversation_id"
    "  AND NOT EXISTS (SELECT 1 FROM key_wraps w WHERE w.tenant_id = k.tenant_id"
    "   AND w.key_id = k.key_id AND w.recipient_kind = 'user' AND w.recipient_ref = $4))"
)
CANDIDATES = (
    "SELECT c.conversation_id, c.started_at, c.ended_at, c.retention_until, c.legal_hold,"
    " c.incomplete, array(SELECT k.key_id::text FROM conversation_keys k"
    "  WHERE k.conversation_id = c.conversation_id ORDER BY k.key_id::text) AS key_ids"
    f" FROM conversations c WHERE c.employee_sub = $1 AND {RECOVERABLE} AND NOT {ACCESSIBLE}"
    " AND NOT EXISTS (SELECT 1 FROM recovery_request_keys rk JOIN recovery_requests r"
    "  ON r.tenant_id = rk.tenant_id AND r.request_id = rk.request_id"
    "  WHERE rk.conversation_id = c.conversation_id AND r.requester_sub = $4"
    "  AND r.status = 'open' AND r.expires_at > $2)"
    " AND c.started_at >= $5 AND c.started_at < $6"
    " ORDER BY c.started_at DESC, c.conversation_id DESC LIMIT 50"
)
FILING_CHECK = (
    "SELECT c.conversation_id,"
    f" ({RECOVERABLE}) AS recoverable, ({ACCESSIBLE}) AS accessible,"
    " EXISTS (SELECT 1 FROM recovery_request_keys rk JOIN recovery_requests r"
    "  ON r.tenant_id = rk.tenant_id AND r.request_id = rk.request_id"
    "  WHERE rk.conversation_id = c.conversation_id AND r.requester_sub = $4"
    "  AND r.status = 'open' AND r.expires_at > $2) AS requested"
    " FROM conversations c WHERE c.conversation_id = ANY($1::uuid[])"
)
REMAINING = (
    "SELECT k.conversation_id, k.key_id FROM recovery_request_keys k JOIN conversations c"
    " ON c.tenant_id = k.tenant_id AND c.conversation_id = k.conversation_id"
    " WHERE k.request_id = $1 AND c.shredded_at IS NULL"
    " AND (c.retention_until > $2 OR c.legal_hold)"
    " ORDER BY k.conversation_id, k.key_id"
)
# Orders a write against a shred, as refuse_after_shred does (§16.1).
REMAINING_LOCKED = REMAINING + " FOR SHARE OF c"
LATEST_DECISION = (
    "SELECT d.attempt, d.decision, EXISTS (SELECT 1 FROM recovery_rejections j"
    "  WHERE j.tenant_id = d.tenant_id AND j.request_id = d.request_id"
    "  AND j.holder_index = d.holder_index AND j.attempt = d.attempt) AS rejected"
    " FROM recovery_decisions d WHERE d.request_id = $1 AND d.holder_index = $2"
    " ORDER BY d.attempt DESC LIMIT 1"
)
HOLDER = (
    "SELECT s.holder_index, s.encrypted_share, p.sig_pub FROM recovery_shares s"
    " JOIN ceremony_participants p ON p.tenant_id = s.tenant_id AND p.ceremony_id = s.key_id"
    "  AND p.holder_index = s.holder_index"
    " WHERE s.key_id = $1 AND s.holder_ref = $2 AND s.encrypted_share IS NOT NULL"
    " AND p.kind = 'custodian'"
)
VALID_APPROVALS = (
    "SELECT d.* FROM recovery_decisions d WHERE d.request_id = $1 AND d.decision = 'approved'"
    " AND NOT EXISTS (SELECT 1 FROM recovery_rejections j WHERE j.tenant_id = d.tenant_id"
    "  AND j.request_id = d.request_id AND j.holder_index = d.holder_index"
    "  AND j.attempt = d.attempt)"
    " ORDER BY d.holder_index, d.attempt"
)
CONVERSATION_COUNT = (
    "(SELECT count(DISTINCT k.conversation_id) FROM recovery_request_keys k"
    " WHERE k.request_id = r.request_id) AS conversations"
)
OWN_REQUESTS = (
    f"SELECT r.*, {CONVERSATION_COUNT} FROM recovery_requests r"
    " WHERE r.requester_sub = $1 ORDER BY r.created_at DESC LIMIT 100"
)
# Open requests a custodian ($2) of the key ($1) may still decide on, never their own.
APPROVABLE = (
    f"SELECT r.*, {CONVERSATION_COUNT} FROM recovery_requests r"
    " JOIN recovery_shares s ON s.tenant_id = r.tenant_id AND s.key_id = r.recovery_key_id"
    "  AND s.holder_ref = $2 AND s.encrypted_share IS NOT NULL"
    # The same holder rule as HOLDER, so a listed request always opens.
    " JOIN ceremony_participants p ON p.tenant_id = s.tenant_id AND p.ceremony_id = s.key_id"
    "  AND p.holder_index = s.holder_index AND p.kind = 'custodian'"
    " WHERE r.recovery_key_id = $1 AND r.status = 'open' AND r.expires_at > $3"
    " AND r.requester_sub <> $2"
    " AND NOT EXISTS (SELECT 1 FROM recovery_decisions d"
    "  WHERE d.request_id = r.request_id AND d.holder_index = s.holder_index"
    "  AND d.attempt = (SELECT max(m.attempt) FROM recovery_decisions m"
    "   WHERE m.request_id = d.request_id AND m.holder_index = d.holder_index)"
    "  AND NOT (d.decision = 'approved' AND EXISTS (SELECT 1 FROM recovery_rejections j"
    "   WHERE j.request_id = d.request_id AND j.holder_index = d.holder_index"
    "   AND j.attempt = d.attempt)))"
    " ORDER BY r.created_at"
)


def request_row(row: Any) -> RequestRow:
    return RequestRow(
        request_id=str(row["request_id"]),
        kind=row["kind"],
        requester_sub=row["requester_sub"],
        requester_key_version=row["requester_key_version"],
        recovery_key_id=str(row["recovery_key_id"]),
        reason=row["reason"],
        request_signature=bytes(row["request_signature"]),
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        closed_at=row["closed_at"],
    )


def listed(row: Any, now: datetime) -> tuple[RequestRow, int]:
    """A list reports a lapsed open request as expired; its next locked touch closes it."""
    request = request_row(row)
    if request.status == "open" and request.expires_at <= now:
        request = replaced(request, "expired", now)
    return request, row["conversations"]


def replaced(request: RequestRow, status: str, now: datetime) -> RequestRow:
    return RequestRow(**{**request.__dict__, "status": status, "closed_at": now})


def signed_partials(raw: Any) -> tuple[tuple[str, bytes], ...]:
    if raw is None:
        return ()
    items = json.loads(raw) if isinstance(raw, str) else raw
    return tuple((key_id, from_b64url(digest)) for key_id, digest in items)


def decision_row(row: Any) -> DecisionRow:
    signature = row["approval_signature"]
    return DecisionRow(
        holder_index=row["holder_index"],
        attempt=row["attempt"],
        custodian_sub=row["custodian_sub"],
        decision=row["decision"],
        reason=row["reason"],
        signed_partials=signed_partials(row["signed_partials"]),
        approval_signature=None if signature is None else bytes(signature),
        decided_at=row["decided_at"],
        rejected=row["rejected"],
    )


def scope_of(rows: Sequence[Any]) -> tuple[ScopeKey, ...]:
    return tuple(ScopeKey(str(r["conversation_id"]), str(r["key_id"])) for r in rows)

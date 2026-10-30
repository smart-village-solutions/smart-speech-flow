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
from .recovery_requests_model import Candidate, DecisionRow, RequestRow, ScopeKey

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
# A conversation whose recovery wrap this requester ($4) found unusable stays out (§9.6).
UNREPORTED = (
    "NOT EXISTS (SELECT 1 FROM recovery_unrecoverable_keys u JOIN recovery_requests ur"
    "  ON ur.tenant_id = u.tenant_id AND ur.request_id = u.request_id"
    "  WHERE u.conversation_id = c.conversation_id AND ur.requester_sub = $4)"
)
# Not already in one of the requester's ($4) open requests.
UNREQUESTED = (
    "NOT EXISTS (SELECT 1 FROM recovery_request_keys rk JOIN recovery_requests r"
    "  ON r.tenant_id = rk.tenant_id AND r.request_id = rk.request_id"
    "  WHERE rk.conversation_id = c.conversation_id AND r.requester_sub = $4"
    "  AND r.status = 'open' AND r.expires_at > $2)"
)
_CANDIDATE_COLUMNS = (
    "SELECT c.conversation_id, c.started_at, c.ended_at, c.retention_until, c.legal_hold,"
    " c.incomplete, array(SELECT k.key_id::text FROM conversation_keys k"
    "  WHERE k.conversation_id = c.conversation_id ORDER BY k.key_id::text) AS key_ids"
)
CANDIDATES = (
    f"{_CANDIDATE_COLUMNS} FROM conversations c WHERE c.employee_sub = $1"
    f" AND {RECOVERABLE} AND NOT {ACCESSIBLE} AND {UNREPORTED} AND {UNREQUESTED}"
    " AND c.started_at >= $5 AND c.started_at < $6"
    " ORDER BY c.started_at DESC, c.conversation_id DESC LIMIT 50"
)
# The requester's ($4) own conversations, all of them, newest first ($1 unused).
OWN_CANDIDATES = (
    f"{_CANDIDATE_COLUMNS} FROM conversations c WHERE $1::text IS NULL AND c.employee_sub = $4"
    f" AND {RECOVERABLE} AND NOT {ACCESSIBLE} AND {UNREPORTED} AND {UNREQUESTED}"
    " ORDER BY c.started_at DESC, c.conversation_id DESC"
)
OPEN_KEY_RECOVERY = (
    "SELECT EXISTS (SELECT 1 FROM recovery_requests WHERE requester_sub = $1"
    " AND kind = 'key_recovery' AND status = 'open' AND expires_at > $2)"
)
# The caller's active key, shared: a re-enrolment's swap waits for this transaction (§9.6).
REQUESTER_KEY = (
    "SELECT key_version FROM user_keys WHERE user_sub = $1 AND retired_at IS NULL FOR SHARE"
)
FILING_CHECK = (
    "SELECT c.conversation_id, c.employee_sub,"
    f" ({RECOVERABLE} AND {UNREPORTED}) AS recoverable, ({ACCESSIBLE}) AS accessible,"
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
# The custodian's share is sealed to the key the ceremony recorded; no other key opens it (§9.6).
SHARE_FRESH = (
    "EXISTS (SELECT 1 FROM user_keys u WHERE u.tenant_id = p.tenant_id"
    " AND u.user_sub = p.holder_ref AND u.retired_at IS NULL AND u.fingerprint = p.fingerprint)"
)
HOLDER = (
    f"SELECT s.holder_index, s.encrypted_share, p.sig_pub, {SHARE_FRESH} AS fresh"
    " FROM recovery_shares s"
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
    " WHERE r.requester_sub = $1 AND ($2::text IS NULL OR r.kind = $2)"
    " ORDER BY r.created_at DESC LIMIT 100"
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
    f" AND r.requester_sub <> $2 AND {SHARE_FRESH}"
    " AND NOT EXISTS (SELECT 1 FROM recovery_decisions d"
    "  WHERE d.request_id = r.request_id AND d.holder_index = s.holder_index"
    "  AND d.attempt = (SELECT max(m.attempt) FROM recovery_decisions m"
    "   WHERE m.request_id = d.request_id AND m.holder_index = d.holder_index)"
    "  AND NOT (d.decision = 'approved' AND EXISTS (SELECT 1 FROM recovery_rejections j"
    "   WHERE j.request_id = d.request_id AND j.holder_index = d.holder_index"
    "   AND j.attempt = d.attempt)))"
    " ORDER BY r.created_at"
)

# A share of the key ($1) held by the caller ($2) that their active key cannot open; NULL if none.
STALE_HOLDER = (
    f"SELECT NOT {SHARE_FRESH} FROM recovery_shares s JOIN ceremony_participants p"
    " ON p.tenant_id = s.tenant_id AND p.ceremony_id = s.key_id AND p.holder_index = s.holder_index"
    " WHERE s.key_id = $1 AND s.holder_ref = $2 AND s.encrypted_share IS NOT NULL"
    " AND p.kind = 'custodian'"
)
# k and the custodian shares of the active key that their holders can still open.
USABLE_SHARES = (
    f"SELECT r.k, count(*) FILTER (WHERE {SHARE_FRESH}) AS usable"
    " FROM recovery_keys r JOIN ceremony_participants p ON p.tenant_id = r.tenant_id"
    "  AND p.ceremony_id = r.key_id AND p.kind = 'custodian'"
    " JOIN recovery_shares s ON s.tenant_id = p.tenant_id AND s.key_id = p.ceremony_id"
    "  AND s.holder_index = p.holder_index AND s.encrypted_share IS NOT NULL"
    " WHERE r.status = 'active' GROUP BY r.k"
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


def candidate_of(row: Any) -> Candidate:
    return Candidate(
        conversation_id=str(row["conversation_id"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        retention_until=row["retention_until"],
        legal_hold=row["legal_hold"],
        incomplete=row["incomplete"],
        key_ids=tuple(row["key_ids"]),
    )


def scope_of(rows: Sequence[Any]) -> tuple[ScopeKey, ...]:
    return tuple(ScopeKey(str(r["conversation_id"]), str(r["key_id"])) for r in rows)

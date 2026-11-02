"""SQL fragments of who may read a conversation and why (spec §10.6, §9.5, §10.7).

A user wrap's `creator_ref` tells grants apart: a gateway key ID for the
employee's own, the recipient's sub for a recovery they made themselves, and
another sub for a reviewer grant. Arguments are SQL expressions or placeholders;
every fragment expects the conversation as `c`.
"""

from __future__ import annotations

from typing import Final

OPEN_STATUSES: Final[str] = "('awaiting', 'in_review')"

# The status alone is a string the requester's own call sets; k approvals are not (§9.5).
APPROVED: Final[str] = (
    "(SELECT count(DISTINCT d.holder_index) FROM recovery_decisions d"
    "  WHERE d.tenant_id = r.tenant_id AND d.request_id = r.request_id"
    "  AND d.decision = 'approved' AND NOT EXISTS (SELECT 1 FROM recovery_rejections j"
    "   WHERE j.tenant_id = d.tenant_id AND j.request_id = d.request_id"
    "   AND j.holder_index = d.holder_index AND j.attempt = d.attempt))"
    # The k of the holders it was filed under: a later resharing never revokes it (§9.7).
    " >= (SELECT g.k FROM recovery_ceremonies g"
    "  WHERE g.tenant_id = r.tenant_id AND g.ceremony_id = r.holders_ceremony_id)"
)


def readable(sub: str, now: str) -> str:
    """Ended, not shredded, within its date or held, and wrapped for the caller."""
    return (
        f"c.ended_at IS NOT NULL AND c.shredded_at IS NULL"
        f" AND (c.retention_until > {now} OR c.legal_hold)"
        " AND EXISTS (SELECT 1 FROM key_wraps w JOIN conversation_keys k"
        "  ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
        "  WHERE k.conversation_id = c.conversation_id"
        f"  AND w.recipient_kind = 'user' AND w.recipient_ref = {sub})"
    )


def recovered(sub: str) -> str:
    """A completed request of `sub` covers the conversation, with k approvals that count."""
    return (
        "EXISTS (SELECT 1 FROM recovery_request_keys rk JOIN recovery_requests r"
        "  ON r.tenant_id = rk.tenant_id AND r.request_id = rk.request_id"
        f"  WHERE rk.conversation_id = c.conversation_id AND r.requester_sub = {sub}"
        f"  AND r.status = 'completed' AND {APPROVED})"
    )


def only_self_made(sub: str) -> str:
    """Every user wrap of `sub` on the conversation is one they made: no reviewer grant."""
    return (
        "NOT EXISTS (SELECT 1 FROM key_wraps w JOIN conversation_keys k"
        "  ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
        "  WHERE k.conversation_id = c.conversation_id AND w.recipient_kind = 'user'"
        f"  AND w.recipient_ref = {sub} AND w.creator_ref <> {sub})"
    )


def openable(sub: str, now: str, supervisor: str) -> str:
    """The opening rule (§10.6), widened by §9.5: the employee, or a supervisor whose
    request for the conversation completed and whose wraps are all their own (§10.7)."""
    return (
        f"(c.employee_sub = {sub} OR ({supervisor} AND {recovered(sub)}"
        f" AND {only_self_made(sub)})) AND {readable(sub, now)}"
    )


def excluded(sub: str, now: str) -> str:
    """Who may not be assigned: whoever can read it already, or is trying to (§10.7).

    A lapsed request stays 'open' until the retention worker's next pass closes it;
    it is no attempt any more, so it excludes nobody.
    """
    return (
        f"(c.employee_sub = {sub}"
        " OR EXISTS (SELECT 1 FROM key_wraps w JOIN conversation_keys k"
        "  ON k.tenant_id = w.tenant_id AND k.key_id = w.key_id"
        "  WHERE k.conversation_id = c.conversation_id AND w.recipient_kind = 'user'"
        f"  AND w.recipient_ref = {sub})"
        " OR EXISTS (SELECT 1 FROM recovery_request_keys rk JOIN recovery_requests r"
        "  ON r.tenant_id = rk.tenant_id AND r.request_id = rk.request_id"
        f"  WHERE rk.conversation_id = c.conversation_id AND r.requester_sub = {sub}"
        f"  AND (r.status = 'completed' OR (r.status = 'open' AND r.expires_at > {now}))))"
    )


def assigned(sub: str) -> str:
    """An open assignment of `sub` covers the conversation."""
    return (
        "EXISTS (SELECT 1 FROM verifications v WHERE v.tenant_id = c.tenant_id"
        f"  AND v.conversation_id = c.conversation_id AND v.reviewer_sub = {sub}"
        f"  AND v.status IN {OPEN_STATUSES})"
    )


def reviewing(sub: str, now: str, reviewer: str) -> str:
    """The reviewer branch (§10.7): never part of the archive list or `/archive/{id}`."""
    return f"({reviewer} AND {assigned(sub)} AND {readable(sub, now)})"


# The user wrap `w` (on a key of `c`) still has a reason to exist (§10.7).
LIVE_REASON: Final[str] = (
    "(w.recipient_ref = c.employee_sub"
    f" OR (w.creator_ref = w.recipient_ref AND {recovered('w.recipient_ref')})"
    " OR EXISTS (SELECT 1 FROM verifications v WHERE v.tenant_id = c.tenant_id"
    "  AND v.conversation_id = c.conversation_id AND v.reviewer_sub = w.recipient_ref"
    f"  AND v.requested_by = w.creator_ref AND v.status IN {OPEN_STATUSES}))"
)

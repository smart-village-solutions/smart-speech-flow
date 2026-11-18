"""SQL predicates for retained conversations, independent access grants and assignments."""

from __future__ import annotations

from typing import Final

OPEN_STATUSES: Final[str] = "('awaiting', 'in_review')"


def usable_grant(sub: str, reason: str) -> str:
    """w is one exact content-key wrap; a live independent grant must justify each read."""
    return (
        "EXISTS (SELECT 1 FROM key_grants g JOIN user_keys u ON u.tenant_id=g.tenant_id "
        "AND u.user_sub=g.user_sub AND u.key_version=g.key_version "
        "WHERE g.tenant_id=w.tenant_id AND g.key_id=w.key_id AND g.user_sub=w.recipient_ref "
        f"AND g.key_version=w.recipient_version AND w.recipient_kind='user' AND g.user_sub={sub} "
        f"AND u.state IN ('active','superseded') AND u.fingerprint=w.recipient_fingerprint AND ({reason}))"
    )


def readable(sub: str, now: str, reason: str = "g.reason IN ('owner','transfer')") -> str:
    return (
        f"c.ended_at IS NOT NULL AND c.shredded_at IS NULL AND (c.retention_until>{now} OR c.legal_hold) "
        "AND EXISTS (SELECT 1 FROM key_wraps w JOIN conversation_keys k ON k.tenant_id=w.tenant_id "
        f"AND k.key_id=w.key_id WHERE k.conversation_id=c.conversation_id AND {usable_grant(sub, reason)})"
    )


def openable(sub: str, now: str, supervisor: str) -> str:
    """Ordinary archive access requires a usable version with an owner or transfer grant."""
    # Keep the parameter typed in callers sharing legacy SQL placeholder positions.
    return f"({supervisor}::boolean IS NOT NULL AND {readable(sub, now)})"


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
    reason = (
        "g.reason='review' AND EXISTS (SELECT 1 FROM verifications vr WHERE "
        "vr.verification_id=g.grant_ref AND vr.reviewer_sub=g.user_sub "
        f"AND vr.reviewer_key_version=g.key_version AND vr.status IN {OPEN_STATUSES})"
    )
    return f"({reviewer} AND {assigned(sub)} AND {readable(sub, now, reason)})"


# The user wrap `w` (on a key of `c`) still has a reason to exist (§10.7).
LIVE_REASON: Final[str] = usable_grant("w.recipient_ref", "true")

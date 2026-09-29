# Change: One live conversation per admin, not per tenant

## Why

Creating a conversation ended every other live conversation in the same tenant,
so a second operator silently ended a colleague's running conversation (#473).
The intended rule is one live conversation per admin: several admins of a tenant
may converse in parallel, each with one.

## What Changes

- A session records the admin who created it, as a hash of the issuer-derived
  tenant and the verified token subject. The subject itself is not stored.
- Creating a conversation ends only that admin's previous live conversation.
- `GET /api/admin/session/current` without `session_id` returns the requesting
  admin's live conversation. With `session_id` it is unchanged.
- The owner is persisted with the session and never appears in API responses.
- `SSF_ALLOW_PARALLEL_SESSIONS=true` keeps disabling the limit altogether.

## Impact

- Affected specs: `admin-session-ownership` (new)
- Affected code: `services/api_gateway/tenant_context.py`, `session_manager.py`,
  `session_lifecycle.py`, `routes/admin.py`
- Sessions stored before the change have no owner; no admin's new conversation
  ends them, and they expire on their normal lifetime.
- Issue: #473; unblocks the #289 tester-release proof.

# Change: Admin session access limited to the owner

## Why

Since #473 several admins of a tenant hold live conversations in parallel, but
every admin route that names a session still authorizes by tenant only. Any
admin can open, read, speak into, join and end a colleague's conversation, and
the dashboard offers a colleague's live conversation as re-enterable (#476).

## What Changes

- **BREAKING** Every admin route that names a session answers only the admin who
  created it. A colleague's session, and a session without an owner, get the
  same `404 Session not found` as an unknown id. This covers status, messages,
  audio, sending a message, the realtime ticket, the session's realtime
  connections, terminate and the admin polling routes. The admin WebSocket
  opens only with a ticket, so it follows the ticket.
- **BREAKING** `GET /api/admin/session/current?session_id=…` returns the named
  session only to its owner.
- `GET /api/admin/session/history` lists only the requesting admin's ended and
  live sessions; `limit` counts after that filter. The dashboard therefore offers
  only the admin's own live conversation as re-enterable.
- `GET /api/admin/realtime/connections` lists only connections of the requesting
  admin's sessions.
- Decided on #476: ended conversations are owner-only as well; sessions without
  an owner (created before #473) belong to no admin and are denied to everyone;
  no role is exempt. An oversight role would be new product behaviour and is
  out of scope.
- The owner is the existing `owner_ref`; nothing new is stored. The session
  manager has no lookup across a tenant's admins any more: every listing and
  lookup takes the requesting admin's owner reference.
- The tester release check proves the colleague denial on every release: each
  tenant's two operators are refused each other's sessions on every route and
  socket, as A1 and B1 already are across tenants. Its preflight reads every
  tester's live sessions, since a history no longer shows a colleague's; whether
  real users are live is checked on the host instead.

## Impact

- Affected specs: `admin-session-ownership`
- Affected code: `services/api_gateway/session_access.py`, `session_lifecycle.py`,
  `session_manager.py`, `routes/admin.py`; the release check in
  `scripts/release_check/` (`preflight.py`, `isolation.py`, `__main__.py`) and its
  runbook
- Issue: #476

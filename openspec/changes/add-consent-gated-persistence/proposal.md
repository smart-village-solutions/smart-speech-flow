# Change: Consent-gated conversation persistence

## Why

SSF persists conversation content unconditionally. Audio is written to a
24-hour retention path and messages are stored in the session record, whatever
the tenant's Studio storage policy says and whatever the guest answered. No
consent answer reaches the server at all.

Runtime Configuration V1 requires SSF to re-read the storage policy before every
operation that would persist conversation content, and to hold a content-free
consent status per session. PR #342 built that gate under #299 but left it
unwired, because two of the three writes it would refuse are also how the live
conversation is delivered: the listener's audio URL exists only once the TTS
file is saved, and in-session history reads from the stored message record.

This change resolves that by separating live delivery from durable storage, so
the gate can refuse persistence without withholding the live translation that
Contract V1 explicitly permits for declined and disabled sessions.

## What Changes

- Guest consent is resolved at session activation from a live Studio read and
  stored as a content-free status. `granted`, `declined` and `policy_disabled`
  become reachable; today every session is `pending` forever.
- **BREAKING** for API clients: `POST /api/customer/session/activate` accepts an
  optional consent field. Omitting it resolves to `declined`, so a client that
  never sends it stops producing stored conversations.
- Each of the three conversation-content writes gets its own live Studio policy
  read, and the outcome is recorded against the artefact it wrote. The write
  itself still happens: two of the three are load-bearing for live delivery and
  cannot be deferred without removing the listener's audio.
- The policy reads move behind the participant-visible result, so none is
  awaited on the live path.
- Content recorded as refused is removed at session termination, and by a sweep
  for sessions that are never terminated. That removal is never configurable.
- One configurable retention period, default 24 hours, covers authorized audio
  and authorized message text, so the tester environment can use
  operator-managed deletion. Stored message text has no expiry today.
- A static guard fails the build if persistence-authorizing code reads frozen
  session configuration.

## Impact

- Affected specs: `guest-consent` (new), `conversation-persistence` (new)
- Affected code:
  - `services/api_gateway/routes/customer.py` — activation resolves consent
  - `services/api_gateway/routes/session.py` — the three write sites, tiering,
    correlation IDs, persistence moved behind the broadcast
  - `services/api_gateway/audio_storage.py` — configurable retention,
    removal of refused audio
  - `services/api_gateway/session_manager.py` — per-artefact authorization,
    removal at termination
  - `services/api_gateway/session_store.py` — expiry for stored message text,
    which has no TTL today
  - `services/api_gateway/conversation_service.py` — the authorization outcome
    must not reach the message-history response body
  - `services/api_gateway/app.py` — gate and metrics wiring, new timeout
    variable
  - `services/frontend/src/domain/session/session.repository.ts`,
    `src/features/consent/ConsentScreen.tsx`,
    `src/domain/consent/` — the answer travels on the existing activation
    request; the stub sink and its second call are removed
  - `tests/conftest.py` — a permissive gate for suites that assert persistence
- Closes: #288. Unblocks #289.
- Consumes the decision recorded in #299 and the primitives delivered in
  PR #342.

## Context

Issue #288 is Phase 4 of #266. Runtime Configuration V1 requires SSF to re-read
the effective storage policy before every operation that would persist
conversation content, to hold a content-free per-session consent status, and to
keep providing the live translation even when persistence is forbidden.

#299 decided the caching and failure rules: no cache, one live read per write,
every failure refuses. PR #342 implemented the primitives — `ConsentStatus`,
`RuntimePolicyGate`, `RuntimePolicyMetrics` and a presentation-only
configuration projection — and stopped, because wiring them as specified would
have broken live delivery. Nothing calls the gate today.

Verified against `main` at `b3894e1`: the gate has no production caller,
`Session.consent_status` is never set to anything but `pending`,
`RETENTION_HOURS = 24` is a module constant with no override, session records
carry no TTL and no sweep, the activation request has no consent field, and the
frontend records consent into a stub that discards it.

Client answers of 2026-09-17 fixed the product questions: hold non-consented
content only for the live conversation; 24-hour retention, made configurable; an
unticked checkbox means "no"; no mid-session withdrawal and no erasure requests;
manual deletion with no tooling; the consent screen unchanged, including when
storage is disabled.

## Goals / Non-Goals

- Goals:
  - Make `granted`, `declined` and `policy_disabled` reachable.
  - Authorize every conversation-content write with its own live Studio read.
  - Keep the live conversation identical for every consent state.
  - Remove non-consented content when the conversation ends, unconditionally.
  - Give authorized audio and text one configurable retention period, which the
    tester environment can disable.
- Non-Goals:
  - A consent screen redesign, a deletion UI, mid-session withdrawal, or
    erasure requests.
  - Locale fallback for the consent question; that is #300.
  - Per-tenant retention periods. Runtime Configuration V1 cannot express them:
    `conversationContentStorage` carries only `mode`.
  - Rendering Studio-supplied question HTML, deferred while Studio holds no real
    question text.
  - Changes to feedback storage.

## Decisions

- **Decision: the write always happens; the authorization is decided after the
  participant has been served.**

  Two of the three writes are load-bearing for live delivery, and they cannot be
  deferred. `_store_audio_artifacts` returns `original_audio_available`, which
  feeds `transform_pipeline_metadata` before the message is constructed
  (`routes/session.py:1020-1028`). `translated_audio_available` is set by the TTS
  save (`:1211-1217`) and gates `audio_url` in both the HTTP response
  (`:560-564`) and the WebSocket broadcast (`:1371-1379`). Moving either write
  behind the broadcast reports `audio_available: false` to every listener,
  granted and declined alike.

  Each write therefore lands where it lands today. After the participant-visible
  result is produced, each write's own live policy read runs and its outcome is
  recorded against the artefact. Refused content is removed at session
  termination.

  Alternatives considered and rejected: writing refused content to a separate
  ephemeral path, which forces every audio reader to resolve two locations —
  `conversation_service.py:74` decides whether history carries an `audio_url`,
  and `:114` serves the audio endpoint, both against a single path; and
  refusing the write outright and delivering TTS bytes inline over the
  WebSocket, which costs a frontend playback rewrite plus history and
  reconnection for declined guests.

- **Decision: the authorization outcome is recorded per write, not per session.**
  #299's central criterion is that a mode flip from `ask` to `disabled` between
  two writes in one session retains the first and not the second. Deciding a
  session's fate at termination fails it, because the first write would be
  removed too. Recording each write's own outcome preserves the criterion;
  termination only acts on decisions already taken. The three writes are three
  independent reads and may disagree.

- **Decision: the outcome is server-side state and is not exposed.**
  `SessionMessage.to_dict` is both the Redis payload and the body returned by
  `conversation_service.messages` (`conversation_service.py:71`), so the public
  response shape must not gain the field. Records written before this change
  restore as refused, so legacy in-flight content is not retained without an
  authorization.

- **Decision: consent is resolved once, on the activation that leaves the
  pending state.** Activation is explicitly idempotent and is re-entered
  mid-conversation whenever the customer language changes
  (`routes/customer.py:190-198`). A repeat activation performs no runtime read
  and leaves consent untouched. Without this rule a consent-less language change
  would overwrite `granted` with `declined`, and the tenant-availability refusal
  would block a language change during a live conversation.

- **Decision: activation reads through the raw runtime fetcher, not the policy
  gate.** `RuntimePolicyGate.authorize` increments
  `ssf_runtime_policy_content_discarded_total` on every refusal
  (`runtime_policy.py:85-88`). Routing activation through it would report
  discarded content for every `disabled` or consent-less activation, where no
  content write occurred.

- **Decision: a failed policy read at activation leaves consent `pending`, and
  the session still activates.** `pending` is the honest label: the guest was
  never successfully asked. Recording `declined` would claim the guest refused
  and would surface later refusals as `consent_declined` rather than a Studio
  problem. Both statuses refuse persistence, so this is a labelling choice, not
  a safety one. Refusing activation outright was rejected because a Studio
  outage would then prevent every new conversation.

- **Decision: an unbound gate refuses every write, and never blocks startup.**
  `runtime_flow_from_environment` raises when Studio credentials are absent,
  which is the normal state in local development and CI. The lifespan catches
  that and leaves the gate unbound. A process with no gate persists nothing.

- **Decision: one retention period covers audio and text.** Stored message text
  has no expiry today — session records are written with no TTL and no sweep —
  so a retention rule covering audio alone would leave transcripts and
  translations indefinitely. Expiry for stored message text is added so that one
  configurable period, default 24 hours, governs both. Disabling automatic
  deletion for the tester environment never retains refused content.

- **Decision: the per-write read checks tenant identity only.** It does not
  compare `authorizationRevision`, unlike `StudioRuntimeFlow.resolve`
  (`studio_runtime_flow.py:74-79`), because the customer flow carries no token
  and so has no revision claim to compare against. This was flagged and approved
  under #299 and shipped that way in PR #342; it is recorded here so the
  asymmetry reads as intended.

## Risks / Trade-offs

- **Three Studio round trips per utterance.** Affordable only because the reads
  sit behind the participant-visible result. The gateway has regressed this way
  before (#189, #190), so the test asserting it is not optional. If measurement
  shows the cost unacceptable, the answer is a Studio-side push mechanism, not a
  TTL — that would reopen #299.
- **Refused content exists in its normal location for the conversation's
  duration.** This is the client-confirmed reading of "transient processing
  strictly necessary to provide the live conversation". It is not the strictest
  possible reading, and it means the negative assertion is only true after
  termination.
- **Adding text expiry exceeds "minimal change".** It introduces record expiry
  where none exists. Accepted deliberately: without it the retention requirement
  cannot be met for transcripts, and declined transcripts in an abandoned
  session would persist indefinitely.
- **Default-refusing breaks existing tests.** Twenty-one test files reference
  `add_message`, `.messages`, `save_audio` or `translated_audio_available`. A
  permissive gate in `tests/conftest.py` keeps suites that are not about consent
  working; dedicated suites override it.
- **The guest-facing copy remains inaccurate.** `consent.optIn` and
  `consent.checkbox` promise storage "for up to 180 days" while retention will be
  24 hours. The client chose to leave it pending the legal review tracked at
  `add-multi-tenant-operations/tasks.md:1.2`. Carried deliberately.
- **A disabled tenant's guest still sees an inert checkbox.** Contract V1 says
  `disabled` asks nothing. Accepted to leave the screen unchanged.

## Migration Plan

- Sessions created before the deploy carry a snapshot that still contains the
  storage policy, which the projection introduced by PR #342 rejects. Sessions
  live at most `SSF_SESSION_MAX_HOURS`, default 8, so the condition clears
  within one session lifetime. The first caller must tolerate such records.
- Messages written before the deploy restore as refused and are removed at
  termination. This affects only conversations in flight at deploy time.
- Sessions created before the deploy restore with consent `pending`, which
  refuses persistence. Their conversations continue.
- `STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS` is new, defaults to `5.0`, and
  is optional. A required compose variable would break every interpolating
  compose test, so it is introduced with a default.
- Rollback is a revert. Authorized content stays. Refused content already
  removed is not recoverable, which is the intended behaviour.

## Open Questions

- The retention period shown to guests is unresolved pending the legal review.
  24 hours is the implemented value; the 180-day copy is untouched.
- `STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS` keeps the client default until
  `ssf_runtime_policy_read_duration_seconds` yields measured Studio latency.
- Studio-supplied consent question HTML is deferred. When Studio holds real
  question text, the presentation field and its locale fallback (#300) land
  together.

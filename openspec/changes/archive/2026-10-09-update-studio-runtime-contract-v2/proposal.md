# Change: Consume the Studio runtime contract v2

## Why

SVA Studio now serves contract v2 in production: a tenant runtime configuration
at `/internal/plugins/ssf/v2/runtime-configuration` and installation-wide
content at `/internal/plugins/ssf/v2/installation-content`. SSF still reads v1,
uses only `tenant.id` and the storage mode from it, and shows bundled copy for
everything Studio already provides: staff texts, guest texts, the storage
question, feedback forms, legal links, logo and favicon. Retention is a global
24-hour setting while Studio now states a per-tenant period of 4320 hours.

## What Changes

- **BREAKING (internal):** the v1 runtime-configuration client is replaced by a
  v2 client. Policy fields and content are parsed separately, so an invalid
  content section falls back to bundled copy instead of refusing persistence.
  The login directory stays on v1.
- A new installation-content client and a content cache keyed by
  `configurationRevision`. The storage mode is never cached.
- The persistence gate takes one live Studio read per message instead of one
  per artefact; the decision applies to every artefact of that message.
- Retention becomes per tenant: `retentionHours` is captured with granted
  consent and governs that session's message text, audio and terminal record.
  The global `SSF_CONTENT_RETENTION_HOURS` is removed.
- New browser-facing routes:
  - `GET /api/content/installation` (anonymous)
  - `GET /api/customer/session/{session_id}/languages`
  - `GET /api/customer/session/{session_id}/content/{language}`
  - `GET /api/admin/content` (authenticated)
- Hybrid guest languages: SSF keeps its own guest language list. A language
  Studio provides uses Studio texts; every other language keeps today's bundled
  texts unchanged. German is staff-only.
- Feedback forms become Studio-defined. Answers are stored per question id
  with the rendered form, validated against the form the person was shown, and
  emitted to analytics per answer. **BREAKING (data):** the fixed rating
  columns are replaced; no production feedback data needs migrating.
- Staff feedback requires login and is filed under the staff member's tenant
  through `POST /api/admin/feedback`.
- The frontend renders Studio content with a sanitising renderer that never
  writes raw HTML, shows imprint, privacy and accessibility links on every page
  (on conversation screens in a row under the microphone row), and uses the
  Studio logo and favicon. The tenant display name is not shown after login.
- The Studio mock serves both v2 endpoints.

## Superseded requirements

Those capabilities were never archived into `openspec/specs/`, so this change
states its requirements as ADDED and lists what each replaces.

| This change | Supersedes |
|---|---|
| `studio-runtime-integration`: Studio Runtime Configuration V2 client | `add-studio-runtime-configuration-client`: Studio Runtime Configuration V1 client |
| `conversation-persistence`: Per-message live policy authorization | `add-consent-gated-persistence`: Per-write live policy authorization |
| `conversation-persistence`: Tenant retention captured with consent | `add-consent-gated-persistence`: Configurable retention for authorized content |
| `studio-content-delivery`: Hybrid guest languages | `add-conversation-language-display-fallback`: all three requirements |
| `feedback-persistence`: Studio-defined feedback forms; Per-answer analytics events | `add-feedback-persistence`: Store structured feedback in ClickHouse analytics (fixed ratings and NPS) |
| `studio-runtime-configuration-mock`: Mock serves contract v2 | `add-studio-runtime-configuration-mock`: Contract-faithful opt-in runtime configuration mock (v1 body) |

## Impact

- Affected specs: `studio-runtime-integration`, `conversation-persistence`,
  `guest-consent`, `studio-content-delivery` (new), `feedback-persistence`,
  `studio-runtime-configuration-mock`
- Affected code:
  - Gateway: `studio_runtime_client.py`, `studio_v1.py`,
    `studio_runtime_flow.py`, `studio_runtime_token.py`, `runtime_policy.py`,
    `persistence_authorization.py`, `consent_resolution.py`,
    `session_lifecycle.py`, `tenant_session.py`, `session_models.py`,
    `session_store.py`, `session_manager.py`, `audio_storage.py`,
    `presentation_configuration.py` (removed), `display_text_fallback.py`
    (removed), `feedback/*`, `quality_telemetry*.py`, `routes/*`, `app.py`
  - `services/studio_mock`, `deploy/postgres/migrations/004`,
    `deploy/clickhouse/migrations/008`, compose files, `monitoring/`
  - Frontend: `src/domain/content` (new), `src/domain/{brand,feedback}`,
    `src/features/{access-code,login,language-select,consent,conversation,
    feedback,admin}`, `src/ui/patterns`, `index.html`
- Depends on Studio: both v2 endpoints are live (verified 2026-10-07). A
  fourth system-load label (`unknown`) is not yet in the contract; the bundled
  text stays until Studio adds it.

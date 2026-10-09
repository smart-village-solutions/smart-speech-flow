## Context

Studio contract v2 (rev2 schema, agreed with Studio on 2026-10-06) is live for
the tenants `tenant-kassel` and `smart-city-labor`. Both responses and the
installation content validate against the rev2 schemas. Studio provides staff
texts in `de-DE` and one guest language, `en`. v2 errors carry
`contractVersion: "2.0"`.

Decisions already taken by the product owner:

- German is a staff language only; guests never get it.
- Guest languages are hybrid: Studio texts where Studio provides the language,
  today's bundled texts for every other language.
- Retention follows Studio's `retentionHours` (4320 hours for both tenants).
- Text content is accepted as Studio delivers it.
- Legal links appear on every page; on conversation screens below the
  microphone row.
- The tenant display name is not shown after login. No issue or document asks
  for it; the login organisation chooser keeps using the directory name.
- Staff feedback requires login.

## Goals / Non-Goals

- Goals:
  - Replace v1 with v2 without a gap in persistence or consent behaviour.
  - Show Studio content wherever v2 provides it, with bundled fallback.
  - Per-tenant retention captured at the moment of consent.
  - Studio-defined feedback forms end to end, including analytics.
- Non-Goals:
  - Conversation or feedback deletion on request (tracked in #318).
  - Moving the login directory to v2 (Studio has no v2 directory).
  - A content security policy or media host allowlist.
  - Showing the tenant display name or using `tenant.timeZone` for anything
    beyond formatting staff timestamps.

## Decisions

### Two-stage parse

A strict policy view (`contractVersion`, `configurationRevision`, `tenant`,
`conversationContentStorage`) decides persistence and consent. Content
sections are parsed separately and per guest language. A content error logs
and drops that section, so the browser gets bundled copy. A policy error
refuses, as today.

Alternative: one strict model for the whole body. Rejected because one
unknown feedback question type would refuse every write and leave every new
session's consent `pending`.

### Versions

The client accepts `contractVersion` `2.x` for bodies and `1.x` or `2.x` for
error envelopes, so a 409 `tenant_suspended` still raises a tenant conflict at
activation.

### Shared token provider

One `StudioRuntimeTokenProvider` is built in the lifespan and injected into
the runtime, installation and directory clients, replacing two separate token
caches.

### Content cache, live policy

`StudioContentCache` holds sanitised content keyed by
`(tenant_id, configurationRevision)`, at most four revisions per tenant, plus
a per-tenant latest-revision pointer. Every live read that already happens
(session create, activation, persistence) refreshes it. Display routes use the
pointer while it is younger than `STUDIO_CONTENT_CACHE_SECONDS` (default 60),
otherwise make one single-flight live read, and on failure serve the last
known content marked stale. The type holding cached content has no storage
field. Installation content has its own single-key cache with the same rules.

### Per-message persistence reads

One live read per message authorizes the message record and both of its audio
artefacts, replacing up to three reads per voice message. Each artefact still
records the decision taken for it.

### Retention captured with consent

When activation resolves consent to `granted`, the session stores
`consent_retention_hours` and `consent_configuration_revision` from the same
live read. They never change afterwards.

- Message text: the active-session sweep and the terminal record TTL use the
  session value; `0` means no automatic deletion.
- Audio: a `retention.json` marker in the session's audio directory carries
  the hours; the cleanup walk reads it per session directory and falls back to
  the short default when it is missing or invalid, so errors delete sooner.
- Sessions without granted consent keep no content after settlement; their
  terminal record expires after `SSF_TERMINAL_RECORD_HOURS` (default 24).
- The tenant session index is pruned of expired members, because at 4320
  hours records stay live and the index is read in full on every staff list.

### Session record keeps only the revision

`Session.runtime_configuration` (a full snapshot, about 12 KB in v2) is
replaced by `configuration_revision`. `from_dict` still reads v1 records,
because active sessions and terminal records survive the deploy.

### Browser routes

| Route | Access | Returns |
|---|---|---|
| `GET /api/content/installation` | anonymous, per-IP rate limit | branding, legal URLs, start page and login texts, installation feedback form; `Cache-Control: public, max-age=60`, ETag = revision |
| `GET /api/customer/session/{id}/languages` | session key | SSF's guest languages; Studio-provided entries add `provided`, `nativeName`, `icon` |
| `GET /api/customer/session/{id}/content/{language}` | session key, also within the feedback grace period after the session ends | `storage.mode` from a live read (`unknown` on failure), and either the Studio guest content and form or `provided: false` |
| `GET /api/admin/content` | Keycloak, tenant from the token | staff texts, staff form, logo, icon, time zone, staff language names |

Locales map to SSF language codes by primary subtag, with explicit aliases
(`kmr` → `ku`). Unsupported or duplicate locales are skipped and counted.
HTML is sanitised once at cache insert with the existing nh3 allowlist (moved
from `display_text_fallback.py` to `studio_html.py`).

### Frontend rendering

- A `RichText` pattern parses Studio HTML with `DOMParser` and rebuilds an
  allowlist of elements with `createElement`. It never sets `innerHTML`, which
  avoids a Sonar security hotspot and adds no dependency. A source-scan test
  forbids `dangerouslySetInnerHTML`.
- Studio text is a data overlay, not i18next resources. One resolver returns
  Studio or bundled text per field, so each component has one render path.
- The consent screen waits for guest content up to the request timeout, so one
  legal text never swaps for another while being read. The storage checkbox is
  hidden when the mode is `disabled` or `unknown`.
- The feedback form is driven by a form definition. The bundled form becomes a
  definition using Studio's question ids, so fallback and Studio forms share
  one renderer.

### Feedback storage

Postgres migration `004` replaces the four rating columns and
`improvements_ciphertext` with `audience`, `form_source`,
`configuration_revision`, `form_locale`, `form_snapshot` (JSONB),
`numeric_answers` (JSONB) and `text_answers_ciphertext` (one envelope over all
free-text answers, same cipher and AAD). Validation lives in the service, not
in pydantic constraints, so no error copies free text into a 422 body. A
submission is checked against the form of its revision when cached, otherwise
against the current form; it is rejected with 409 only when its answers do not
fit. Rating questions require `min ≥ 1`, because zero stars cannot be told
apart from no answer.

### Feedback analytics

One `feedback_submitted` header event plus one `feedback_answer` event per
numeric answer, with ids `uuid5(analytics_event_id, question_id)` so
reconciliation stays idempotent. ClickHouse migration `008` restates the full
materialized view query as the schema contract test requires.

## Risks / Trade-offs

- **Retention rises from 24 hours to 180 days** for consented content once
  deployed, while no deletion route exists (#318) and Studio's feedback notice
  promises withdrawal through staff. → Product-owner decision; #318 remains
  the follow-up.
- **Studio becomes a dependency of every display route.** → Fail open to
  cached or bundled content; only policy fails closed.
- **Old session records at deploy.** → Backward-compatible `from_dict` with a
  v1-payload test.
- **Fallow cognitive limits** on `ConsentScreen`, `FeedbackSheet` and
  `AdminDashboardScreen`. → Extract hooks in the same PRs.
- **Audio disk alerts** are tuned for 24 hours. → Retune with this change;
  715 GB are free on the production host.

## Migration Plan

1. Backend lands first: v2 clients, mock, cutover, retention, content routes.
   The frontend keeps working on bundled copy throughout.
2. Frontend PRs consume the routes one surface at a time.
3. Feedback backend and analytics land with the Studio form frontend.
4. Deploy runs Postgres migration `004`, ClickHouse migration `008`, and a
   Prometheus restart for the new rules.
5. Rollback: redeploy the previous images. Sessions written by the new code
   carry only additive fields; feedback rows written after `004` are lost on a
   schema rollback, which is acceptable while production holds test data.

## Open Questions

- Studio has not yet added an `unknown` system-load label; SSF keeps the
  bundled text until it does.

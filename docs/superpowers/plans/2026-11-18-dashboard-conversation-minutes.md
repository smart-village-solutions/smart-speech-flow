# Dashboard Conversation Minutes Implementation Plan

> **For agentic workers:** Execute inline with the executing-plans workflow. Steps
> use checkbox syntax for tracking.

**Goal:** Show rolling thirty-day conversation minutes and customer-language
breakdowns for the requesting staff member, organisation and deployment.

**Architecture:** Persist timestamped language intervals with session metadata.
An independent SQLite usage ledger holds only usage metadata on a dedicated
volume, because Redis intentionally disables disk persistence. The authenticated
gateway returns aggregates; the dashboard renders one compact, expandable card.

**Tech Stack:** Python 3.12, sqlite3, asyncio, FastAPI, React, React Query, i18next.

**Spec:** `openspec/changes/add-dashboard-conversation-minutes/specs/conversation-usage-reporting/spec.md`

## Global Constraints

- Count activation to termination, including pauses, once per conversation.
- Clip intervals to the rolling thirty-day window and query timestamp.
- Keep owner references internal; store no conversation content in the ledger.
- Labels show only the customer language.
- Report incomplete coverage and unavailable storage explicitly.
- Place the card below the new-conversation button and above conversation history.
- Preserve unrelated, pre-existing untracked proposals and documents.

## Task 1: Usage ledger and lifecycle

**Files:** Create `services/api_gateway/conversation_usage.py` and
`tests/test_conversation_usage.py`; modify `session_models.py`,
`session_manager.py`, `dependencies.py` and the gateway container/Compose setup.

**Interfaces:** `ConversationUsage.record(snapshot: UsageSnapshot)` persists an immutable metadata snapshot;
`ConversationUsage.report(tenant_id, owner_ref, now)` returns three scopes with
`total_seconds` and `by_language` plus window and coverage timestamps.

- [x] Write failing tests exercising real SQLite files and real session managers:
  activation after waiting, language switches, termination, restart, clipping,
  duplicate snapshots, owner/tenant totals, missing language, expiry and failure.
- [x] Run `.venv/bin/pytest tests/test_conversation_usage.py -q` and confirm red.
- [x] Add internal `usage_language_changes` metadata with ISO UTC timestamps;
  append on first activation and genuine language changes only. Strip it from
  public session dictionaries. Restore it across Redis rehydration.
- [x] Implement SQLite transactions off the event loop, parameterised SQL, bounded
  retention and a deployment-wide coverage start persisted in the same database.
  Example: ten Arabic minutes followed by fifteen Ukrainian minutes yields
  `{"total_seconds": 1500, "by_language": {"ar": 600, "uk": 900}}`.
- [x] Wire post-commit usage projection and retry failed snapshots before serving
  totals. Preserve the session pipeline on reporting failure; return 503 until
  failed writes can be retried. Replay retained canonical metadata at startup;
  never project uncommitted cached state during reporting.
- [x] Add a dedicated named volume and `SSF_USAGE_DATABASE_PATH`; document that
  the SQLite ledger is for the existing single-gateway deployment, not replicas.
- [x] Rerun ledger and session lifecycle regression tests.

## Task 2: Authenticated report

**Files:** Modify `services/api_gateway/routes/admin.py`; create
`tests/test_conversation_usage_route.py`.

**Interfaces:** `GET /api/admin/usage` derives tenant and owner from authentication;
returns `window_start`, `window_end`, `coverage_start`, `complete`, `personal`,
`organisation` and `server`. Each scope contains seconds and a language map.

- [x] Write route tests for real aggregate results, unavailable storage and
  unauthenticated access. Verify no owner, tenant or session identifiers escape.
- [x] Run the route tests before implementation and confirm red.
- [x] Add the route with `Cache-Control: no-store` on success and failure, a
  response model and a value-free 503 error.
- [x] Run route and owner-access regression tests.

## Task 3: Compact dashboard card

**Files:** Create `domain/admin/usage.ts`, `features/admin/ConversationUsageCard.tsx`
and its component tests; modify the admin repository, dashboard, locale catalogues
and MSW handlers.

**Interfaces:** `AdminRepository.getUsage(): Promise<ConversationUsage>` validates
the response with Zod. The card uses the existing staff language-name resolver.

- [x] Write component tests for totals, collapsed language details, expansion,
  language-only labels, incomplete coverage, loading and errors.
- [x] Run `npm test -- ConversationUsageCard` and confirm red.
- [x] Add validated response parsing, an admin-cache-scoped query refreshed every
  thirty seconds, and a semantic table with one accessible disclosure button.
- [x] Show totals first; sort language rows by descending deployment duration.
  Display minutes with a locale-aware formatter and one decimal place.
- [x] Add German/English copy and place the card between the start button and
  history. Use existing design tokens and keyboard-visible focus styles.
- [x] Run frontend tests, lint and production build; run Python formatting, lint,
  type checks and the relevant regression suite; validate the OpenSpec proposal.

## Validation

- Backend regression and gateway contract suite: 594 passed.
- Complete frontend suite: 1,799 passed.
- Gateway MyPy: 213 source files passed; affected Python files pass Black,
  isort and Flake8. Frontend lint, production build and token checks passed.
- Chromium preview at 320px and 960px: no overflow or page errors.
- Independent review: all demonstrated persistence and concurrency defects
  resolved; no remaining important findings in the targeted review.
- OpenSpec strict validation passed. Changes are prepared for pull-request review; no deployment performed.

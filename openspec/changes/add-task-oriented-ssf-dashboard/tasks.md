## 1. Shared contract and handoff

- [ ] 1.1 Approve this proposal alongside the coordinated key-lifecycle and Studio proposals; confirm shared route/DTO ownership before runtime changes.
- [ ] 1.2 Add overview and result-summary DTO fixtures covering no recording, owned recording, transferred recording, archive-only row, encrypted language, expired metadata and completed review; align frontend and gateway consumers.

## 2. Gateway overview and result summaries

- [ ] 2.1 Add owner-scoped overview aggregation with internal-only source joins, stable deduplication, bounded pagination, user/tenant-bound cursors and explicit unavailable errors.
- [ ] 2.2 Expose only permitted metadata, preserve encrypted languages and existing retention, derive navigation hints without replacing action-time authorization.
- [ ] 2.3 Add own-completed-review result summaries with current review permission checks and no recording, findings, key, wrap, download or object access.
- [ ] 2.4 Verify cross-tenant/owner isolation, source failures, duplicate rows, expired data, pagination and absence of private/internal identifiers or forbidden result payloads.

## 3. SSF task dashboard

- [ ] 3.1 Add shared table composition and a gateway overview repository; keep conversation, recording and verification status distinct.
- [ ] 3.2 Preserve ordinary conversations for every admitted user; add the review tab only with effective review permission and remove stale review state when permission is lost.
- [ ] 3.3 Add independent local filters and sorting, explicit loaded-subset counts, unknown/encrypted language handling, load-more and resettable empty/error states.
- [ ] 3.4 Integrate existing live sessions and recording viewers; add metadata-only unrecorded details without content/reconstruction actions.
- [ ] 3.5 Integrate existing review inbox/editor and the completed-result summary; invalidate relevant lists after decisions, returned assignments and ended conversations.
- [ ] 3.6 Preserve originating table/view/filter state and the exact permitted detail target through account unlock, cancellation and normal login after actual session expiry; valid sessions require no sensitive-action reauthentication.
- [ ] 3.7 Keep existing rolling thirty-day conversation-minute reporting and optional language breakdown available in the conversation context.

## 4. Account and coordinated navigation

- [ ] 4.1 Add internal account composition with personal access management, existing external Keycloak account settings, optional technical key details and explicit lock.
- [ ] 4.2 Retain passphrase vocabulary, encrypted personal-key blobs and policy-controlled local TXT flows; consume the companion lifecycle's historical-key APIs instead of implementing a second key model.
- [ ] 4.3 Add effective-capability replacement notices and organisation-contact guidance; coordinate final removal of legacy ceremony/recovery/approval entries with the Studio/Gateway release.
- [ ] 4.4 Reduce the final user menu to account, authorized Studio administration and logout; retain tenant-bound Studio checks and existing secret cleanup.

## 5. Acceptance and release

- [ ] 5.1 Run focused frontend behavior tests for task combinations, independent filters, pagination, unknown languages, unlock returns, result-only summaries and account navigation.
- [ ] 5.2 Run gateway route/aggregation/authorization tests and existing affected recording/review regressions; run frontend build and lint.
- [ ] 5.3 Review keyboard/mobile table behavior and meaningful empty/error states against the concept without requiring pixel-identical Figma geometry.
- [ ] 5.4 Verify coordinated Studio links and organisation-recovery availability before retiring legacy navigation; document rollout and test evidence in English without performing unapproved data deletion.

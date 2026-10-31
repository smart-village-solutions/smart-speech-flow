## 1. Implementation

- [x] 1.1 Add regression coverage for removed language discovery, selection,
  validation, and Studio locale filtering (`ti`, `ku`, `kmr`, regional variants).
- [x] 1.2 Remove Gateway registrations and the Kurdish Studio alias; check
  activation and message validation, including existing sessions.
- [x] 1.3 Remove frontend catalogues, imports, and dedicated metadata; update
  supported-language fixtures and UI tests.
- [x] 1.4 Remove ASR support and prevent translation discovery or request
  validation from exposing the removed languages through model capabilities.
- [x] 1.5 Remove TTS voice registrations and language-specific speech-text rules;
  retain Amharic MMS support and verify its existing tests.
- [x] 1.6 Update Studio mock fixtures and replace positive alias coverage with
  unsupported-locale coverage; align API contracts, smoke/load scenarios and
  active language fixtures.
- [x] 1.7 Update current API, model and TTS documentation and supported-language
  counts; retain historical reports and archived changes.

## 2. Verification

- [x] 2.1 Run affected Gateway, Studio mock, ASR, translation and TTS tests.
- [x] 2.2 Run affected frontend tests, type checking and production build.
- [x] 2.3 Search active code and documentation for remaining positive support
  claims; inspect the diff and validate the OpenSpec change with strict checks.

## Verification results

- Backend selection: 1,041 passed, 22 skipped. The skipped tests require live
  services; this change was verified with the existing service doubles.
- Frontend: all 1,541 tests passed across 173 files.
- Frontend production build (including TypeScript checking) and ESLint passed.
- Gateway mypy: no issues in 193 source files.
- All 24 remaining duration fixtures exist; changed Python and JSON files parse.
- OpenSpec strict validation and `git diff --check` passed.
- Independent code review findings were resolved: the refinement default test
  and current developer, fixture, and MMS documentation now match the removal.
- Studio's `kmr` mock input is deliberately retained to test filtering of
  unsupported content.

## Production deployment

- Deployed on explicit user instruction on 2026-10-30 from source commit
  `2acde0bd`; the five image references and IDs are recorded in
  `deploy/production/known-good-images.lock`. Previous images remain available
  locally for rollback. No unrelated service was recreated.
- Production follows its existing code line. The PR carries the equivalent
  language removal on current main; unrelated recording features from main
  were not deployed.
- Full production health gate passed. Public API discovery returns 20 languages
  without `ti` or `ku`; the public frontend returns HTTP 200 and the removed
  Eritrean flag asset is absent.
- ASR and TTS each advertise 20 languages; translation discovery excludes both
  removed codes. Direct removed-language requests return HTTP 400.
- Real German ASR, German-to-English translation, German Piper TTS and Amharic
  MMS TTS all passed using synthetic input. No customer records were modified.
- The isolated pre-commit mypy environment reports 14 errors on both the
  original production baseline and this change because it lacks runtime
  dependencies. That hook alone was skipped for commits; mypy 2.3.1 in the
  project's installed environment passed. All other applicable commit hooks
  passed.

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
  unsupported content. No deployment or real model inference was performed.

# PR 654 frontend compatibility release

This release starts from the running frontend source `45f4e6b2` and applies the UI fixes from merged PR #654 (`4aaacbd7`). It always renders the controlled ordinary introduction instead of Studio explanations, qualifies the recording-consent notice in all 20 existing catalogues, and handles explicit/undetermined reference-wording locales.

The deployed application still uses the older storage/activation contract. The backport deliberately preserves storage questions, their rendering conditions, activation parameters and the route-keyed reference snapshot. Its current disabled storage policy still displays only the two ordinary introduction paragraphs. No backend, policy, domain/authentication code, source legal wording, language selection, flags or unrelated catalogue keys are changed.

Validation before image build: 1,272 tests across 131 files, 16 browser cases, lint, production build, compiled-CSS token checks and Fallow pass. Independent review found no actionable regressions. Source is published on `release/kassel-pr654-ui-20261101`.

Build from an immutable source archive with the existing public API/WebSocket/OIDC URLs. Verify the candidate image and read-only entry replay before replacing only the frontend. Capture the live Compose definition and container/image IDs for rollback, create a verified backup, then check full platform health and the public frontend after activation. Keep canonical Compose and the image lock in sync with the verified image.

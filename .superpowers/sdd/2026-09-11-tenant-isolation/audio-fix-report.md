# Audio Fix Report

## Status

Complete. Final-review findings 2, 3, 4, and 8 are implemented without restoring the removed generic audio routes.

## Findings addressed

### 2. Role-correct live and historical audio URLs

- Audio URLs are created only at HTTP and WebSocket response boundaries for the authorized receiving role.
- Sender and receiver broadcasts independently receive admin- or customer-scoped original, translated, and pipeline-metadata URLs.
- History endpoints now emit role-scoped URLs, and the frontend mapper consumes those server-provided URLs instead of reconstructing `/api/audio/...`.
- Persisted message and pipeline metadata retain audio availability, not reusable role-specific URLs.

### 3. Authenticated frontend audio loading

- The browser clip loader now fetches protected audio through the shared Axios client, including the admin bearer interceptor, and converts the response to a blob URL.
- Playback waits for the authenticated loader and has no raw protected-URL fallback.
- The DOM player rejects protected role-scoped API URLs as a defense against accidental unauthenticated playback.
- The bearer interceptor accepts same-origin absolute admin URLs while refusing to attach a token to a different origin.

### 4. V2 retention and disk accounting

- Cleanup and usage accounting now traverse only the managed `v2/<tenant-ref>/<session>/<variant>/<message>.wav` layout.
- Expired v2 audio is removed, recent audio is retained, and unrelated, malformed, legacy, symlinked, or escaping paths are ignored.
- Existing aggregate original/translated metrics remain fixed-cardinality.

### 8. Terminal-session audio denial

- The audio-serving boundary returns the same neutral 404 for missing and terminal sessions.
- Both original and translated variants are denied immediately after termination while physical files remain available for retention cleanup.

## TDD and verification

Focused regressions were observed failing before the production changes, then passing after implementation. The final verification run completed with:

- Backend focused suite: `102 passed`.
- Frontend suite: `80 files passed`, `568 tests passed`.
- Frontend ESLint: passed.
- Frontend TypeScript/Vite production build: passed; Vite reported only the existing large-chunk advisory.
- Python bytecode compilation for `services/api_gateway`: passed.
- `git diff --check`: passed.

Python `mypy` and `black` are not installed in this worktree environment, so those optional commands could not be run. No scoped implementation blocker remains.

## Scope and coordination

This change does not modify `session_manager.py`, `realtime_ticket.py`, application startup store wiring, or WebSocket authentication/logging. The commit containing this report is the isolated audio-fix commit.

## Architecture

The gateway records the first activation and subsequent customer-language changes
in internal session metadata. Public session responses strip this field. Existing
creation-to-termination quality telemetry remains unchanged.

An independent SQLite ledger projects only opaque session keys, internal tenant
and owner attribution, language intervals, termination timestamps and timeout
deadlines. It never receives conversation content or bearer/guest tokens. SQLite
uses WAL and full synchronous commits on a dedicated named volume, with all I/O
off the event loop. This fits the existing single-gateway deployment without new
database credentials or persisting the plaintext Redis database. Replicated
gateways would require a shared transactional ledger instead.

## Reporting

`GET /api/admin/usage` derives the organisation and owner from verified identity
and returns seconds, language maps and coverage timestamps only. One query time
defines the rolling thirty-day window. A conversation's first interval starts
at activation; subsequent intervals start at language changes. Intervals are
clipped to the window and termination/query time. Unknown language attribution
has an explicit bucket. Running projections are capped at the last known session
timeout so lost Redis state cannot create indefinitely growing usage.

The frontend validates the response, refreshes every thirty seconds in the
existing administrative query-cache boundary and shows minutes with up to one
decimal place. Raw seconds are summed before display rounding. One disclosure
reveals language rows for all three scopes; labels show only customer languages.

## Recovery and coverage

Usage projection uses immutable snapshots captured before persistence and queued
only after a successful session-store commit. Activation, language changes and
termination are serialised per session, so termination neither preserves a failed
activation nor overwrites one whose persistence acknowledgement is still pending.
Projection and recovery share a lock so recovery cannot delete a newly committed
conversation. Failed projections
remain queued and the endpoint refuses a successful result until retries succeed.
Unchanged successful snapshots are skipped, and a storage failure stops further
reconciliation promptly; lifecycle writes back off for thirty seconds.

Startup replays retained canonical Redis records, including terminal sessions,
before restoring live presence. A durable open-run marker detects unclean
shutdown. After an unclean stop, completed ledger rows remain trustworthy, while
open rows are discarded and reconstructed only from retained canonical state.
Open rows without canonical state after Redis loss are also discarded. Coverage
is marked incomplete from recovery time rather than silently claiming thirty
days of reliable measurement. Known completed usage from before this boundary
remains visible; the boundary describes continuous complete coverage.

Graceful shutdown flushes pending projections before marking the ledger clean.
An outage followed by loss/expiry of Redis records can prevent full recovery;
the incomplete-coverage state explicitly accounts for this limitation. Sessions
from before this feature have no trustworthy activation timestamp and are not
backfilled with invented times.

Usage rows expire after their effective end leaves the reporting window. The
minute-level timeout monitor performs retention even when nobody opens the
dashboard. Retention affects only the dedicated usage ledger.

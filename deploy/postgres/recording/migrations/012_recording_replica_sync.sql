-- Noticing an archive site that does not receive new versions (#626).
-- Applied by ../../apply.sh after 011. Every statement is idempotent.

-- When this site's worker first read the version. Unlike checked_at, a re-read
-- after a restore does not clear it: a version read once is not missing.
ALTER TABLE version_locks ADD COLUMN IF NOT EXISTS first_read_at TIMESTAMPTZ;
-- Versions read before this migration: otherwise each would count as missing
-- until its next visit, which can be months away.
UPDATE version_locks SET first_read_at = checked_at
WHERE first_read_at IS NULL AND checked_at IS NOT NULL;

-- When the oldest version this site has never read was stored; NULL when there
-- is none. The gateway exports it, so a replica whose sync stopped alerts.
ALTER TABLE retention_worker_status ADD COLUMN IF NOT EXISTS unconfirmed_since TIMESTAMPTZ;

-- Each pass reads it per tenant; normally only the newest versions match.
CREATE INDEX IF NOT EXISTS version_locks_unread
    ON version_locks (tenant_id, site) WHERE first_read_at IS NULL AND deleted_at IS NULL;

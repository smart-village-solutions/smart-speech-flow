-- The roles that make migration 001's tenant policy real.
--
-- A policy is only consulted for a role that is neither a superuser nor
-- BYPASSRLS. The gateway previously connected as the migration owner, which is
-- both, so `feedback_tenant_isolation` was never in the path: bound to one
-- tenant, that connection still saw every tenant's rows. Verified against
-- postgres:17.7-alpine.
--
-- The work splits in two because the access patterns genuinely differ. The
-- request path handles one tenant per request and must not be able to reach
-- another, or to delete anything at all. Reconciliation and retention are
-- deployment-wide by definition -- there is no tenant to bind them to -- so
-- they get a role that bypasses the policy and nothing else.
--
-- Passwords arrive as psql variables from apply.sh, so this file holds none.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssf_feedback_app') THEN
        CREATE ROLE ssf_feedback_app;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssf_feedback_maintenance') THEN
        CREATE ROLE ssf_feedback_maintenance;
    END IF;
END
$$;

-- Set unconditionally rather than only at creation, so rotating a password is
-- a re-run of this migration and not a manual step someone has to remember.
ALTER ROLE ssf_feedback_app
    WITH LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

ALTER ROLE ssf_feedback_maintenance
    WITH LOGIN PASSWORD :'maintenance_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;

GRANT CONNECT ON DATABASE :"database" TO ssf_feedback_app, ssf_feedback_maintenance;
GRANT USAGE ON SCHEMA public TO ssf_feedback_app, ssf_feedback_maintenance;

-- The request path. SELECT is required because the delivery-state UPDATE reads
-- feedback_id in its WHERE clause, and because the policy is evaluated against
-- the row. No DELETE: expiry must not be reachable from an HTTP request, and
-- the absence of the grant makes that a privilege error rather than a review
-- comment someone has to notice.
GRANT SELECT, INSERT, UPDATE ON feedback TO ssf_feedback_app;

-- The background jobs. UPDATE covers re-marking a redelivered row; DELETE and
-- the audit insert are the retention pass.
GRANT SELECT, UPDATE, DELETE ON feedback TO ssf_feedback_maintenance;
GRANT INSERT ON feedback_deletion_audit TO ssf_feedback_maintenance;
GRANT USAGE ON SEQUENCE feedback_deletion_audit_audit_id_seq TO ssf_feedback_maintenance;

-- Defence in depth, with an honest limit: this subjects the table's owner to
-- its own policy, but a superuser bypasses RLS whatever this says. It earns its
-- place only once the owner is a non-superuser, which is the direction to move
-- in; it is here so that change is a one-line role edit and not a migration.
ALTER TABLE feedback FORCE ROW LEVEL SECURITY;

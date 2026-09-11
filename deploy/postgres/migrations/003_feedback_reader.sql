-- The authorised read path's role.
--
-- Neither existing role can serve Studio reads. `ssf_feedback_app` is the
-- unauthenticated submit path: #318 records that it must gain nothing, and it
-- deliberately holds no SELECT on feedback_access_audit. `ssf_feedback_maintenance`
-- is BYPASSRLS, so reading through it would leave tenant isolation enforced
-- only by Python -- one missing WHERE clause from serving another tenant's
-- feedback to a signed-in operator.
--
-- So: a third role, NOBYPASSRLS like the request path, which puts
-- feedback_tenant_isolation from 001 in the path of every read. A read bound
-- to the wrong tenant returns no rows rather than the wrong rows.
--
-- Passwords arrive as psql variables from apply.sh, so this file holds none.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssf_feedback_reader') THEN
        CREATE ROLE ssf_feedback_reader;
    END IF;
END
$$;

ALTER ROLE ssf_feedback_reader
    WITH LOGIN PASSWORD :'reader_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT CONNECT ON DATABASE :"database" TO ssf_feedback_reader;
GRANT USAGE ON SCHEMA public TO ssf_feedback_reader;

-- SELECT only. A read path that can change or remove a record is not a read
-- path, and withdrawal (#318) deliberately stays out of this role until it has
-- its own reviewed route.
GRANT SELECT ON feedback TO ssf_feedback_reader;

-- The audit is written by the role that performs the read, so a disclosure
-- cannot be made without one. SELECT so an operator can later be shown who
-- read what.
GRANT SELECT, INSERT ON feedback_access_audit TO ssf_feedback_reader;
GRANT USAGE ON SEQUENCE feedback_access_audit_audit_id_seq TO ssf_feedback_reader;

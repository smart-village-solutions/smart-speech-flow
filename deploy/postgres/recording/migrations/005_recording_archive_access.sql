-- Recording mode (#616): the employee's own archive (spec §10.6). Applied by
-- ../../apply.sh after 004; idempotent. No new grants: the list and the open
-- read what 003 already lets the application role read.

CREATE INDEX IF NOT EXISTS key_wraps_user_recipient
    ON key_wraps (tenant_id, recipient_kind, recipient_ref);

CREATE INDEX IF NOT EXISTS conversations_employee_started
    ON conversations (tenant_id, employee_sub, started_at DESC, conversation_id DESC);

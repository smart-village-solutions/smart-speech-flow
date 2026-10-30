-- Leavers (#617d, spec §9.8): when an org admin retired a user's key without a
-- successor. Applied by ../../apply.sh after 008. Every statement is idempotent.

ALTER TABLE user_keys ADD COLUMN IF NOT EXISTS left_at TIMESTAMPTZ;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_keys_left_retired') THEN
        ALTER TABLE user_keys ADD CONSTRAINT user_keys_left_retired
            CHECK (left_at IS NULL OR retired_at IS NOT NULL);
    END IF;
END
$$;

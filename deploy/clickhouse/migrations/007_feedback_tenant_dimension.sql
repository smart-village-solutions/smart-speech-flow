-- A tenant dimension for the feedback aggregate.
--
-- #325. `feedback_submitted` was the one quality event with no tenant
-- reference: 005 added `tenant_ref` to silver for `translation_message` and
-- `session_lifecycle`, and 006 restated that projection, but nothing emitted
-- the attribute for a feedback row, so the column was always empty. The
-- emitter now populates it, and this gives gold somewhere to group it.
--
-- Gold only. Silver needs no change: the column exists from 005 and 006
-- projects it for every row, feedback included -- which is also why this
-- migration does not touch `quality_events_mv`, and why the schema-contract
-- guard reads the newest migration that redefines that view rather than the
-- newest file.
--
-- ROWS WRITTEN BEFORE THIS DEPLOY carry the missing reference. Aggregate rows
-- that already exist keep `tenant_ref = ''` and go on collecting submissions
-- from the days before the emitter shipped. Every tenant breakdown therefore
-- has a start date, and the dashboard panel says so.

-- One statement, deliberately. MODIFY ORDER BY may only append a column that
-- the same ALTER added: an existing column may already be out of order within
-- a part, so ClickHouse refuses to promote one into the sorting key. Split in
-- two this reads fine and fails at apply time.
--
-- And no DEFAULT clause, unlike every column 002-006 add. ClickHouse also
-- refuses a sorting-key column that carries a default expression (verified
-- against 26.3.17: "Newly added column tenant_ref has a default expression").
-- Nothing is lost by omitting it: a String's implicit default is already '',
-- which is what existing aggregate rows read as.
--
-- Appended last, after `feedback_form_version`, so every prefix of the old key
-- still sorts the way the existing parts are written.
ALTER TABLE feedback_daily
    ADD COLUMN IF NOT EXISTS tenant_ref LowCardinality(String),
    MODIFY ORDER BY (
        event_date, deployment_env, service_version, feedback_form_version, tenant_ref
    );

-- MODIFY QUERY replaces the whole view, so 006's projection is restated in
-- full. Dropping a line here would leave its column in place and silently fill
-- it with defaults -- no error, no missing column, just zeros where the
-- ratings were.
ALTER TABLE feedback_daily_mv MODIFY QUERY
SELECT
    toDate(emitted_at_utc)                  AS event_date,
    deployment_env,
    service_version,
    feedback_form_version,
    tenant_ref,
    uniqExactState(event_id)                AS submissions,
    -- The denominator a response rate divides by is counted from
    -- session_lifecycle, not from here; this is the numerator's session set.
    uniqExactState(session_ref)             AS sessions,
    avgState(translation_quality)           AS translation_quality_avg,
    avgState(performance)                   AS performance_avg,
    avgState(usability)                     AS usability_avg,
    avgState(net_promoter_score)            AS net_promoter_score_avg,
    uniqExactStateIf(event_id, net_promoter_score >= 9) AS promoters,
    uniqExactStateIf(event_id, net_promoter_score <= 6) AS detractors
FROM quality_events
WHERE event_type = 'feedback_submitted'
GROUP BY event_date, deployment_env, service_version, feedback_form_version, tenant_ref;

# Change: Show conversation minutes in the staff dashboard

## Why

Staff need to compare SSF usage with interpreter costs. Interpreters are paid
throughout a conversation, including pauses, so usage must measure elapsed
conversation time rather than the duration of translated audio.

## What Changes

- Show personal, current-organisation and deployment-wide conversation minutes
  for a rolling 30-day window in the authenticated staff dashboard.
- For each scope, show the total across all languages and a breakdown by the
  configured customer language, labelled only with that language (for example,
  Arabic or Ukrainian), without the staff language or a language pair.
- Attribute elapsed intervals to the language configured during each interval.
  A language change splits usage at the change timestamp; both translation
  directions and pauses belong to that interval without double counting.
- Count from the first activation until termination, including pauses and time
  until automatic termination. Exclude waiting before activation and sessions
  that never activate. Include ongoing conversations up to the query time.
- Count only the overlap with the reporting window, once per conversation,
  regardless of the number of participants or translation directions.
- Persist the first activation timestamp and timestamped language changes, and
  retain durable usage metadata independently of short-lived conversation content.
- Keep personal attribution inside the gateway. Return only aggregate totals,
  language breakdowns and coverage metadata; do not add owner references to logs
  or quality telemetry.
- Clearly identify the start of trustworthy measurement. Never invent historical
  activation times or present incomplete history as a complete 30-day total.

## Impact

- New capability: conversation-usage-reporting.
- Affected code: gateway session lifecycle and persistence, authenticated admin
  routes, frontend dashboard, localisation and relevant tests.
- Existing session-duration telemetry measures creation to termination and
  remains unchanged; it is not the definition of this new metric.
- Preserve the existing admin-session-ownership contract: individual sessions
  and owner references are not exposed through reporting.
- Implementation requires approval of this proposal before code changes.

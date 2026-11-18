## ADDED Requirements

### Requirement: Elapsed conversation time

SSF SHALL measure conversation usage from the first transition to active until
termination, or the query time for an ongoing conversation. Pauses and temporary
disconnects SHALL count until termination. Time before activation and sessions
that never activate SHALL contribute zero. Each conversation SHALL count once,
including both translation directions without multiplying by participant count.
Changing languages or activating again SHALL NOT reset the first activation.

#### Scenario: Conversation with pauses

- **WHEN** a conversation waits five minutes before activation, remains active
  for twenty minutes including pauses, and then terminates
- **THEN** it contributes twenty conversation minutes

#### Scenario: Automatic termination

- **WHEN** an activated conversation is automatically terminated after inactivity
- **THEN** its elapsed time through termination counts, including inactivity

#### Scenario: Conversation never starts

- **WHEN** a pending session terminates without activation
- **THEN** it contributes zero conversation minutes

### Requirement: Rolling thirty-day reporting

SSF SHALL calculate personal, current-organisation and deployment-wide totals
using one query timestamp and the preceding thirty times twenty-four hours.
Only the overlap of each conversation interval with this window SHALL count.
Durations SHALL be summed before conversion to displayed minutes. Lifecycle
updates SHALL be idempotent and usage SHALL survive gateway restarts and normal
conversation-content expiry. Reporting failures SHALL produce an unavailable
state rather than a successful zero total.

#### Scenario: Conversation crosses the window boundary

- **WHEN** a conversation starts ten minutes before the reporting window and
  ends fifteen minutes inside it
- **THEN** it contributes fifteen minutes

#### Scenario: Ongoing conversation

- **WHEN** a conversation started ten minutes ago and is still active
- **THEN** it contributes ten minutes at the query timestamp

#### Scenario: Reporting storage unavailable

- **WHEN** reporting storage cannot be queried
- **THEN** the dashboard indicates that usage is unavailable

### Requirement: Authenticated aggregate access

The reporting endpoint SHALL derive the requesting owner and organisation from
the verified identity. Personal totals SHALL count conversations created by that
owner in the current organisation. Organisation totals SHALL include all owners
in that organisation. Server totals SHALL include all organisations within the
deployment. Responses SHALL expose only totals, the reporting window and data
coverage and aggregate language breakdowns, without individual conversations,
other organisations' subtotals or
owner references. Owner attribution SHALL remain internal to the gateway and
SHALL NOT be emitted into logs or quality telemetry.

#### Scenario: Staff member requests dashboard usage

- **WHEN** an authenticated staff member requests usage
- **THEN** the response contains their personal total, their organisation's total
  and the deployment total, each with a language breakdown, without exposing
  other owners or organisations

#### Scenario: Unauthenticated request

- **WHEN** an unauthenticated client requests usage
- **THEN** access is denied

### Requirement: Conversation duration by language

For each reporting scope SSF SHALL provide both the total across all languages
and a breakdown by configured customer language. Language labels SHALL show only
the customer language, such as Arabic or Ukrainian, without the staff language
or a language pair. Both translation
directions SHALL count towards the same language bucket. German SHALL NOT receive
a second copy of the same elapsed time merely because it is the staff language.

Usage SHALL be attributed to the customer language configured during each elapsed
interval, including pauses. A language change SHALL close the previous interval
and open the next at the same effective timestamp. Re-selecting the same language
SHALL NOT duplicate usage. Each interval SHALL be clipped to the reporting window
and termination or query timestamp. Missing language attribution SHALL use an
explicit unknown-language bucket rather than be discarded. The sum of unrounded
language durations SHALL equal the scope's all-languages duration. The dashboard
SHALL show the all-languages total and make its language breakdown available for
each of the three scopes.

#### Scenario: Both directions with pauses

- **WHEN** a twenty-minute German–Arabic conversation includes speech in both
  directions and pauses
- **THEN** it contributes twenty minutes to Arabic and twenty minutes to the
  all-languages total, without an additional German allocation

#### Scenario: Language labels in the dashboard

- **WHEN** the dashboard displays usage for conversations with German-speaking
  staff and Arabic-speaking customers
- **THEN** the language entry is labelled Arabic without German or a language pair

#### Scenario: Language changes during a conversation

- **WHEN** a conversation uses Arabic for ten minutes and then Ukrainian for
  fifteen minutes before termination
- **THEN** it contributes ten minutes to Arabic, fifteen minutes to Ukrainian
  and twenty-five minutes to the all-languages total

#### Scenario: Language interval crosses the reporting boundary

- **WHEN** the Arabic interval begins before the reporting window and lasts five
  minutes inside it, followed by ten minutes of Ukrainian
- **THEN** the window contains five Arabic minutes, ten Ukrainian minutes and
  fifteen minutes in total

#### Scenario: Language attribution is missing

- **WHEN** a trustworthy conversation interval has no known customer language
- **THEN** its duration appears in the unknown-language bucket and the total

### Requirement: Measurement coverage is explicit

SSF SHALL expose the beginning of trustworthy usage coverage and distinguish
incomplete coverage from a complete thirty-day window. Historical sessions
without a trustworthy activation timestamp SHALL NOT be assigned an invented
activation time. The dashboard SHALL label the three figures as conversation
minutes for the last thirty days and explain that pauses count. It SHALL display
incomplete-coverage information when applicable.

After an unclean shutdown or loss of canonical live session state, SSF SHALL
discard unconfirmed open usage projections, replay retained canonical metadata
where available and mark the reporting window incomplete from recovery time.
Known completed usage SHALL remain available. The coverage boundary SHALL
describe continuous complete measurement, rather than the oldest known row.

#### Scenario: Feature introduced less than thirty days ago

- **WHEN** trustworthy measurement began ten days ago
- **THEN** the dashboard identifies the measurement start and does not imply that
  the displayed total covers the entire thirty-day window

#### Scenario: Usage cannot be fully recovered after a crash

- **WHEN** the gateway restarts without a clean ledger shutdown and some canonical
  session metadata is no longer retained
- **THEN** known completed usage remains available, unconfirmed open rows do not
  contribute invented durations and the dashboard identifies incomplete coverage

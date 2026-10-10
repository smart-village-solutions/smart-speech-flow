## ADDED Requirements

### Requirement: Consent resolution reads contract v2

SSF SHALL resolve consent at activation from the storage policy of a live v2
runtime-configuration read. The resolution rules for `ask`, `disabled`,
answers, missing answers, failed reads and tenant conflicts SHALL stay as they
are.

#### Scenario: Storage disabled in v2

- **WHEN** the v2 storage mode is `disabled`
- **THEN** SSF records the consent status `policy_disabled`

#### Scenario: Content invalid, policy valid

- **WHEN** the v2 body has a valid storage policy and an invalid content section
- **THEN** consent is resolved from the policy as if the content were valid

### Requirement: Storage question follows the live mode

The guest consent screen SHALL show the storage question only when a live read
reports the mode `ask`. It SHALL hide the question, and send no consent, when
the mode is `disabled` or cannot be read. For a guest language Studio provides,
the question text SHALL be Studio's `storageQuestionHtml`; for every other
language it SHALL be the bundled text.

#### Scenario: Mode disabled

- **WHEN** the guest opens the consent screen and the live mode is `disabled`
- **THEN** no storage question is shown
- **AND THEN** the activation carries a negative answer

#### Scenario: Mode cannot be read

- **WHEN** the live mode read fails
- **THEN** no storage question is shown

#### Scenario: Studio provides the guest language

- **WHEN** the guest chose English and Studio provides English
- **THEN** the explanation and the storage question are Studio's texts

#### Scenario: Studio does not provide the guest language

- **WHEN** the guest chose Arabic and Studio does not provide Arabic
- **THEN** the explanation and the storage question are the bundled texts

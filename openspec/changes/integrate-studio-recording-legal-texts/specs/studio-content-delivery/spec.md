## ADDED Requirements

### Requirement: Studio recording legal wording
SSF SHALL consume the optional Studio `legalTexts` block, sanitize its HTML and use documentation consent and role-specific recording releases in the existing recording flow. Legal content SHALL NOT enable recording or change retention, permissions or the recording legal basis. Quality-session consent SHALL NOT be shown for documentation recordings.

#### Scenario: Legal texts without authorization
- **WHEN** Studio provides legal wording but no valid enabled recording policy
- **THEN** recording remains unavailable

#### Scenario: Source language fallback
- **WHEN** no legal localization matches the participant's language
- **THEN** the source localization is shown with its actual language identified
- **AND** it is not presented as a translation

#### Scenario: Per-section bilateral release
- **WHEN** a participant starts or resumes a recording section
- **THEN** the employee must explicitly release it and the guest must approve the served recording question
- **AND** dismissal or refusal does not start recording

#### Scenario: Wording changed while a request is open
- **WHEN** either party's effective release changes after it was reviewed
- **THEN** a stale affirmative answer is refused
- **AND** the archived evidence contains the exact accepted wording and source version

#### Scenario: Truthful status wording
- **WHEN** recording loses liveness while the server state remains on
- **THEN** the UI shows paused rather than Studio's running wording

#### Scenario: Existing configuration
- **WHEN** Studio sends no legal block
- **THEN** the existing consent texts, checks and recording lifecycle continue to work

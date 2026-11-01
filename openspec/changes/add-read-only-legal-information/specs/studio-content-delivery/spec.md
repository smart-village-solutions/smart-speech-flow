## ADDED Requirements

### Requirement: Read-only legal information
SSF SHALL make configured Studio legal wording readable from the guest consent and both conversation screens through an explicitly informational, close-only view. Reading, opening or closing the view SHALL NOT send consent, activate a session, release recording, enable storage or change retention. The view SHALL use existing safe rich-text rendering, identify the actual wording locale and source version, and remain available independently of Studio guest-language coverage.

#### Scenario: Guest reads source wording
- **WHEN** a guest language has no translated legal wording
- **THEN** the view shows the source wording and identifies its actual locale
- **AND** no consent or recording request is sent

#### Scenario: No legal wording configured
- **WHEN** Studio sends no valid legal block
- **THEN** the existing flow remains usable without an empty legal-information action

#### Scenario: Production backport
- **WHEN** the informational feature is rolled out before recording cutover
- **THEN** only the narrowly reviewed gateway/frontend changes are deployed
- **AND** existing policy, storage, sessions and infrastructure remain unchanged

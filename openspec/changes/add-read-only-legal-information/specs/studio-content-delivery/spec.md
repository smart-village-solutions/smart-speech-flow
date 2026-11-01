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

#### Scenario: Ordinary conversation entry
- **WHEN** a guest opens the ordinary conversation entry
- **THEN** a short localized introduction explains automatic translation, possible errors, and that starting does not grant documentation recording consent
- **AND** it explains that a planned recording requires separate information, any consent required by its applicable recording policy, and release of each recording section
- **AND** these two introduction paragraphs always come from the UI catalogue, irrespective of Studio explanation availability or wording
- **AND** optional Studio explanations are not displayed on the ordinary entry, preventing duplicate introductions and obsolete storage promises
- **AND** full counsel declarations are available through the separate informational dialog rather than displayed inline
- **AND** recording consent and participant releases remain in their respective recording steps

#### Scenario: Stable entry wording
- **WHEN** entry content settles or reaches its timeout
- **THEN** its reference legal information is captured for that session and route language
- **AND** delayed language lists, late content and reconnects do not replace the displayed wording
- **AND** source wording retains its actual language and locale-derived direction

#### Scenario: Source wording script and unknown language
- **WHEN** the source locale declares a recognized horizontal script
- **THEN** that script determines direction, including right-to-left Yezidi and explicit Latin overrides
- **WHEN** the source language is undetermined and has no explicit script
- **THEN** the reference region uses automatic direction rather than maximizing the tag to a guessed language

## MODIFIED Requirements

### Requirement: Hybrid guest languages

SSF SHALL keep its own guest language list. For a guest language Studio provides, guest-facing content Studio defines SHALL come from Studio, except for the ordinary conversation introduction. That introduction SHALL always use the UI catalogue's two controlled paragraphs and SHALL omit optional Studio explanations. For a guest language Studio does not provide, bundled texts SHALL be used unchanged. The staff language SHALL NOT be offered to guests. This exception SHALL NOT alter the existing guest-content response contract, reference legal wording or recording-policy controls.

#### Scenario: Partial Studio coverage
- **WHEN** Studio provides only English
- **THEN** English guests continue receiving applicable Studio content and guests choosing another SSF language use bundled fallback content
- **AND** the ordinary introduction uses the corresponding UI catalogue for both groups

#### Scenario: Legacy or already-updated Studio explanation
- **WHEN** an ordinary guest entry receives an optional Studio explanation with obsolete storage wording or a duplicate of the new introduction
- **THEN** the entry displays its two controlled UI paragraphs exactly once
- **AND** no Studio explanation, storage choice or inline counsel declaration is displayed there

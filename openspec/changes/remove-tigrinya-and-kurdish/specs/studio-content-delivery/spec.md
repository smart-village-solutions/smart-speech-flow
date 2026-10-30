## MODIFIED Requirements

### Requirement: Guest content routes

SSF SHALL serve `GET /api/customer/session/{session_id}/languages` and
`GET /api/customer/session/{session_id}/content/{language}` to holders of the
session key, including within the feedback grace period after the session
ends. The language list SHALL contain SSF's guest languages; entries Studio
provides SHALL carry Studio's native name and icon. The content route SHALL
return the live storage mode, or `unknown` when it cannot be read, and either
Studio's guest texts and feedback form for that language or `provided: false`.
Studio content SHALL NOT add unsupported languages to SSF's guest language list.

#### Scenario: Language provided by Studio

- **WHEN** the guest requests content for `en` and Studio provides `en`
- **THEN** the response carries Studio's explanation, storage question and
  feedback form

#### Scenario: Language not provided by Studio

- **WHEN** the guest requests content for `ar` and Studio does not provide it
- **THEN** the response carries `provided: false` and the live storage mode

#### Scenario: Unsupported locale mapping

- **WHEN** Studio provides `ti`, `ku`, `kmr`, or a regional variant of these locales
- **THEN** SSF skips that content as unsupported
- **AND** neither Tigrinya nor Kurdish appears in the guest language list

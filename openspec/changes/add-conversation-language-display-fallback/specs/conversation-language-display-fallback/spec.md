## ADDED Requirements

### Requirement: Separate conversation language from display locale

SSF SHALL use `/api/languages/supported` as the conversation-language source
and Studio `localization.defaultLocale` and `localization.locales` as the source
of reviewed display variants. Resolving display text SHALL NOT change the
selected conversation language or the existing language picker.

#### Scenario: Studio locale differs from conversation code
- **WHEN** the selected conversation language is `de` and Studio supplies `de-DE`
- **THEN** SSF may select its reviewed display text while retaining `de` as the conversation language

### Requirement: Resolve each Studio display field independently

For each supported field in a valid Studio runtime configuration, SSF SHALL
prefer a present matching Studio variant. If absent, SSF SHALL translate a
present German Studio variant, otherwise a present English Studio variant,
otherwise an SSF-owned English default for that field. New fields SHALL be
opted in explicitly with their text kind and default. Unsupported or failed
translation SHALL return the selected source text safely.

#### Scenario: Reviewed text wins
- **WHEN** a matching Studio locale supplies a field
- **THEN** SSF uses that field without machine translation

#### Scenario: German source is preferred
- **WHEN** the matching field is absent and German and English Studio values exist
- **THEN** SSF translates the German value into the selected language

#### Scenario: English Studio source is used
- **WHEN** the matching and German field values are absent but an English Studio value exists
- **THEN** SSF translates the English Studio value into the selected language

#### Scenario: SSF English display default is used
- **WHEN** the matching, German, and English Studio field values are absent
- **THEN** SSF translates the field's SSF-owned English display default

#### Scenario: Translation fails
- **WHEN** translation fails or the selected language is unsupported by translation
- **THEN** SSF returns the selected source text safely and does not invent a translation

### Requirement: Preserve safe display markup and storage applicability

SSF SHALL translate text content inside supported HTML fields without sending
markup as translatable prose. Resolved HTML SHALL be safe and structurally
valid. Plain-text fields SHALL use the same source order without HTML parsing.
When conversation-content storage mode is `disabled`, SSF SHALL omit its
storage question rather than generate a fallback.

#### Scenario: HTML text translation
- **WHEN** a Studio HTML field contains nested markup and text to translate
- **THEN** SSF translates only its text content and returns safe, valid HTML structure

#### Scenario: Storage is disabled
- **WHEN** the valid runtime configuration sets storage mode to `disabled`
- **THEN** SSF returns no conversation-content-storage question

# Change: Remove Tigrinya and Kurdish support

## Why

Tigrinya and Kurdish must no longer be offered as supported SSF languages.
Removing them only from the picker would leave API, Studio, and speech-service
contracts inconsistent.

## What Changes

- **BREAKING**: Remove `ti` and `ku` from supported language lists and reject
  them wherever SSF validates supported conversation or speech languages.
- Stop mapping Studio's `kmr` locale to `ku`; skip Kurdish and Tigrinya Studio
  content, including regional locale variants.
- Remove the bundled frontend catalogues, imports, and language-specific UI
  metadata for both languages.
- Remove their TTS voice registrations and dedicated speech-text rules; keep
  the Amharic MMS voice and shared processing intact.
- Align ASR and translation language discovery and validation with the removal.
- Update current documentation, mock fixtures, smoke/load scenarios, and tests.
  Keep negative tests that verify the removed languages are rejected.

## Impact

- Affected specs: `studio-content-delivery`,
  `studio-runtime-configuration-mock`, `supported-conversation-languages` (new).
- Affected code: Gateway language registry, validation and Studio mapping;
  frontend i18n and fixtures; ASR, translation and TTS services; test fixtures.
- Existing stored conversations and historical benchmark reports remain intact.
  Existing sessions using a removed language receive the normal unsupported
  language response when starting new processing; they are not reassigned to
  another language.
- No deployment, external Studio edits, or deletion of downloaded model caches
  is included in this repository change.

## Validation

Verify language discovery and selection exclude both codes, unsupported language
requests fail consistently, and Studio cannot reintroduce either language.
Run the affected gateway, service and frontend tests plus frontend type checking
and build. Confirm remaining languages, including Amharic, still work with the
existing mocked service tests; real model inference requires a running stack.

# Change: Add conversation-language display fallback

## Why

Conversation languages and Studio localization locales are separate contracts.
SSF needs a predictable way to prepare display text for a selected conversation
language when a valid Studio configuration lacks that language variant.

## What Changes

- Add an internal resolver for the three Studio Runtime Configuration V1 text fields.
- Prefer reviewed Studio text, then translate German Studio text, English Studio
  text, or a limited SSF-owned English display default per field.
- Keep HTML safe and structurally valid while translating its text content.
- Document the locale mapping and fallback order with focused behavior tests.

The proposed SSF-owned English fallback copy is
`<p>Smart Speech Flow helps people communicate across languages.</p>` for each
explanation field and `<p>May this conversation be stored?</p>` for the storage
question. These are display fallbacks only and never replace a present Studio
value.

The resolver does not expose a new route, connect screens, alter the language
picker, or change Studio's contract or implementation.

## Impact

- Affected specs: `conversation-language-display-fallback` (new).
- Affected code: Gateway runtime-configuration presentation logic and focused
  tests; Gateway dependency files for the HTML sanitizer.
- Affected docs: SSF architecture and OpenSpec only.
- Related: #300, parent #266, runtime client #297. The Studio contract wording
  correction remains a separate Studio follow-up.

# Conversation-language display fallback (#300)

## Context and scope

`GET /api/languages/supported` defines conversation and pipeline languages.
Studio Runtime Configuration V1 supplies reviewed display content under
`localization.defaultLocale` and `localization.locales`. These are different
contracts: selecting fallback display text must never change the conversation
language. The gateway already validates Studio configuration and has a
translation service, but no screen consumes these Studio fields yet.

This change supplies an internal SSF resolver and its behavior tests. It does
not add a route, connect a screen, change the language picker, change Studio,
or define tenant-specific conversation-language restrictions. A valid Studio
runtime configuration is a precondition; complete Studio failure and invalid
configurations retain their existing handling.

## Decision

Expose one internal operation that takes a validated runtime configuration and
the requested conversation-language code and returns resolved display values
for the known Studio text fields. Keep the conversation-language code as a
separate value; the resolver only reads it. The three V1 fields are
`authenticatedHomeExplanationHtml`, `guestExplanationHtml`, and
`conversationContentStorageQuestionHtml`.

Keep a small explicit field definition for each supported field: its Studio
name, plain-text or HTML kind, and SSF-owned English fallback. The V1 fields
are HTML. A future field is added deliberately with its own definition and
tests; unknown optional Studio fields are left untouched. One shared
resolution flow handles all definitions. No language catalogue, generated
schema, plugin system, or public response contract is needed.

## Locale selection and source order

Compare language tags case-insensitively. For each field, consider only locales
with a present value for that field. First prefer an exact tag match. Otherwise
consider locales with the same primary language subtag, such as `de` and
`de-DE`. Prefer `defaultLocale` when it belongs to that group; otherwise use
the first matching locale in the Studio response. This works as new languages
are added without an SSF language table. It makes the choice deterministic for
a given valid response even when Studio supplies several regional variants.

Resolve each field independently:

1. Use a present field from the matching Studio locale without translating its
   text. Reviewed Studio text always wins; HTML safety processing still applies.
2. Otherwise select present German Studio text using the same locale rule. If
   none exists, select present English Studio text.
3. If neither Studio source exists for this field, select its SSF-owned
   English fallback. This fallback is for display in a requested language;
   it does not replace or reinterpret Studio's configured values.
4. Translate the selected source into the requested conversation language.
   If source and target primary language already match, use the source without
   a translation request. If translation is unsupported, fails, or yields
   unusable output, use that source. Never synthesize an empty or invented
   translation.

`null`, absent, and blank text do not count as present. When storage mode is
`disabled`, the storage question remains absent and is never synthesized.
When storage mode is `ask`, it follows the normal field order. The resolver
does not make or alter storage-policy decisions.

## Text handling and failure behavior

Plain text goes to the translation service as plain text. For HTML, parse the
fragment, translate only text content, and serialize a safe fragment while
preserving the allowed structure. Markup, tag names, attributes, and URLs are
never submitted as prose. Unsafe markup is not returned merely because it
came from Studio. If parsing or translation cannot produce safe, valid HTML,
return the safe source fragment. Preserve the translation service's existing
language-code behavior; an unsupported target follows the source-text
fallback. Do not add a provider-code mapping or translation cache for this
issue.

## Verification and documentation

Use focused, table-driven tests for each V1 field: matching reviewed Studio
text; German, English, and SSF-English translation sources; translation
failure; and an unsupported target. Cover regional locale selection, changing
conversation languages without a hard-coded list, the storage-disabled case,
and safe HTML with nested elements and attributes. Test plain text through a
field definition in isolation so a future plain-text Studio field uses the
same resolver without changing its algorithm. Tests assert that the requested
conversation language is unchanged.

Update current SSF architecture and OpenSpec documentation with this source
order, the limited SSF-owned English display fallback, and the separation of
conversation language from Studio locale. The older Studio V1 contract note
about product defaults remains a separate Studio follow-up, not a closure
criterion for #300.

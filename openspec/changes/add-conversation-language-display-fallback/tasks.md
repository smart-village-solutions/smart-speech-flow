## 1. Internal text resolution

- [x] 1.1 Add field definitions and locale selection without a fixed list of conversation languages.
- [x] 1.2 Resolve each field in reviewed Studio, German, English, SSF English order; preserve the conversation language and omit the storage question when storage is disabled.
- [x] 1.3 Integrate the existing translation service and fall back to the selected safe source on failure or unsupported language.
- [x] 1.4 Sanitize HTML and translate only its text content; support plain-text field definitions.

## 2. Verification and documentation

- [x] 2.1 Cover all source branches and translation failure for every V1 field, plus locale matching, storage policy, plain text, and HTML safety.
- [x] 2.2 Update SSF architecture documentation with the source order and limited SSF-owned default.
- [x] 2.3 Run focused tests and strict OpenSpec validation.

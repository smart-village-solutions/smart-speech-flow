# Change: Add Studio text translation on Havelland

## Why

Magdeburg staging reached its DeepL quota while testing multilingual dynamic content. A Studio provider adapter can reuse the existing translation jobs and call the Smart Speech Flow (SSF) text API on Havelland.

## What Changes

- Use SSF's own opt-in version 1 API for language discovery and batch text translation.
- Reuse the bounded translation engine and conversation-priority controls from SSF PR #712, updating the implementation against current main.
- Give Studio a trusted server-side provider origin and a dedicated credential for the pilot instance.
- Limit the Studio change to provider selection and a server-side adapter. Keep existing translation jobs, content handling and placeholder protection on the shared path.
- Pilot on the Havelland SSF host with Magdeburg staging as the caller. Verify German-to-English, German-to-Polish and German-to-Japanese with representative Studio content before enabling each target.

## Impact

- Affected specs include `studio-text-translation` and `api-gateway-modular-architecture`.
- Affected code includes the SSF gateway, strict translation service, admission control and production deployment configuration. Studio needs a provider adapter for the SSF HTTP contract and pilot batch limits.
- The laboratory API in [SSF PR #712](https://github.com/smart-village-solutions/smart-speech-flow/pull/712) is a reuse candidate. Its current branch conflicts with main and its laboratory limits must be reconciled with Studio.
- The pilot covers written text translation and language discovery. It starts with a single background request executing at a time.

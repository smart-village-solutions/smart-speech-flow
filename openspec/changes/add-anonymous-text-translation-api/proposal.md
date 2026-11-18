# Change: Add a shared-key text translation API

## Why

Laboratory integrations need a rarely used, session-independent text-to-text
translation API, similar in usability to DeepL's translate endpoint. V1 targets
occasional laboratory calls rather than a general public translation service.
The existing M2M100 service
already translates strings and lists, but its internal contract, truncation
behavior and shared GPU use are unsuitable for direct public exposure.

## What Changes

- Add shared-key-protected `POST /api/v1/translate` and `GET /api/v1/languages` gateway
  routes. A fixed shared `X-API-Key` is required; no Keycloak login or per-user key
  management is required.
- Require a text array and explicit source and target language codes; return
  one translation per input in the original order.
- Initially allow at most 10 entries and 5,000 Unicode code points across the
  entire array, with independent request-body and inference-work bounds.
- Split long inputs automatically using the model tokenizer and sentence and
  paragraph boundaries; preserve paragraph structure and prevent silent input
  and output truncation.
- Keep calls synchronous with a small, bounded in-memory queue. Give live
  conversation work priority and run at most one API segment at a time, only
  when conversation processing permits background work. Reuse service circuit
  breakers and inference admission. A dedicated load test was waived by the
  owner for the rare laboratory workload on 2026-11-17.
- Keep requests independent of conversations, tenant configuration, ASR, TTS,
  refinement and content persistence.
- Extend the gateway architecture specification with an explicit text-only
  exception to the session-only processing rule; retain retired route 404s.

## Impact

- Affected specs: `text-translation-api` (new),
  `api-gateway-modular-architecture` (modified).
- Affected code: gateway routes, dependency composition, translation adapter,
  admission/rate limiting, translation-service tokenization and generation,
  gateway contracts, tests, deployment configuration and API documentation.
- Related active work: `add-pipeline-admission-control`,
  `add-live-service-resilience-path`, `stabilize-production-operations`.
  Reuse their current runtime mechanisms; do not restore retired endpoints
  mentioned in older proposal text.
- This is an additive API, not a promise of DeepL wire or SDK compatibility.
- V1 has no durable queue, job IDs, polling endpoint or additional broker.
- Later extensions: user API keys and quotas, automatic source-language
  detection, optional refinement, asynchronous large-document translation.

## Approval and release

The user approved implementation after reviewing anonymous access, long-text
handling and conversation priority, and clarified that V1 is for occasional
laboratory use. Runtime implementation is authorized under the project
OpenSpec workflow. On 2026-11-17 the owner waived the dedicated load test based
on stable observed server utilization and rare laboratory usage. Finite
operating defaults and conversation priority remain in force; the feature
remains opt-in. No mixed-load benchmark has been performed.

The owner subsequently clarified that no Keycloak login does not mean
anonymous access: V1 requires one fixed server-configured X-API-Key. This
correction is implemented and deployed, with the existing internal callback
token kept separate.

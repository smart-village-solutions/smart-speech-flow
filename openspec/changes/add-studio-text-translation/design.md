# Design

## Integration and HTTP contract

Studio's DeepL integration provides a functional reference for language discovery and ordered batch translation. The pilot uses the SSF HTTP contract already proposed in PR #712. Studio's provider adapter maps SSF languages to Studio locales and reuses Studio's batching, job handling and marker restoration.

The public [DeepL terms, section 8.1.1(f)](https://www.deepl.com/en/pro-license) restrict customers' use of DeepL services, documentation and other supplied materials to create a similar machine-learning product, service or API. Which terms govern the Studio account and how they apply here are open questions. [Section 69a(2) UrhG](https://www.gesetze-im-internet.de/urhg/__69a.html) and [CJEU judgment C-406/10](https://eur-lex.europa.eu/legal-content/EN/SUM/?uri=celex%3A62010CJ0406) distinguish functional interface principles from protected program expression. That copyright distinction leaves the contractual question open.

Studio calls `GET /api/v1/languages` and `POST /api/v1/translate` with `X-API-Key`. An SSF-issued secret identifies the Magdeburg staging instance. Studio selects the SSF origin through trusted server-side configuration scoped to the pilot. Use the same origin for verification and translation, retain redirect rejection, and avoid exposing an arbitrary outbound URL in instance configuration. Use synthetic inputs and SSF output in pilot tests.

Discovery returns an object with the SSF `languages` list. The Studio adapter checks for German source support and offers validated target codes. Use base language codes such as `en`, `pl` and `ja` for the pilot.

Translation accepts `text`, `source_lang` and `target_lang` and returns the SSF response with `translations`, `source_lang` and `target_lang`. Each translation entry has a `text` field. Use German as the explicit source for the pilot. The whole request succeeds or fails. Check the actual Studio-generated `SVA<nonce>X<index>Z` markers per entry. Protect them during inference and validate their exact multiplicity and order before returning a result. Reject any output that fails marker verification. Retain the strict path's bounded segmentation and incomplete-output detection.

## Studio integration

Select the provider at the existing server-side translation boundary. The adapter handles connection verification, language mapping, the SSF key and HTTP response parsing, and translates SSF errors into the existing job error handling. Reuse the existing batching algorithm with provider-specific limits and the same placeholder protection and restoration. Magdeburg staging selects SSF through configuration. The content editing workflow and job lifecycle stay on the existing Studio path.

## Admission and limits

The laboratory path starts at 10 entries and 5,000 Unicode code points per request. The inspected Studio client batches up to 50 entries and 102,400 encoded JSON bytes and imposes a 30-second translation timeout. Measure representative jobs, then document a common envelope before the pilot. If Havelland cannot serve Studio's current batch envelope within its timeout, configure smaller SSF-specific batches in Studio and surface an explicit terminal error when one entry exceeds the supported limit. Apply server limits independently of the client. Bound the queue and inference work, keep one background request executing at a time, and allow conversation work between background segments. Return `429` for caller rate limits and `503` for temporary capacity exhaustion with `Retry-After`. Coordinate Studio's retry budget and timeout with the server deadline.

The pilot reuses the deployed translation model. Measure active conversation latency, translation latency and GPU memory under representative mixed load. Record the baseline and agree on acceptance thresholds before enabling the pilot. Retain only operational metrics such as outcome, latency and size. Keep source text, translations and credentials out of logs, telemetry and persistence.

## Rollout and rollback

- Validate the reconciled PR #712 release artifacts against the running Havelland installation. The core gateway and speech translation use separate Compose projects on the shared backend network. Scope image and environment updates to those two services and record the running images for rollback.
- Configure the Havelland allowlist as `de,en,pl,ja` once the target checks pass. Set the SSF gateway client key and internal service token through the deployment configuration. Set `SVA_SSF_TRANSLATION_INSTANCE_ID`, `SVA_SSF_TRANSLATION_ORIGIN`, `SVA_SSF_TRANSLATION_LOCALES` and the corresponding `SVA_SSF_TRANSLATION_API_KEY` secret for the Studio pilot.
- Deploy the SSF routes behind a disabled-by-default setting. Enable them on Havelland for a dedicated pilot credential, verify the running contract, and switch Magdeburg staging only after the compatibility and mixed-load checks pass.
- To roll back, restore the previous Studio provider configuration and disable the Havelland routes or revoke the pilot credential. Restoring DeepL restores the previous provider selection. Successful translation still depends on an available DeepL quota.

## Verification status

The deployed Havelland model reported German, English, Polish and Japanese availability. One synthetic two-item request per target completed through the existing internal model endpoint in 0.22–0.24 seconds. This is a model baseline. The candidate API, marker protection and concurrent conversation latency still require verification against the release artifacts.

# Anonymous laboratory text API release

Deployed on 2026-11-17 from source
`84bfd311ba227c47d7277ef3815748fa33b9ef6c`, including current main `2355aecc`.
The owner authorized activation and deployment, followed by a pull request
after successful verification. Dedicated load testing was explicitly waived
for rare laboratory usage based on stable observed server utilization.

## Installed images

| Service | Image | Image ID |
| --- | --- | --- |
| Gateway | `ssf-backend-api_gateway:prod-lab-key-84bfd311` | `sha256:a7389751923380dacd1ab3ed7080a75482a976564ef54c7d5feb2ff0dd634fa1` |
| Translation | `ssf-backend-translation:prod-lab-key-84bfd311` | `sha256:7057235079109153068edef2e1a6c76cfb686e5461d348fd885ce54ba902125b` |

`deploy/production/Dockerfile.text-translation` copies application code onto
the audited, installed gateway and translation runtimes. This promotion does
not change Python dependencies, CUDA or the model selection. Both images carry
the source revision label. Build from an immutable source export:

```bash
git archive 84bfd311ba227c47d7277ef3815748fa33b9ef6c | tar -x -C "$RELEASE_SOURCE"
docker build --network=none --target gateway \
  --build-arg SOURCE_REVISION=84bfd311ba227c47d7277ef3815748fa33b9ef6c \
  -f deploy/production/Dockerfile.text-translation \
  -t ssf-backend-api_gateway:prod-lab-key-84bfd311 "$RELEASE_SOURCE"
docker build --network=none --target translation \
  --build-arg SOURCE_REVISION=84bfd311ba227c47d7277ef3815748fa33b9ef6c \
  -f deploy/production/Dockerfile.text-translation \
  -t ssf-backend-translation:prod-lab-key-84bfd311 "$RELEASE_SOURCE"
```

`RELEASE_SOURCE` must be an empty existing directory; run each build from that
source directory or give the Dockerfile's absolute path. Verify the base images
against their retained IDs below before building. Canonical production Compose
and `known-good-images.lock` record the promoted images. Only the gateway and
translation containers were recreated; the other platform services were left
in place.

## Activation and verification

The host's untracked `.env` has `SSF_TEXT_TRANSLATION_ENABLED=1` and a generated
private `SSF_TEXT_TRANSLATION_INTERNAL_TOKEN`, passed identically to both
services. The token is never committed or required from API clients.
`SSF_TEXT_TRANSLATION_LANGUAGES=de,en,fr,es,ar,tr` selects V1 languages. The API
remains disabled by default for other installations.

When deploying these services, start translation first and wait for its model
to load before recreating the gateway. Cold model loading can otherwise trip
the gateway's translation breaker; the gateway was recreated after model
readiness during this rollout. Existing gateway environment values were
compared with the rendered configuration; only the intended API environment variables changed.

Verification passed:

- Project-pinned hermetic suite after integrating main: 5,342 passed,
  52 skipped and 22 deselected. Earlier gateway MyPy checked 215 modules;
  feature commit hooks passed formatting, lint, typing and security checks.
- `scripts/deploy-production.sh --check` and
  `scripts/production-health-check.sh --timeout-seconds 60` passed.
- Public `GET https://api.dialog.kassel.de/api/v1/languages`: 200 and the six
  configured language codes. The legacy API host serves the route too.
- Anonymous ordered batch translation: 200; two synthetic German texts
  produced two English results in approximately 0.8 seconds.
- A 1,577-character synthetic text translated in approximately 2.2 seconds,
  preserving its paragraph separator.
- Missing source language: 422 `INVALID_REQUEST`; 5,001 characters: 413
  `CHARACTER_LIMIT_EXCEEDED`; exhausted caller allowance: 429
  `RATE_LIMIT_EXCEEDED` with `Retry-After`.
- Anonymous access to the private activity route: 404. API responses carry
  `Cache-Control: no-store`. Full platform health reports ASR, translation and
  TTS healthy.

These are functional smoke checks, not a load benchmark or a guarantee of
unchanged conversation latency. The bounded queue, conversation priority and
503 `SYSTEM_BUSY` contract remain enforced and covered by hermetic tests.

## Rollback

The previous images remain installed:

- Gateway: `ssf-backend-api_gateway:prod-24c088e8`,
  `sha256:d4707f8e8e8292c92f0902dce87d2e14c669188fc927a9395daef823d5d12098`.
- Translation: `ssf-backend-translation:prod-2acde0bd`,
  `sha256:928bfcde85dd612fd32cdf620ba63604346e1eef27ae630a46045e22c0e36a91`.

To disable just the feature, set `SSF_TEXT_TRANSLATION_ENABLED=0` in the host
environment and recreate the two services. To restore the old code, restore
these image pins, recreate translation, wait for model readiness, then recreate
the gateway. Update canonical Compose and the audit lock to match the verified
running images. The protected host rollout directory
`/root/projects/ssf-operations/anonymous-text-api-20261117` contains the previous
environment, configuration, image IDs and an image rollback override. Do not
publish its environment backup or the private service token.

## Fixed shared-key correction

The owner clarified that V1 must require a fixed shared client API key without
Keycloak login or per-user key management. Both `/api/v1/translate` and
`/api/v1/languages` now require `X-API-Key`; the earlier anonymous examples and
smoke checks above describe the initial rollout and are superseded by this
access contract. Missing or incorrect keys return 401 `INVALID_API_KEY` before
rate accounting or translation. A missing configured key returns 503.

The operator key is retained across restarts in the host's protected `.env` as
`SSF_TEXT_TRANSLATION_API_KEY`, with a root-only operator copy at
`/etc/ssf/text-translation-api-key`. It is distinct from the private callback
token and is passed only to the gateway. Never commit its value or put it in
a query string. Client examples use `-H "X-API-Key: $SSF_API_KEY"`.

The gateway enforces client-key access. The translation service was also
promoted with a tested expiry fix that preserves known busy state during a
pending activity refresh. When rolling back to
an older image without client-key support, disable the feature rather than
restoring anonymous access.

The shared-key correction is deployed and verified: both public endpoints
return 401 INVALID_API_KEY for missing/wrong keys; valid-key language discovery
and an actual ordered translation return 200. Full platform health passed.
The corrected pinned hermetic suite passed 5,351 tests (52 skipped, 22
deselected), and independent review found no material issues. No secret values
were printed, committed or placed in the image layers.

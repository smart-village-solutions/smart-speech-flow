## 1. v2 models and clients (backend, not wired)

- [ ] 1.1 Add `studio_v2.py` with the policy view and lenient content models for the runtime and installation bodies, including feedback question unions and cross-field checks
- [ ] 1.2 Add fixtures from the production responses (both tenants, installation) and negative cases per validator
- [ ] 1.3 Add `StudioRuntimeV2Client` and `StudioInstallationClient`; accept `2.x` bodies and `1.x`/`2.x` error envelopes
- [ ] 1.4 Build one shared `StudioRuntimeTokenProvider` in the lifespan and inject it into all Studio clients

## 2. Studio mock on v2

- [ ] 2.1 Serve both v2 endpoints in `services/studio_mock`, keep `/v1/admin-login-tenants`
- [ ] 2.2 Add fixtures: `ask` tenant, `disabled` tenant, `retentionHours` 0 tenant, guest languages `en`, `tr`, `ar` (null icon), `kmr`, `pt-BR`
- [ ] 2.3 Add the `storage-disabled` and `invalid-content` scenarios and a v2 error envelope
- [ ] 2.4 Update the mock contract and compose tests

## 3. Cutover to v2

- [x] 3.1 Move session create, activation and the persistence gate to the v2 client
- [x] 3.2 Authorize persistence with one live read per message and record the decision per artefact
- [x] 3.3 Replace `Session.runtime_configuration` with `configuration_revision`; keep `from_dict` reading v1 records, with a test
- [x] 3.4 Remove the v1 runtime client, `presentation_configuration.py` and `display_text_fallback.py`; move the nh3 sanitiser to `studio_html.py`
- [x] 3.5 Rewrite the affected test builders and suites; regenerate the OpenAPI snapshot
- [x] 3.6 Run the tenant isolation matrix by hand against a rebuilt image

## 4. Per-session retention

- [x] 4.1 Capture `consent_retention_hours` and `consent_configuration_revision` at activation when consent is granted
- [x] 4.2 Apply the session value to the message text sweep and the terminal record TTL; add `SSF_TERMINAL_RECORD_HOURS` for sessions without granted consent
- [x] 4.3 Write the audio `retention.json` marker and read it in the cleanup walk, falling back to the short default
- [x] 4.4 Prune expired members from the tenant session index
- [x] 4.5 Remove `SSF_CONTENT_RETENTION_HOURS` and the unused `AUDIO_RETENTION_HOURS`; forward `STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS` in production compose; update `production.env.example`

## 5. Content cache and browser routes

- [ ] 5.1 Add `StudioContentCache` for tenant content and the installation content cache, both serving stale on error
- [ ] 5.2 Add `GET /api/content/installation` with ETag and cache headers
- [ ] 5.3 Add `GET /api/customer/session/{session_id}/languages` and `.../content/{language}`, including the feedback grace period and the live storage mode
- [ ] 5.4 Add `GET /api/admin/content`
- [ ] 5.5 Map Studio locales to SSF codes with aliases; count skipped locales

## 6. Frontend: feedback form from a definition

- [ ] 6.1 Introduce `FeedbackFormDefinition` and build the bundled form from i18n keys with Studio's question ids
- [ ] 6.2 Render rating, scale and longText questions generically with required validation; keep the v1 submission payload unchanged
- [ ] 6.3 Change `openFeedback` to a context of public, guest or staff and update its call sites

## 7. Frontend: content layer, safe markup, start and login pages

- [ ] 7.1 Add `src/domain/content` (types, port, repository, zod mapper) and wire it into the services
- [ ] 7.2 Add the `RichText` pattern and a test that forbids `dangerouslySetInnerHTML`
- [ ] 7.3 Use installation texts on the start and login pages, with bundled fallback

## 8. Frontend: legal links, logo and favicon

- [ ] 8.1 Add legal links to every page, below the microphone row on conversation screens; specify the measurements in `SCREEN_SPECS.md` first
- [ ] 8.2 Use the Studio logo in the header and the Studio icon as favicon, with the static assets as fallback

## 9. Frontend: guest screens

- [ ] 9.1 Show Studio names and icons in the language picker for Studio-provided languages
- [ ] 9.2 Use Studio explanation and storage question for Studio-provided languages; hide the question when the mode is `disabled` or unknown
- [ ] 9.3 Prefetch guest content on the language screen

## 10. Frontend: staff screens

- [ ] 10.1 Use Studio staff texts on the dashboard, system-load card (`unknown` stays bundled) and invite dialog
- [ ] 10.2 Show staff language names and format staff timestamps in the tenant time zone
- [ ] 10.3 Keep the tenant display name off every page

## 11. Feedback backend

- [ ] 11.1 Add Postgres migration `004` for answers by question id, form snapshot and encrypted text answers; re-check grants
- [ ] 11.2 Validate submissions against the form of their revision in the service layer
- [ ] 11.3 Add `POST /api/admin/feedback` filed under the token's tenant; keep `POST /api/feedback` for guest and installation feedback
- [ ] 11.4 Update the read API and the maintenance re-emit path

## 12. Feedback analytics

- [ ] 12.1 Emit `feedback_submitted` and per-answer `feedback_answer` events with deterministic ids
- [ ] 12.2 Add ClickHouse migration `008` and update the Grafana feedback panels

## 13. Frontend: Studio feedback forms

- [ ] 13.1 Use Studio forms for each audience and submit them to the new payload with revision and locale

## 14. Monitoring and cleanup

- [ ] 14.1 Alert on Studio policy read failures and stale content; retune the audio disk thresholds for 180 days
- [ ] 14.2 Remove dead i18n keys and code; update `services/api_gateway/README.md` and the architecture docs
  - Stop writing the v1 `runtime_configuration` key in `Session.to_dict` (`_previous_gateway_snapshot`) only once rolling back to a gateway image from before the cutover is ruled out; without the key that gateway quarantines every newer session record
  - Remove the v1 fallback in `Session.from_dict` only after a scan of production Redis finds no session record without `configuration_revision`; terminal records live as long as their content retention, and retention `0` never expires them, so elapsed time alone does not prove they are gone
- [ ] 14.3 Deploy with Postgres `004`, ClickHouse `008` and a Prometheus restart; verify against production

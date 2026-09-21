# SonarCloud Issue Ledger

This immutable ledger replaces the superseded July 101-issue WP-A–E ledger,
which remains in Git history. The approved baseline is `main` revision
`114574a9789256b8bbc06640af962b769285ca70`, analyzed at 2026-09-18 08:16:39 UTC
under analysis ID `e648dbdd-4091-461b-99e9-684d785faf62` for project
`smart-village-solutions_smart-speech-flow`: **163 issues, 5 vulnerabilities,
158 code smells, and 0 bugs**.

The keys were derived from the eight execution task reports and reconciled
against the live `main` issues API on 2026-09-20. The latest main analysis still
matches the immutable revision and analysis ID. Verification found 163 unique
keys, zero duplicates, zero missing keys, and zero extra keys. Each file has
exactly one owning task/package. New PR findings are tracked in the execution
evidence in [tasks.md](tasks.md), without changing this baseline.

## Package and PR ownership

| Owner | Package | Baseline findings | Pull request |
| --- | --- | ---: | --- |
| Task 1 / PR-1 | Containers | 5 | [#367](https://github.com/smart-village-solutions/smart-speech-flow/pull/367) |
| Task 2 / PR-2 | Frontend and token checks | 14 | [#368](https://github.com/smart-village-solutions/smart-speech-flow/pull/368) |
| Task 3 / PR-3 | Gateway routes and authentication | 19 | [#369](https://github.com/smart-village-solutions/smart-speech-flow/pull/369) |
| Task 4 / PR-4 | Telemetry, feedback, and pipeline | 27 | [#370](https://github.com/smart-village-solutions/smart-speech-flow/pull/370) |
| Task 5 / PR-5 | Session state | 13 | [#371](https://github.com/smart-village-solutions/smart-speech-flow/pull/371) |
| Task 6 / PR-6 | Realtime transport | 22 | [#372](https://github.com/smart-village-solutions/smart-speech-flow/pull/372) |
| Task 7 / PR-7 | Feedback tests | 28 | [#373](https://github.com/smart-village-solutions/smart-speech-flow/pull/373) |
| Task 8 / PR-8 | Remaining tests | 35 | [#374](https://github.com/smart-village-solutions/smart-speech-flow/pull/374) |
| Total | | 163 | |

All eight PRs remain OPEN and await merge as of 2026-09-20. Their clean PR
analyses do not establish closure of these baseline keys on `main`; integrated
verification remains pending in [tasks.md](tasks.md#9-final-integration-evidence).

## Immutable issue inventory

| Package | File | Rule | Count | Issue keys |
| --- | --- | --- | ---: | --- |
| PR-1 | `services/api_gateway/Dockerfile` | `docker:S8541` | 1 | `AaCq7ussyFXewxHju0eC` |
| PR-1 | `services/asr/Dockerfile` | `docker:S8541` | 1 | `AaCq7uzZyFXewxHju0eE` |
| PR-1 | `services/studio_mock/Dockerfile` | `docker:S8541` | 1 | `AaCq7u2EyFXewxHju0eG` |
| PR-1 | `services/translation/Dockerfile` | `docker:S8541` | 1 | `AaCq7u1myFXewxHju0eF` |
| PR-1 | `services/tts/Dockerfile` | `docker:S8541` | 1 | `AaCq7uyiyFXewxHju0eD` |
| PR-2 | `services/frontend/index.html` | `javascript:S3358` | 1 | `AaCMvl78MEL4mAZEOFMC` |
| PR-2 | `services/frontend/scripts/check-tokens.sh` | `shelldre:S1192` | 3 | `AaCp6Gl29_sydZyaFDBl`, `AaCp6Gl29_sydZyaFDBm`, `AaCp6Gl29_sydZyaFDBn` |
| PR-2 | `services/frontend/src/app/auth/__tests__/keycloak.test.ts` | `typescript:S2094` | 1 | `AaCQMv9GixRLzS7jOm-Z` |
| PR-2 | `services/frontend/src/app/auth/__tests__/keycloak.test.ts` | `typescript:S6635` | 1 | `AaCQMv9GixRLzS7jOm-a` |
| PR-2 | `services/frontend/src/app/auth/keycloak.ts` | `typescript:S6582` | 1 | `AaCQMv9bixRLzS7jOm-b` |
| PR-2 | `services/frontend/src/app/router/AppRoutes.tsx` | `typescript:S6759` | 2 | `AaCQMv8uixRLzS7jOm-X`, `AaCQMv8uixRLzS7jOm-Y` |
| PR-2 | `services/frontend/src/domain/feedback/__tests__/feedback.repository.test.ts` | `typescript:S7718` | 1 | `AaCRdqNxmMv0uEV3r66h` |
| PR-2 | `services/frontend/src/features/admin/AdminLoginScreen.tsx` | `typescript:S8786` | 1 | `AaBHmdCHI4aEr1GesYAQ` |
| PR-2 | `services/frontend/src/features/admin/SessionStatusOverlay.tsx` | `typescript:S6819` | 1 | `AaBHmdDQI4aEr1GesYAR` |
| PR-2 | `services/frontend/src/features/login/TenantLoginScreen.tsx` | `typescript:S6819` | 1 | `AaCQMv5vixRLzS7jOm-W` |
| PR-2 | `services/frontend/src/ui/__tests__/header-stacking.test.ts` | `typescript:S7780` | 1 | `AaBHmdEII4aEr1GesYAS` |
| PR-3 | `services/api_gateway/app.py` | `python:S3776` | 1 | `AaCzmA7OswDuyNWs6iuS` |
| PR-3 | `services/api_gateway/app.py` | `python:S7632` | 3 | `AaCRdqeDmMv0uEV3r66x`, `AaCRdqeDmMv0uEV3r66w`, `AaCRdqeDmMv0uEV3r66y` |
| PR-3 | `services/api_gateway/realtime_ticket.py` | `python:S1172` | 2 | `AaCQUKpivHWOUSvkfAj8`, `AaCQUKpivHWOUSvkfAj9` |
| PR-3 | `services/api_gateway/routes/admin.py` | `python:S1192` | 1 | `AaCQUKkWvHWOUSvkfAjd` |
| PR-3 | `services/api_gateway/routes/admin.py` | `python:S8409` | 1 | `AaCQUKkWvHWOUSvkfAje` |
| PR-3 | `services/api_gateway/routes/customer.py` | `python:S1192` | 1 | `AaCQUKkAvHWOUSvkfAjc` |
| PR-3 | `services/api_gateway/routes/feedback.py` | `python:S8409` | 3 | `AaCRdqZKmMv0uEV3r66j`, `AaCRdqZKmMv0uEV3r66k`, `AaCRdqZKmMv0uEV3r66i` |
| PR-3 | `services/api_gateway/routes/feedback.py` | `python:S8410` | 5 | `AaCRdqZKmMv0uEV3r66m`, `AaCRdqZKmMv0uEV3r66n`, `AaCRdqZKmMv0uEV3r66o`, `AaCRdqZKmMv0uEV3r66p`, `AaCRdqZKmMv0uEV3r66l` |
| PR-3 | `services/api_gateway/routes/login.py` | `python:S8409` | 1 | `AaCQMwC8ixRLzS7jOm-d` |
| PR-3 | `services/api_gateway/studio_login_directory_client.py` | `python:S1186` | 1 | `AaCQMwB9ixRLzS7jOm-c` |
| PR-4 | `services/api_gateway/feedback/crypto.py` | `python:S5713` | 1 | `AaCRdqcImMv0uEV3r66s` |
| PR-4 | `services/api_gateway/feedback/maintenance.py` | `python:S7632` | 2 | `AaCRdqcjmMv0uEV3r66t`, `AaCRdqcjmMv0uEV3r66u` |
| PR-4 | `services/api_gateway/feedback/service.py` | `python:S7632` | 1 | `AaCRdqc9mMv0uEV3r66v` |
| PR-4 | `services/api_gateway/feedback/tenant.py` | `python:S1172` | 2 | `AaCmdWcB9XEHV8Xt_Zg0`, `AaCmdWcB9XEHV8Xt_Zg1` |
| PR-4 | `services/api_gateway/feedback/tenant.py` | `python:S7503` | 1 | `AaCmdWcB9XEHV8Xt_Zg2` |
| PR-4 | `services/api_gateway/message_telemetry.py` | `python:S7519` | 1 | `AaB7JEJxR5VWOR5WA1tq` |
| PR-4 | `services/api_gateway/pipeline_admission.py` | `python:S5709` | 1 | `AaBcFEa3c1Gr0qfc8O26` |
| PR-4 | `services/api_gateway/pipeline_admission.py` | `python:S6796` | 3 | `AaCQUKmhvHWOUSvkfAjo`, `AaBcFEa3c1Gr0qfc8O27`, `AaBcFEa3c1Gr0qfc8O28` |
| PR-4 | `services/api_gateway/quality_telemetry.py` | `python:S107` | 1 | `AaCQUKoGvHWOUSvkfAjw` |
| PR-4 | `services/api_gateway/quality_telemetry.py` | `python:S1192` | 8 | `AaCmi0ZXWCQT0xQX7t9e`, `AaCRdqifmMv0uEV3r660`, `AaCRdqifmMv0uEV3r66z`, `AaCQUKoGvHWOUSvkfAjv`, `AaB7JEM9R5VWOR5WA1tr`, `AaB7JEM9R5VWOR5WA1tu`, `AaB7JEM9R5VWOR5WA1tt`, `AaB7JEM9R5VWOR5WA1ts` |
| PR-4 | `services/api_gateway/quality_telemetry.py` | `python:S5799` | 1 | `AaCRdqifmMv0uEV3r661` |
| PR-4 | `services/api_gateway/quality_telemetry.py` | `python:S5864` | 1 | `AaB7Gd_NjHwcUD3oUcs-` |
| PR-4 | `services/api_gateway/quality_telemetry.py` | `python:S6353` | 1 | `AaB7Gd_NjHwcUD3oUcs9` |
| PR-4 | `services/api_gateway/runtime_policy_metrics.py` | `python:S6796` | 1 | `AaCmmuQ1Cs0sTIMXJ_bn` |
| PR-4 | `services/api_gateway/runtime_policy.py` | `python:S7632` | 1 | `AaCmmuOmCs0sTIMXJ_bm` |
| PR-4 | `services/translation/app.py` | `python:S5709` | 1 | `AaBcFEdFc1Gr0qfc8O2-` |
| PR-5 | `services/api_gateway/session_manager.py` | `python:S1192` | 2 | `AaCQUKldvHWOUSvkfAjg`, `AaCQUKldvHWOUSvkfAjf` |
| PR-5 | `services/api_gateway/session_manager.py` | `python:S3776` | 5 | `AaCzmBAUswDuyNWs6iuT`, `AaCzmBAUswDuyNWs6iuU`, `AaCQUKldvHWOUSvkfAjh`, `AaCQUKldvHWOUSvkfAjj`, `AaCQUKldvHWOUSvkfAji` |
| PR-5 | `services/api_gateway/session_manager.py` | `python:S7504` | 1 | `AaCzmBAUswDuyNWs6iuV` |
| PR-5 | `services/api_gateway/session_store.py` | `python:S1192` | 1 | `AaCQUKoYvHWOUSvkfAjx` |
| PR-5 | `services/api_gateway/session_store.py` | `python:S3776` | 1 | `AaCQUKoYvHWOUSvkfAj0` |
| PR-5 | `services/api_gateway/session_store.py` | `python:S5713` | 3 | `AaCQUKoYvHWOUSvkfAj1`, `AaCQUKoYvHWOUSvkfAjy`, `AaCQUKoYvHWOUSvkfAjz` |
| PR-6 | `services/api_gateway/routes/session.py` | `python:S1172` | 3 | `AaCQUKjlvHWOUSvkfAjW`, `AaCQUKjlvHWOUSvkfAja`, `AaCQUKjlvHWOUSvkfAjb` |
| PR-6 | `services/api_gateway/routes/session.py` | `python:S7503` | 3 | `AaCQUKjlvHWOUSvkfAjZ`, `AaCQUKjlvHWOUSvkfAjX`, `AaCQUKjlvHWOUSvkfAjY` |
| PR-6 | `services/api_gateway/websocket_monitor.py` | `python:S1172` | 4 | `AaCQUKl-vHWOUSvkfAjk`, `AaCQUKl-vHWOUSvkfAjl`, `AaCQUKl-vHWOUSvkfAjm`, `AaCQUKl-vHWOUSvkfAjn` |
| PR-6 | `services/api_gateway/websocket_polling_routes.py` | `python:S1192` | 1 | `AaCQUKncvHWOUSvkfAjp` |
| PR-6 | `services/api_gateway/websocket_polling_routes.py` | `python:S7483` | 2 | `AaCQUKncvHWOUSvkfAjt`, `AaCQUKncvHWOUSvkfAju` |
| PR-6 | `services/api_gateway/websocket_polling_routes.py` | `python:S7503` | 1 | `AaCQUKncvHWOUSvkfAjs` |
| PR-6 | `services/api_gateway/websocket_polling_routes.py` | `python:S8415` | 2 | `AaCQUKncvHWOUSvkfAjq`, `AaCQUKncvHWOUSvkfAjr` |
| PR-6 | `services/api_gateway/websocket.py` | `python:S1172` | 3 | `AaCQUKo3vHWOUSvkfAj3`, `AaCQUKo3vHWOUSvkfAj4`, `AaCQUKo3vHWOUSvkfAj5` |
| PR-6 | `services/api_gateway/websocket.py` | `python:S1192` | 1 | `AaCQUKo3vHWOUSvkfAj2` |
| PR-6 | `services/api_gateway/websocket.py` | `python:S7503` | 2 | `AaCQUKo3vHWOUSvkfAj7`, `AaCQUKo3vHWOUSvkfAj6` |
| PR-7 | `tests/integration/test_feedback_repository.py` | `python:S5778` | 2 | `AaCRdqpzmMv0uEV3r667`, `AaCRdqpzmMv0uEV3r666` |
| PR-7 | `tests/integration/test_feedback_row_level_security.py` | `python:S5778` | 2 | `AaCRdqrsmMv0uEV3r668`, `AaCRdqrsmMv0uEV3r669` |
| PR-7 | `tests/test_feedback_connection_wiring.py` | `python:S8997` | 4 | `AaCRdqo4mMv0uEV3r665`, `AaCRdqo4mMv0uEV3r662`, `AaCRdqo4mMv0uEV3r663`, `AaCRdqo4mMv0uEV3r664` |
| PR-7 | `tests/test_feedback_dsn_credentials.py` | `python:S5778` | 3 | `AaCRdqtmmMv0uEV3r66_`, `AaCRdqtmmMv0uEV3r67A`, `AaCRdqtmmMv0uEV3r67B` |
| PR-7 | `tests/test_feedback_dsn_credentials.py` | `python:S5958` | 1 | `AaCRdqtmmMv0uEV3r66-` |
| PR-7 | `tests/test_feedback_maintenance_alerting.py` | `python:S9073` | 1 | `AaCRdqvwmMv0uEV3r67E` |
| PR-7 | `tests/test_feedback_models.py` | `python:S5778` | 4 | `AaCRdqzGmMv0uEV3r67F`, `AaCRdqzGmMv0uEV3r67G`, `AaCRdqzGmMv0uEV3r67H`, `AaCRdqzGmMv0uEV3r67I` |
| PR-7 | `tests/test_feedback_route.py` | `python:S8997` | 2 | `AaCRdqu1mMv0uEV3r67C`, `AaCRdqu1mMv0uEV3r67D` |
| PR-7 | `tests/test_feedback_service.py` | `python:S5778` | 9 | `AaCmdW109XEHV8Xt_Zg6`, `AaCmdW109XEHV8Xt_Zg3`, `AaCmdW109XEHV8Xt_Zg5`, `AaCmdW109XEHV8Xt_Zg4`, `AaCRdq3FmMv0uEV3r67N`, `AaCRdq3FmMv0uEV3r67J`, `AaCRdq3FmMv0uEV3r67K`, `AaCRdq3FmMv0uEV3r67L`, `AaCRdq3FmMv0uEV3r67M` |
| PR-8 | `services/api_gateway/tests/test_admin.py` | `python:S8997` | 1 | `AZ_oRcAxue9n_h9Ab4uf` |
| PR-8 | `services/api_gateway/tests/test_pipeline.py` | `python:S9073` | 1 | `AZ_oRb-Bue9n_h9Ab4ue` |
| PR-8 | `services/api_gateway/tests/test_tenant_realtime_integration_contract.py` | `python:S8997` | 2 | `AaCp0j8ZjP_kIYV1sNxF`, `AaCp0j8ZjP_kIYV1sNxG` |
| PR-8 | `tests/operations/test_tenant_isolation_smoke.py` | `python:S5778` | 1 | `AaCQUKuqvHWOUSvkfAj_` |
| PR-8 | `tests/test_pipeline_admission.py` | `python:S5778` | 7 | `AaBcFEeyc1Gr0qfc8O3D`, `AaBcFEeyc1Gr0qfc8O3E`, `AaBcFEeyc1Gr0qfc8O3F`, `AaBcFEeyc1Gr0qfc8O2_`, `AaBcFEeyc1Gr0qfc8O3A`, `AaBcFEeyc1Gr0qfc8O3B`, `AaBcFEeyc1Gr0qfc8O3C` |
| PR-8 | `tests/test_quality_telemetry_taxonomy.py` | `python:S5778` | 1 | `AaB7GeCfjHwcUD3oUcs_` |
| PR-8 | `tests/test_service_app_helpers.py` | `python:S9073` | 1 | `AZ_oRcGWue9n_h9Ab4ug` |
| PR-8 | `tests/test_studio_login_directory_client.py` | `python:S5778` | 2 | `AaCQMwNZixRLzS7jOm-g`, `AaCQMwNZixRLzS7jOm-h` |
| PR-8 | `tests/test_studio_login_directory.py` | `python:S5778` | 1 | `AaCQMwJdixRLzS7jOm-f` |
| PR-8 | `tests/test_studio_runtime_flow.py` | `python:S5778` | 5 | `AaCG2GbEeMZvS3_Ezgzi`, `AaCG2GbEeMZvS3_Ezgzj`, `AaCG2GbEeMZvS3_Ezgzk`, `AaCG2GbEeMZvS3_Ezgzl`, `AaCG2GbEeMZvS3_Ezgzm` |
| PR-8 | `tests/test_tenant_session_access.py` | `python:S5778` | 1 | `AaCQUKwGvHWOUSvkfAkA` |
| PR-8 | `tests/test_translation_inference_offload.py` | `python:S5778` | 3 | `AaBcFEgEc1Gr0qfc8O3H`, `AaBcFEgEc1Gr0qfc8O3I`, `AaBcFEgEc1Gr0qfc8O3J` |
| PR-8 | `tests/test_translation_inference_offload.py` | `python:S9073` | 2 | `AaBcFEgEc1Gr0qfc8O3G`, `AaBcFEgEc1Gr0qfc8O3K` |
| PR-8 | `tests/test_translation_message_emission.py` | `python:S5778` | 6 | `AaB7JEPmR5VWOR5WA1tw`, `AaB7JEPmR5VWOR5WA1tx`, `AaB7JEPmR5VWOR5WA1ty`, `AaB7JEPmR5VWOR5WA1tz`, `AaB7JEPmR5VWOR5WA1t0`, `AaB7JEPmR5VWOR5WA1t1` |
| PR-8 | `tests/test_websocket_polling_behavior.py` | `python:S5778` | 1 | `AaCQUKrqvHWOUSvkfAj-` |

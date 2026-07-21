# Implementation Tasks - Eliminate the SonarCloud Backlog

## 0. Coordination and Baseline

- [x] 0.1 Obtain approval for this proposal before implementation starts.
- [x] 0.2 Export the live open-issue list for `main` and confirm the baseline is still 101 issues.
- [x] 0.3 Record every issue key, rule, component, assignee, work package, and target PR in the coordinator ledger.
- [x] 0.4 Create one branch or fork per work package from the same approved baseline.
- [x] 0.5 Confirm file ownership with all agents and reserve shared configuration files for the coordinator.

## 1. WP-E - Test Correctness (Agent E, 8 Findings)

Owned files:

- `tests/test_circuit_breaker_integration.py`
- `tests/test_service_app_helpers.py`
- `tests/test_end_to_end_conversation.py`
- `tests/load/test_production_load.py`

Tasks:

- [x] 1.1 Move assertions outside `try` blocks that catch `AssertionError` in the circuit-breaker integration tests (`python:S5779`, 2 findings).
- [x] 1.2 Replace the broad expected exception with the narrow network exception and guarantee client/server cleanup in `finally` (`python:S5958`, 1 finding).
- [x] 1.3 Restrict each `pytest.raises` block to the single invocation expected to throw (`python:S5778`, 2 findings).
- [x] 1.4 Remove unnecessary exception-catching wrappers so end-to-end parsing failures fail naturally (`python:S8714`, 2 findings).
- [x] 1.5 Convert the load harness into a collectable `@pytest.mark.load` test with meaningful assertions, or move it to `scripts/load` and update documented commands (`python:S2187`, 1 finding).
- [x] 1.6 Replace fixed test ports with dynamically assigned ports where touched and guarantee thread cleanup.
- [x] 1.7 Run the circuit-breaker suite three consecutive times and run all four affected test modules.
- [ ] 1.8 Open a focused PR and confirm the expected Sonar count changes from 101 to 93 after merge.

## 2. WP-C - Frontend Security and Semantics (Agent C, 32 Findings)

Owned scope: `services/frontend`, including package manifests and the dependency lock file, but excluding shared CI workflow files.

Tasks:

- [x] 2.1 Add one central validator for session and polling identifiers used in request paths.
- [x] 2.2 Construct REST URLs with validated and encoded path segments in `SessionService.ts` and `MessageService.ts` (`tssecurity:S7044` and `tssecurity:S8476`, 6 findings).
- [x] 2.3 Validate the WebSocket base URL and allow only `ws` or `wss` before constructing a connection (`tssecurity:S8480`, 1 finding).
- [x] 2.4 Remove or redact user-controlled values from eight logs across services, context, and components (`tssecurity:S5145`, 8 findings).
- [x] 2.5 Replace four existence checks using `.find()` with `.some()` in `SessionContext.tsx` (`typescript:S7754`, 4 findings).
- [x] 2.6 Add an explicit `type` to all 13 reported buttons (`typescript:S9011`, 13 findings).
- [x] 2.7 Add a minimal frontend test harness if none exists, then add tests for valid identifiers, path injection, invalid WebSocket schemes, submit behavior, and message reconciliation.
- [x] 2.8 Run `npm ci`, frontend tests, `npm run lint`, `npm run build`, `npm audit`, and `npm run fallow:audit`.
- [ ] 2.9 Open a focused PR and confirm the expected Sonar count changes from 93 to 61 after merge.

## 3. WP-A - Backend Routes (Agent A, 20 Findings)

Owned files:

- `services/api_gateway/routes/admin.py`
- `services/api_gateway/routes/circuit_breaker.py`
- `services/api_gateway/routes/customer.py`
- `services/api_gateway/routes/session.py`
- `services/api_gateway/app.py`
- route-specific tests that are not owned by WP-E

Tasks:

- [x] 3.1 Replace the 18 reported exception-logging calls with safe `logger.exception()` calls inside active exception handlers (`python:S8572`).
- [x] 3.2 Remove user-controlled values from the reported customer-route log (`pythonsecurity:S5145`, 1 finding).
- [x] 3.3 Define and reuse one health-path constant without changing route behavior (`python:S1192`, 1 finding).
- [x] 3.4 Add log-capture tests proving that tracebacks remain available while session identifiers, language values, and raw exception text are absent.
- [x] 3.5 Run route, admin, customer, session, and application-startup tests plus formatting and linting checks.
- [ ] 3.6 Open a focused PR and confirm the expected Sonar count changes from 61 to 41 after merge.

## 4. WP-B - Backend Core (Agent B, 25 Findings)

Owned files:

- `services/api_gateway/audio_storage.py`
- `services/api_gateway/circuit_breaker.py`
- `services/api_gateway/circuit_breaker_client.py`
- `services/api_gateway/enhanced_audio_validation.py`
- `services/api_gateway/service_health.py`
- `services/api_gateway/websocket.py`
- `services/api_gateway/websocket_fallback.py`
- `services/api_gateway/websocket_monitor.py`
- `services/api_gateway/websocket_polling_routes.py`
- core-specific tests that are not owned by WP-E

Tasks:

- [x] 4.1 Replace the 23 reported exception-logging calls with safe `logger.exception()` calls inside active exception handlers (`python:S8572`).
- [x] 4.2 Remove the user-controlled session value from the reported WebSocket log (`pythonsecurity:S5145`, 1 finding).
- [x] 4.3 Rename the internal long-polling timeout parameter and preserve the public `timeout` query parameter with an explicit alias (`python:S7483`, 1 finding).
- [x] 4.4 Add log-capture tests for sensitive values and regression tests for `?timeout=` and generated OpenAPI metadata.
- [x] 4.5 Run WebSocket, polling, storage, validation, health, monitoring, fallback, and circuit-breaker tests plus formatting and linting checks.
- [ ] 4.6 Open a focused PR and confirm the expected Sonar count changes from 41 to 16 after merge.

## 5. WP-D - Reproducible Containers (Agent D, 16 Findings)

Owned files:

- `services/api_gateway/Dockerfile`
- `services/asr/Dockerfile`
- `services/translation/Dockerfile`
- `services/tts/Dockerfile`
- service-specific Python requirement and lock files
- dedicated dependency-lock generation scripts or documentation

Tasks:

- [x] 5.1 Inventory every runtime dependency source, direct Dockerfile installation, package index, Python version, and CUDA requirement.
- [x] 5.2 Pin pip, torch, torchvision, torchaudio, and every other direct Dockerfile installation to reviewed exact versions.
- [x] 5.3 Generate service-specific exact lock files with hashes or equivalent verifiable artifacts.
- [x] 5.4 Add builder stages that download or build all required wheels in a controlled environment.
- [x] 5.5 Install runtime dependencies with `--no-index` and `--only-binary=:all:` from the controlled wheel directory (`docker:S8541`, 8 findings).
- [x] 5.6 Ensure Dockerfile install commands cannot resolve unlocked dependency versions (`docker:S8544`, 8 findings).
- [x] 5.7 Align CUDA base images, PyTorch wheel indexes, and pinned GPU packages; document the supported matrix.
- [x] 5.8 Run dependency audits against every service lock file.
- [x] 5.9 Build all four images and run Python import, CUDA availability, model dependency, and `/health` smoke checks.
- [ ] 5.10 Open a focused PR and confirm Sonar reports zero open issues after merge.

## 6. Coverage Wave (Starts After Tasks 1-5 Merge)

- [x] 6.1 Refresh coverage and calculate the exact uncovered-line reduction required for 80% after remediation. Current hermetic suite coverage is 76% (4,047/5,336 lines); at least 222 additional currently uncovered lines are required if the denominator remains stable.
- [x] 6.2 Assign one coverage agent to WebSocket, polling, and circuit-breaker behavior.
- [x] 6.3 Assign a second coverage agent to enhanced audio validation, storage, ASR, translation, and TTS behavior.
- [x] 6.4 Cover the required additional lines for the post-remediation denominator using behavioral assertions. Coverage increased from 4,047 to 4,277 covered lines (+230), exceeding the 4,269 lines required for 80%.
- [ ] 6.5 Confirm overall backend line coverage is at least 80% and new-code coverage has not fallen below 84.8%.
- [ ] 6.6 Set the enforced CI coverage floor to 80% only after the suite reaches it.

## 7. Coordinator Integration and Quality Gates

- [ ] 7.1 Rebase each PR on the latest `main` immediately before final validation.
- [ ] 7.2 Verify that each PR closes its assigned issue keys and introduces no new findings.
- [x] 7.3 Run the hermetic backend suite with coverage:

  ```bash
  pytest tests/ -q \
    -m "not integration and not real_system" \
    --ignore=tests/integration \
    --ignore=tests/load \
    --ignore=tests/integration_test_audio_validation.py \
    --cov=services \
    --cov-report=term-missing \
    --cov-report=xml:coverage.xml \
    --cov-fail-under=80
  ```

- [x] 7.4 Run frontend installation, tests, lint, build, audit, and Fallow audit from a clean dependency install.
- [x] 7.5 Build and smoke-test all four production images.
- [ ] 7.6 Run optional integration, real-system, and load suites in their controlled environments and document skips.
- [ ] 7.7 Run a fresh SonarCloud analysis on the final commit and wait for Quality Gate completion.
- [ ] 7.8 Confirm zero open bugs, vulnerabilities, code smells, and unreviewed security hotspots.
- [ ] 7.9 Confirm ratings A/A/A, new coverage at least 84.8%, overall coverage at least 80%, and new duplication at most 3%.
- [ ] 7.10 Record final analysis evidence in this change and mark all tasks complete only after the evidence exists.

## 8. Final Evidence

- [ ] 8.1 Final commit: `TBD`
- [ ] 8.2 Sonar analysis ID and timestamp: `TBD`
- [ ] 8.3 Final issue totals: `TBD`
- [ ] 8.4 Final ratings and Quality Gate: `TBD`
- [ ] 8.5 Backend tests and coverage: `TBD`
- [ ] 8.6 Frontend checks: `TBD`
- [ ] 8.7 Container build and smoke checks: `TBD`
- [ ] 8.8 Approved false-positive decisions, if any: `None expected`

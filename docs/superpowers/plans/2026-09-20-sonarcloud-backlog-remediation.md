# SonarCloud Backlog Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all 163 findings in the immutable 2026-09-18 SonarCloud baseline through eight focused, independently reviewable pull requests.

**Architecture:** Divide work by exclusive file ownership so each PR can branch from `origin/main`, be tested and reviewed independently, and be reverted without affecting another package. Preserve all public contracts; use characterization tests before behavior-sensitive Python refactors and use the existing SonarCloud failure as the red test for analyzer-only configuration findings.

**Tech Stack:** Python 3.12, FastAPI, pytest, TypeScript, React, Vitest, ESLint, Bash, Docker/BuildKit, GitHub Actions, SonarCloud, OpenSpec.

**Spec:** `openspec/changes/fix-sonarcloud-open-issues/design.md`

## Global Constraints

- Baseline revision is `114574a9789256b8bbc06640af962b769285ca70`, analysis ID `e648dbdd-4091-461b-99e9-684d785faf62`, with exactly 163 findings: 5 vulnerabilities and 158 code smells.
- Do not change HTTP paths, query names, response models, WebSocket messages, authentication semantics, persistence keys, or emitted telemetry contracts.
- Do not use `NOSONAR`, exclusions, disabled rules, issue-status changes, or weaker Quality Gate thresholds.
- A file belongs to exactly one task. Stop and report a cross-task file dependency instead of editing outside the task's owned files.
- Production code refactors use red-green-refactor. Analyzer-only Docker/configuration corrections use the already-observed SonarCloud issue as RED and must still pass behavioral build/smoke verification.
- New or changed tests must name the production break they catch, assert real observable behavior, and avoid assertions on mocks.
- Every implementation task ends with targeted verification, a self-review, one or more conventional commits, an independent task review, and a focused PR targeting `main`.
- The coordinator, not the implementer, refreshes branches, pushes, opens PRs, and records SonarCloud PR-analysis evidence.
- Project documentation, commit messages, PR titles, and PR bodies are written in English.

---

### Task 1: Container Supply-Chain Findings

**Files:**
- Modify: `services/studio_mock/Dockerfile`
- Modify: `services/api_gateway/Dockerfile`
- Modify: `services/asr/Dockerfile`
- Modify: `services/translation/Dockerfile`
- Modify: `services/tts/Dockerfile`
- Modify only if required by the chosen wheelhouse implementation: the corresponding service `requirements.txt`
- Test: existing Docker builds and service import/health smoke commands

**Interfaces:**
- Consumes: hash-locked service requirement files and current Python/CUDA base images.
- Produces: five runtime images whose dependency installation never executes an untrusted source distribution setup script.

- [ ] **Step 1: Export and pin the five live findings**

Run:

```bash
curl -fsS 'https://sonarcloud.io/api/issues/search?componentKeys=smart-village-solutions_smart-speech-flow&resolved=false&ps=500' \
  | jq -r '.issues[] | select(.rule == "docker:S8541") | [.key, .component, .line, .message] | @tsv'
```

Expected: exactly five rows for `studio_mock`, `api_gateway`, `asr`, `translation`, and `tts` Dockerfiles.

- [ ] **Step 2: Confirm the analyzer RED state and runtime requirements**

Record the current SonarCloud issue keys in the task report. For each Dockerfile, identify every `pip install` in both builder and runtime stages. The required invariant is:

```text
Every install that resolves or installs an artifact includes --only-binary=:all:,
or installs only from a controlled local wheelhouse with --no-index and
--find-links=/wheels. Source packages may be built only in a builder stage.
```

- [ ] **Step 3: Implement the minimal controlled-wheel correction**

Use the existing API gateway/GPU-service wheelhouse pattern. Add
`--only-binary=:all:` to the hash-pinned pip bootstrap installs. Convert
`studio_mock` to a builder/runtime wheelhouse flow rather than adding an
unverified network install to its runtime stage. Do not change base-image,
dependency, CUDA, UID, command, or health behavior unless a build proves the
existing combination cannot satisfy the invariant.

- [ ] **Step 4: Verify image behavior**

Run syntax/config tests first:

```bash
.venv/bin/pytest tests/test_studio_runtime_configuration_mock_compose.py tests/test_tenant_websocket.py -q
```

Then build each affected image with its existing Compose or direct-build
context. At minimum run:

```bash
docker build -f services/studio_mock/Dockerfile -t ssf-sonar-studio-mock .
docker build -f services/api_gateway/Dockerfile -t ssf-sonar-api-gateway .
docker build -f services/asr/Dockerfile -t ssf-sonar-asr .
docker build -f services/translation/Dockerfile -t ssf-sonar-translation .
docker build -f services/tts/Dockerfile -t ssf-sonar-tts .
```

Run import or health smoke checks documented by each service. Record GPU-only
checks as controlled-environment skips if the host has no compatible GPU.

- [ ] **Step 5: Commit and report**

```bash
git add services/studio_mock/Dockerfile services/api_gateway/Dockerfile services/asr/Dockerfile services/translation/Dockerfile services/tts/Dockerfile
git commit -m "fix(containers): require binary-only dependency installs"
```

The report must list issue keys, changed files, exact build/smoke commands,
results, skips, and remaining risks.

---

### Task 2: Frontend and Token-Check Findings

**Files:**
- Modify: `services/frontend/index.html`
- Modify: `services/frontend/scripts/check-tokens.sh`
- Modify: `services/frontend/src/app/auth/keycloak.ts`
- Modify: `services/frontend/src/app/auth/__tests__/keycloak.test.ts`
- Modify: `services/frontend/src/app/router/AppRoutes.tsx`
- Modify: `services/frontend/src/domain/feedback/__tests__/feedback.repository.test.ts`
- Modify: `services/frontend/src/features/admin/AdminLoginScreen.tsx`
- Modify: `services/frontend/src/features/admin/SessionStatusOverlay.tsx`
- Modify: `services/frontend/src/features/login/TenantLoginScreen.tsx`
- Modify: `services/frontend/src/ui/__tests__/header-stacking.test.ts`

**Interfaces:**
- Consumes: existing React routes, Keycloak initialization, feedback repository, and design tokens.
- Produces: unchanged user flows with safer regular expressions, valid semantics, explicit component props, and clearer tests/scripts.

- [ ] **Step 1: Export the fourteen owned findings**

Filter the live issue response to components beginning with
`services/frontend/`. Assert the count is fourteen and record every key, rule,
file, and line in the report.

- [ ] **Step 2: Add RED behavior tests where behavior can change**

Before changing `AdminLoginScreen.tsx`, add a test proving the username/input
pattern rejects malformed input without catastrophic backtracking on a long
near-match. Before replacing `role="status"`, add or adjust Testing Library
queries to assert the live status is exposed through an actual `<output>`
element. Run the focused Vitest files and record the expected failures.

- [ ] **Step 3: Apply the rule-specific minimal fixes**

Use these exact recipes unless inspection proves a different fix is required:

```text
javascript:S3358   replace the nested conditional with named statements
typescript:S8786   replace the super-linear regex with a linear equivalent
typescript:S6819   render <output> instead of role="status"
typescript:S6759   define and pass the required component props explicitly
typescript:S6582   use optional chaining without changing fallback behavior
typescript:S6635   remove the unnecessary non-null assertion
typescript:S2094   replace an empty test class/object with the simplest real fixture
typescript:S7718   use globalThis instead of window where the test requires the global
typescript:S7780   use String.raw for the escaped regular-expression fixture
shelldre:S1192     define readonly character-class constants once and reuse them
```

- [ ] **Step 4: Verify frontend behavior and quality**

```bash
cd services/frontend
npm ci
npm test
npm run lint
npm run build
bash scripts/check-tokens.sh
```

- [ ] **Step 5: Commit and report**

```bash
git add services/frontend
git commit -m "fix(frontend): resolve current Sonar findings"
```

Report the red/green tests, all verification commands, and the fourteen issue
keys.

---

### Task 3: Gateway Routes and Authentication Findings

**Files:**
- Modify: `services/api_gateway/app.py`
- Modify: `services/api_gateway/realtime_ticket.py`
- Modify: `services/api_gateway/routes/admin.py`
- Modify: `services/api_gateway/routes/customer.py`
- Modify: `services/api_gateway/routes/feedback.py`
- Modify: `services/api_gateway/routes/login.py`
- Modify: `services/api_gateway/studio_login_directory_client.py`
- Test: existing matching modules under `tests/`; create focused tests only in previously unaffected route/authentication test files

**Interfaces:**
- Consumes: current FastAPI dependency providers, response models, login directory protocol, and ticket claims.
- Produces: identical HTTP/OpenAPI/authentication behavior with reduced complexity, constants, complete methods, and modern FastAPI annotations.

- [ ] **Step 1: Export the nineteen owned findings**

Filter the live response to the seven owned production files. Assert the count
is nineteen and record keys, rules, lines, and messages.

- [ ] **Step 2: Establish RED characterization for behavior-sensitive fixes**

For the `app.py` cognitive-complexity finding, identify the named function at
the reported line and add one test for each currently uncovered decision path
that the extraction will move. For `studio_login_directory_client.py`, write a
test that calls the reported empty concrete method and asserts its intended
observable behavior or exception. Run each new test and verify it fails for the
missing contract, not a setup error.

- [ ] **Step 3: Implement minimal route/authentication fixes**

Extract private helpers from the one complex application function without
changing call order or exception mapping. Introduce shared error-message
constants only inside their owning module. Replace redundant FastAPI
`response_model` declarations only when the return annotation is identical;
use `Annotated[T, Depends(provider)]` while preserving dependency providers and
defaults. Remove an unused parameter only after `rg` proves no callback or
protocol requires its signature.

- [ ] **Step 4: Verify routes, OpenAPI, and authentication**

Run the exact affected test modules discovered with:

```bash
rg -l 'routes\.feedback|routes\.admin|routes\.customer|routes\.login|realtime_ticket|studio_login_directory|TestClient' tests services/api_gateway/tests
```

Then run those modules with `.venv/bin/pytest -q`, followed by:

```bash
.venv/bin/black --check services/api_gateway/app.py services/api_gateway/realtime_ticket.py services/api_gateway/routes services/api_gateway/studio_login_directory_client.py
.venv/bin/isort --check-only services/api_gateway/app.py services/api_gateway/realtime_ticket.py services/api_gateway/routes services/api_gateway/studio_login_directory_client.py
.venv/bin/flake8 services/api_gateway/app.py services/api_gateway/realtime_ticket.py services/api_gateway/routes services/api_gateway/studio_login_directory_client.py
```

- [ ] **Step 5: Commit and report**

Commit production and focused characterization tests with a conventional
`fix(gateway): ...` message. Report all nineteen issue keys and red/green
evidence.

---

### Task 4: Telemetry, Feedback, and Pipeline Findings

**Files:**
- Modify: `services/api_gateway/feedback/crypto.py`
- Modify: `services/api_gateway/feedback/maintenance.py`
- Modify: `services/api_gateway/feedback/service.py`
- Modify: `services/api_gateway/feedback/tenant.py`
- Modify: `services/api_gateway/message_telemetry.py`
- Modify: `services/api_gateway/pipeline_admission.py`
- Modify: `services/api_gateway/quality_telemetry.py`
- Modify: `services/api_gateway/runtime_policy.py`
- Modify: `services/api_gateway/runtime_policy_metrics.py`
- Modify: `services/translation/app.py`
- Test: related non-feedback-test-package files, especially `tests/test_pipeline_admission.py`, `tests/test_quality_telemetry_taxonomy.py`, and translation tests, only for production characterization

**Interfaces:**
- Consumes: telemetry attribute taxonomy, feedback service contracts, admission exceptions, runtime-policy metrics, and translation shutdown behavior.
- Produces: unchanged telemetry and feedback contracts with valid exception hierarchies, generic typing, suppression syntax, and constants.

- [ ] **Step 1: Export the twenty-seven owned findings**

Filter by the ten owned files, assert a count of twenty-seven, and record the
issue ledger in the report.

- [ ] **Step 2: Write RED characterization tests**

Add tests proving admission and translation control-flow exceptions are caught
by `except Exception` but still preserve their type/message. Add literal
expectations for emitted quality-telemetry attribute keys and rejection
messages before replacing duplicates with constants. Add a negative test for
the enum-validation branch reported by `python:S5864`. Run each test against
the baseline and record the intended failure where behavior is defective; for
pure refactors, perform the mutation check described by the TDD reference.

- [ ] **Step 3: Implement rule-specific fixes**

```text
python:S5709  derive application exceptions from Exception, not BaseException
python:S1192  define module-private constants and reuse exact existing values
python:S6796  use Python 3.12 generic function syntax instead of standalone TypeVar
python:S7632  correct suppression syntax narrowly; do not broaden suppression
python:S5713  remove redundant exception subclasses from except tuples
python:S7503  remove async only if no caller awaits a protocol-required coroutine
python:S107   replace the long parameter list with an existing typed value object, or a new private frozen dataclass
python:S5799  replace the incompatible comparison without weakening validation
python:S5864  iterate the enum through the supported enum interface
python:S6353  use the concise digit class while preserving anchoring
python:S7519  use an explicit iterable/mapping operation instead of the reported ambiguous access
```

- [ ] **Step 4: Verify domain behavior**

Run all tests discovered with:

```bash
rg -l 'feedback|quality_telemetry|message_telemetry|pipeline_admission|runtime_policy|translation' tests services/api_gateway/tests
```

Use `.venv/bin/pytest -q` on the discovered modules, then run Black, isort,
Flake8, and strict MyPy for the ten production files.

- [ ] **Step 5: Commit and report**

Use one or more coherent conventional commits if the exception hierarchy and
telemetry refactors are independently reviewable. Report twenty-seven issue
keys, red/green evidence, and commands.

---

### Task 5: Session State Findings

**Files:**
- Modify: `services/api_gateway/session_manager.py`
- Modify: `services/api_gateway/session_store.py`
- Test: existing session manager/store/persistence/lifecycle tests; add focused tests in an unaffected matching test module

**Interfaces:**
- Consumes: session persistence records, active-session index, lifecycle transitions, tenant isolation, and current exception messages.
- Produces: identical session state transitions and storage invariants with seven simplified functions and shared constants.

- [ ] **Step 1: Export the thirteen owned findings**

Filter the live issue response to the two owned files, assert thirteen rows,
and record each function named by the seven `python:S3776` messages.

- [ ] **Step 2: Write RED characterization tests for each extracted decision**

For each complex function, map every conditional exit and side effect. Add a
focused test only for branches not already protected. The test name must state
the broken transition or storage invariant it catches. Run new tests after
temporarily applying the intended mutation or against the defective branch and
record the expected RED result.

- [ ] **Step 3: Refactor without changing state order**

Extract private helpers around validation, lookup, mutation, and persistence;
do not reorder writes, index updates, cleanup, or raised exceptions. Replace
duplicated messages with module-private constants containing byte-for-byte
identical strings. Remove redundant exception tuple members and the reported
unnecessary `list()` materialization only when iteration semantics remain the
same.

- [ ] **Step 4: Verify session behavior**

```bash
rg -l 'session_manager|session_store|tenant_session|session lifecycle|active session' tests services/api_gateway/tests
```

Run the discovered tests with `.venv/bin/pytest -q`, then Black, isort,
Flake8, and strict MyPy for both production files.

- [ ] **Step 5: Commit and report**

Commit with a conventional `refactor(gateway): ...` message. Report thirteen
issue keys and branch-by-branch characterization evidence.

---

### Task 6: Realtime Transport Findings

**Files:**
- Modify: `services/api_gateway/routes/session.py`
- Modify: `services/api_gateway/websocket.py`
- Modify: `services/api_gateway/websocket_monitor.py`
- Modify: `services/api_gateway/websocket_polling_routes.py`
- Test: existing WebSocket, polling, session-route, OpenAPI, and tenant-isolation tests; add focused tests only in unaffected matching modules

**Interfaces:**
- Consumes: public `timeout` query parameter, WebSocket message protocol, connection-monitor callbacks, and session route signatures.
- Produces: unchanged realtime contracts with unused parameters removed only where safe, correct FastAPI query annotations, constants, and valid async boundaries.

- [ ] **Step 1: Export the twenty-two owned findings**

Filter the live issue response to the four owned files, assert twenty-two rows,
and record keys, rules, functions, and public/private status.

- [ ] **Step 2: Add RED contract tests**

Before changing polling annotations, assert through generated OpenAPI and a
real request that the external query parameter remains exactly `timeout` with
the existing default and bounds. Before changing callback parameters or
`async`, add tests for real caller behavior and awaitability. Add tests for any
uncovered WebSocket/session error branch touched by a constant extraction.

- [ ] **Step 3: Apply minimal transport fixes**

Use `Annotated[..., Query(alias="timeout", ...)]` where internal naming must
change, preserve WebSocket payloads and close codes, and remove `async` only
when all real callers are synchronous. For unused callback parameters required
by a protocol, rename to an underscore-prefixed name instead of changing the
callable signature. Replace duplicated messages with module-private constants.

- [ ] **Step 4: Verify realtime contracts**

```bash
rg -l 'websocket|polling|routes\.session|OpenAPI|openapi' tests services/api_gateway/tests
```

Run all discovered modules with `.venv/bin/pytest -q`, then Black, isort,
Flake8, and strict MyPy for the four production files.

- [ ] **Step 5: Commit and report**

Commit with a conventional `fix(gateway): ...` or `refactor(gateway): ...`
message. Report twenty-two issue keys and public-contract evidence.

---

### Task 7: Feedback Test-Quality Findings

**Files:**
- Modify: `tests/integration/test_feedback_repository.py`
- Modify: `tests/integration/test_feedback_row_level_security.py`
- Modify: `tests/test_feedback_connection_wiring.py`
- Modify: `tests/test_feedback_dsn_credentials.py`
- Modify: `tests/test_feedback_maintenance_alerting.py`
- Modify: `tests/test_feedback_models.py`
- Modify: `tests/test_feedback_route.py`
- Modify: `tests/test_feedback_service.py`

**Interfaces:**
- Consumes: existing feedback public behavior and pytest fixtures.
- Produces: the same twenty-eight test contracts with one throwing invocation per `pytest.raises`, fixture-managed global state, specific exception checks, and separate assertions.

- [ ] **Step 1: Export the twenty-eight owned findings**

Filter to the eight owned files, assert twenty-eight rows, and record each key,
rule, test name, and line.

- [ ] **Step 2: Prove every test still catches a production break**

Before editing each test, name the concrete production mutation it catches in
the report. If no realistic mutation fails the test, rewrite the test around
the observable feedback behavior before applying the Sonar correction.

- [ ] **Step 3: Apply exact test corrections**

For `python:S5778`, compute fixtures, arguments, and expected values before the
`pytest.raises` block so the block contains only the single invocation expected
to throw. For `python:S8997`, request `monkeypatch` and use `setattr`, `setenv`,
or `delenv` so restoration is automatic. For `python:S5958`, assert the narrow
exception type and relevant message. For `python:S9073`, split the composite
condition into individually named assertions without removing a condition.

- [ ] **Step 4: Verify modified tests**

Run all eight modules together. Run integration-marked modules with their
documented prerequisites when available; otherwise record the exact missing
service as a controlled-environment skip. Run Black, isort, and Flake8 on all
eight files.

- [ ] **Step 5: Commit and report**

```bash
git add tests/integration/test_feedback_repository.py tests/integration/test_feedback_row_level_security.py tests/test_feedback_*.py
git commit -m "test(feedback): tighten exception and fixture assertions"
```

Report the twenty-eight keys, mutation mapping, test results, and skips.

---

### Task 8: Remaining Test-Quality Findings

**Files:**
- Modify: `services/api_gateway/tests/test_admin.py`
- Modify: `services/api_gateway/tests/test_pipeline.py`
- Modify: `services/api_gateway/tests/test_tenant_realtime_integration_contract.py`
- Modify: `tests/operations/test_tenant_isolation_smoke.py`
- Modify: `tests/test_pipeline_admission.py`
- Modify: `tests/test_quality_telemetry_taxonomy.py`
- Modify: `tests/test_service_app_helpers.py`
- Modify: `tests/test_studio_login_directory.py`
- Modify: `tests/test_studio_login_directory_client.py`
- Modify: `tests/test_studio_runtime_flow.py`
- Modify: `tests/test_tenant_session_access.py`
- Modify: `tests/test_translation_inference_offload.py`
- Modify: `tests/test_translation_message_emission.py`
- Modify: `tests/test_websocket_polling_behavior.py`

**Interfaces:**
- Consumes: current pipeline, telemetry, Studio, translation, tenant, and polling behavior.
- Produces: the same thirty-five test contracts using strict exception scopes, fixture-managed state, and separate assertions.

- [ ] **Step 1: Export the thirty-five owned findings**

Filter to the fourteen owned files, assert thirty-five rows, and record every
key, rule, test name, and line.

- [ ] **Step 2: Map tests to real production mutations**

For each affected test, record the production branch, exception, state change,
or emitted message that would make it fail. Replace any tautological or
mock-only assertion with an assertion on the real returned value, state, or
boundary output.

- [ ] **Step 3: Apply rule-specific test corrections**

Use the same strict recipes as Task 7: one throwing call per `pytest.raises`,
`monkeypatch` for temporary global/environment state, one condition per
assertion, and no removal of coverage or assertions. Preserve async markers and
integration markers.

- [ ] **Step 4: Verify modified and related tests**

Run all fourteen modified modules together with `.venv/bin/pytest -q`. Run
Black, isort, and Flake8 on the exact file list. Finally run the hermetic suite:

```bash
PYTHONPATH=. SSF_AUDIO_BASE_DIR=/tmp/ssf-sonar-final-audio .venv/bin/pytest tests/ -q \
  -m 'not integration and not real_system' \
  --ignore=tests/integration \
  --ignore=tests/load \
  --ignore=tests/integration_test_audio_validation.py
```

- [ ] **Step 5: Commit and report**

Commit with `test: tighten remaining Sonar-flagged assertions`. Report all
thirty-five issue keys, mutation mapping, and verification evidence.

---

## Coordinator Completion

After every task review is clean:

1. Refresh that task branch from `origin/main` without rewriting shared history.
2. Re-run its verification commands.
3. Push its dedicated branch and open an English PR against `main` using the repository template.
4. Wait for GitHub checks and SonarCloud PR analysis; fix new findings through the task's review loop.
5. Record the PR URL and checks in `openspec/changes/fix-sonarcloud-open-issues/tasks.md`.
6. After all eight PRs merge, run the full final verification from the OpenSpec design and record the final SonarCloud analysis evidence.

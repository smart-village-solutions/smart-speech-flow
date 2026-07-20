## ADDED Requirements

### Requirement: Complete SonarCloud Backlog Remediation
The repository SHALL resolve every open issue from the approved SonarCloud baseline and SHALL introduce no new open issue before the change is completed.

#### Scenario: Parallel work uses an accountable issue ledger
- **WHEN** remediation work is assigned to agents
- **THEN** every baseline issue is assigned to exactly one work package and one owner
- **AND** each work package has a disjoint file scope
- **AND** every pull request reports the issue keys it closes and the validation it performed

#### Scenario: Final analysis is clean
- **WHEN** all remediation work is merged
- **THEN** a fresh SonarCloud analysis reports zero open bugs, vulnerabilities, and code smells
- **AND** the Quality Gate reports `OK`
- **AND** security, reliability, and maintainability ratings are A

#### Scenario: A suspected false positive is reviewed
- **WHEN** an agent believes a finding cannot be fixed without harming intended behavior
- **THEN** the agent provides reproducible evidence to the coordinator
- **AND** the finding is not suppressed in source code or scanner configuration
- **AND** any SonarCloud false-positive resolution is documented with owner approval

### Requirement: User-Controlled Data Safety
The repository SHALL validate user-controlled connection and path values before use and SHALL prevent user-controlled values from being emitted in operational logs.

#### Scenario: Frontend request paths are constructed
- **WHEN** a session or polling identifier is used in an HTTP request path
- **THEN** the identifier is validated against the backend contract
- **AND** the validated path segment is encoded before URL construction

#### Scenario: A WebSocket connection is constructed
- **WHEN** the frontend constructs a WebSocket URL
- **THEN** the configured base URL is parsed and validated
- **AND** only `ws` and `wss` protocols are accepted
- **AND** invalid user-controlled connection parameters fail before a connection attempt

#### Scenario: An exception or user event is logged
- **WHEN** backend or frontend code records an operational event
- **THEN** raw session identifiers, message content, language values, URLs, and exception text controlled by a user are absent
- **AND** the log retains only safe state, counts, or generated correlation metadata needed for diagnosis

### Requirement: Reproducible Runtime Dependencies
Every Python production image SHALL install exact reviewed dependency versions without executing third-party source build scripts in the runtime stage.

#### Scenario: Runtime dependencies are installed
- **WHEN** a production image installs Python dependencies
- **THEN** every resolved version is exact and verifiable from a service-specific lock artifact
- **AND** runtime installation uses only controlled binary wheels
- **AND** dependency resolution and source builds, when unavoidable, occur in a separate builder stage

#### Scenario: GPU images are validated
- **WHEN** ASR, translation, or TTS images are built
- **THEN** CUDA, PyTorch, torchvision, and torchaudio versions follow a documented compatible matrix
- **AND** Python imports and required GPU capability checks pass before merge

### Requirement: Trustworthy Quality Tests
Tests used as quality evidence SHALL fail when asserted behavior is wrong and SHALL be classified according to how they execute.

#### Scenario: A test expects an exception
- **WHEN** a test verifies that an invocation raises an exception
- **THEN** only the expected invocation is inside the exception assertion context
- **AND** subsequent assertions cannot be swallowed by a broad exception handler

#### Scenario: A load test is retained under the test tree
- **WHEN** a load-test module remains under `tests`
- **THEN** it exposes at least one collectable test marked `load`
- **AND** the test asserts meaningful load-test outcomes
- **AND** normal hermetic CI may deselect it through the marker

### Requirement: Enforced Coverage and Regression Gates
The repository SHALL enforce measurable regression gates after the backlog is eliminated.

#### Scenario: Backend coverage is reported
- **WHEN** the hermetic backend suite runs in CI
- **THEN** overall backend line coverage is at least 80 percent
- **AND** an XML coverage report is supplied to SonarCloud
- **AND** new-code coverage is at least 84.8 percent for this change

#### Scenario: A remediation pull request is evaluated
- **WHEN** a remediation pull request is ready to merge
- **THEN** its targeted tests pass
- **AND** the relevant backend, frontend, or container quality checks pass
- **AND** SonarCloud reports no newly introduced issue

#### Scenario: Final integration is evaluated
- **WHEN** all work packages are integrated
- **THEN** backend tests and frontend checks pass from clean dependency installations
- **AND** all four production images build and pass required smoke checks
- **AND** new-code duplication is at most 3 percent
- **AND** all security hotspots are reviewed

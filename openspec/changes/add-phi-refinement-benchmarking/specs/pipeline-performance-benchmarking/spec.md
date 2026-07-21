# Pipeline Performance Benchmarking Specification

## ADDED Requirements

### Requirement: Multi-Model Refinement Evaluation Contract
The system SHALL support a configuration contract for evaluating more than one Ollama-backed refinement model without requiring an immediate production cutover.

#### Scenario: Shadow comparison preserves the current output path
- **GIVEN** the refinement mode is `shadow_compare`
- **AND** the primary refinement model is `gpt-oss:20b`
- **AND** the candidate refinement model is `phi4-mini`
- **WHEN** the gateway executes a refinement step
- **THEN** the product response SHALL continue to use the primary model output for downstream processing
- **AND** the candidate model SHALL be executed only for comparison and telemetry
- **AND** the candidate result SHALL NOT replace the primary output in this phase

#### Scenario: Future candidate model can be swapped without redesign
- **GIVEN** a future refinement candidate such as `qwen3:4b`
- **WHEN** operators update only the configured candidate model name
- **THEN** the evaluation contract SHALL remain valid without introducing a second refinement architecture

#### Scenario: Qwen is evaluated as an additional non-production candidate
- **GIVEN** operators configure `qwen3:4b` as the candidate model
- **WHEN** they run a controlled `candidate_only` benchmark
- **THEN** its measurements SHALL be reported separately from `phi4-mini`
- **AND** the system SHALL NOT change the production default from that result alone

### Requirement: Supported Refinement Modes
The refinement configuration SHALL define explicit operating modes for disabled, single-model, and comparison use cases.

#### Scenario: Disabled mode skips refinement entirely
- **GIVEN** refinement mode is `disabled`
- **WHEN** a text or audio pipeline runs
- **THEN** no refinement request SHALL be sent
- **AND** downstream timing and output behavior SHALL reflect the absence of the refinement step

#### Scenario: Primary-only mode uses a single production model
- **GIVEN** refinement mode is `primary_only`
- **WHEN** refinement is enabled for a request
- **THEN** only the configured primary model SHALL be used

#### Scenario: Candidate-only mode isolates the candidate model
- **GIVEN** refinement mode is `candidate_only`
- **WHEN** refinement is enabled for a request
- **THEN** only the configured candidate model SHALL be used

#### Scenario: Shadow-compare mode evaluates two models
- **GIVEN** refinement mode is `shadow_compare`
- **WHEN** refinement is enabled for a request
- **THEN** the system SHALL record timings and status for both primary and candidate models
- **AND** the candidate execution SHALL be asynchronous and bounded
- **AND** a saturated candidate queue SHALL record `skipped_overload` without delaying the product response

### Requirement: Refinement Latency Defaults
The first implementation round SHALL target lower-latency refinement behavior than the current `8.0s` timeout and `2` retries.

#### Scenario: First-round timeout default is reduced
- **GIVEN** the first implementation round described by this change
- **WHEN** the refinement timeout default is configured
- **THEN** the default SHALL be `4.0s`
- **AND** the allowed tuning window SHALL be limited to `3.0s` through `5.0s`
- **AND** values below `3.0s` SHALL be out of scope for v1

#### Scenario: Retry count is reduced
- **GIVEN** the first implementation round described by this change
- **WHEN** the refinement retry policy is configured
- **THEN** `LLM_REFINEMENT_MAX_RETRIES` SHALL default to `1`
- **AND** the same retry policy SHALL apply to both primary and candidate refinement requests

#### Scenario: Candidate timeout does not block adoption decisions unfairly
- **GIVEN** the candidate refinement request exceeds its timeout or returns an error during shadow comparison
- **WHEN** the primary refinement request succeeds
- **THEN** the product response SHALL continue with the primary result
- **AND** the candidate timeout or error SHALL be captured as benchmark and telemetry data

### Requirement: Additive Pipeline Performance Telemetry
The runtime timing contract SHALL support sustainable performance analysis of both intermediate steps and total pipeline duration.

#### Scenario: Existing pipeline timings remain canonical
- **GIVEN** the gateway already emits `pipeline_metadata` with per-step timings and total duration
- **WHEN** performance telemetry is extended
- **THEN** the extension SHALL build on the existing timing contract
- **AND** it SHALL NOT replace it with a separate timing system for the same request path

#### Scenario: Refinement comparison details are captured additively
- **GIVEN** refinement executes in a pipeline
- **WHEN** the request completes
- **THEN** the performance contract SHALL include additive refinement comparison fields for:
- **AND** primary model name
- **AND** candidate model name
- **AND** primary duration
- **AND** candidate duration
- **AND** primary and candidate status, including timeout or error information

#### Scenario: Prometheus labels remain low-cardinality
- **GIVEN** pipeline performance metrics are exported to Prometheus
- **WHEN** labels are chosen for timing and error metrics
- **THEN** labels SHALL be restricted to stable low-cardinality fields such as `pipeline_type`, `step`, and approved refinement model names
- **AND** free-form inputs such as session identifiers, user text, or request-specific values SHALL NOT be used as metric labels

### Requirement: Reproducible Benchmark Workflow
The system SHALL define a repeatable benchmark workflow that can be reused for future optimization work across refinement and the broader speech pipeline.

#### Scenario: Benchmark covers both isolated and end-to-end views
- **GIVEN** the team wants before/after comparisons for refinement and broader pipeline changes
- **WHEN** the benchmark workflow is defined
- **THEN** it SHALL include microbenchmarks for individual steps
- **AND** it SHALL include end-to-end benchmark runs for the text pipeline
- **AND** it SHALL include end-to-end benchmark runs for the audio pipeline

#### Scenario: Benchmark uses a fixed goldenset
- **GIVEN** benchmark runs need to be comparable over time
- **WHEN** the benchmark input set is defined
- **THEN** it SHALL use a fixed goldenset rather than ad-hoc requests
- **AND** the goldenset SHALL include representative core language pairs
- **AND** it SHALL include short, medium, and longer samples
- **AND** it SHALL include some cases where refinement can plausibly improve the raw translation
- **AND** it SHALL include audio inputs for full pipeline measurement

#### Scenario: Audio goldenset is privacy-safe and documented
- **GIVEN** the supplied `tests/fixtures/audio/translation/duration_set` fixture set
- **WHEN** the audio benchmark manifest is built
- **THEN** it SHALL use the 30 synthetic WAV inputs and their canonical transcripts from `transcripts.json`
- **AND** it SHALL record a checksum and source/target language for every selected input

#### Scenario: Benchmark output is structured for comparison
- **GIVEN** a benchmark run completes
- **WHEN** results are stored
- **THEN** the output SHALL be machine-readable JSON or CSV
- **AND** it SHALL include at least count, mean, median, p95, min, max, timeout rate, and error rate

### Requirement: Before-and-After Comparison Protocol
The initial evaluation of `phi4-mini` SHALL use a formally defined baseline and comparison workflow.

#### Scenario: Baseline run captures the current state
- **GIVEN** the repository is still using `gpt-oss:20b` as the current refinement model
- **WHEN** the first benchmark round is executed
- **THEN** the team SHALL run the fixed goldenset against the current configuration
- **AND** the benchmark output SHALL preserve the baseline measurements for refinement, text-pipeline total, and audio-pipeline total

#### Scenario: Candidate run compares Phi against the baseline
- **GIVEN** `phi4-mini` is configured as the shadow comparison candidate
- **WHEN** the second benchmark round is executed
- **THEN** the same goldenset SHALL be re-run
- **AND** the comparison output SHALL show absolute and percentage deltas for:
- **AND** refinement timing
- **AND** text-pipeline total duration
- **AND** audio-pipeline total duration
- **AND** end-to-end baselines SHALL use separate `primary_only` and `candidate_only` runs rather than shadow-mode timings

#### Scenario: Acceptance criteria gate the Phi rollout
- **GIVEN** the candidate benchmark run has completed
- **WHEN** the team evaluates whether `phi4-mini` should become the refinement default
- **THEN** the candidate median refinement latency SHALL be at least 30 percent lower and p95 latency at least 20 percent lower than the baseline
- **AND** its timeout rate and error rate SHALL each be no more than one percentage point above baseline
- **AND** a blind paired review by two language-qualified reviewers over at least 30 representative cases SHALL find no critical meaning regression and rate the candidate at least equivalent in at least 90 percent of cases
- **AND** any later switch away from `phi4-mini` SHALL require an approved change

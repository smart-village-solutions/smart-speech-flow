## 1. Refinement Configuration

- [ ] 1.1 Implement the supported refinement modes and the phase-1 `gpt-oss:20b` / `phi4-mini` shadow strategy
- [ ] 1.2 Add bounded asynchronous candidate execution so shadow mode cannot block product responses
- [ ] 1.3 Apply the first-round timeout and retry defaults, including configuration validation

## 2. Performance Contract

- [ ] 2.1 Define additive runtime telemetry for per-step and total pipeline timing
- [ ] 2.2 Define additive refinement-specific timing and status fields for primary/candidate comparison
- [ ] 2.3 Define Prometheus metric expectations with low-cardinality labels

## 3. Benchmark Workflow

- [ ] 3.1 Define the fixed goldenset benchmark approach for text and audio paths
- [ ] 3.2 Define benchmark outputs and comparison report format
- [ ] 3.3 Define the required baseline and post-change comparison runs

## 4. Acceptance Policy

- [ ] 4.1 Define latency, timeout, and error-rate acceptance criteria for `phi4-mini`
- [ ] 4.2 Define the minimum human quality spot-check expectations
- [ ] 4.3 Configure `phi4-mini` as the initial production refinement default; defer any future model switch to a later approved change

## 5. Documentation and Verification

- [ ] 5.1 Document the benchmark commands, input provenance, and acceptance criteria
- [ ] 5.2 Validate the OpenSpec change with `openspec validate add-phi-refinement-benchmarking --strict`
- [ ] 5.3 Run the hermetic unit and benchmark-manifest tests

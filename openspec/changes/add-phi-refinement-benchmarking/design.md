## Context

The API gateway currently performs optional translation refinement synchronously through Ollama. The refinement step already contributes timing information to `pipeline_metadata`, and the overall pipeline also reports total duration. However, the current system is optimized for runtime diagnostics rather than controlled before/after experimentation.

The repository needs two things at the same time:

1. A safe contract for evaluating a smaller commercial-friendly open-source refinement model (`phi4-mini`) beside `gpt-oss:20b`
2. A durable measurement strategy that can be reused for later optimizations in refinement, translation, TTS, ASR, and other pipeline parameters

## Goals / Non-Goals

- Goals:
  - Define a multi-model refinement contract without changing the serving architecture
  - Keep the first rollout non-destructive by evaluating `phi4-mini` in shadow mode
  - Standardize step-level and end-to-end performance reporting
  - Define a repeatable benchmark workflow using a fixed goldenset
  - Capture timeout and retry changes as part of the first optimization round
- Non-Goals:
  - Implement the model switch in this phase
  - Introduce a second inference backend outside Ollama
  - Build a broad automatic quality-judging framework in v1

## Decisions

- Decision: Use Ollama for both current and candidate refinement models
  - Why: the current code already integrates with Ollama, so the first comparison should minimize architectural change
  - Alternatives considered: direct model hosting, vLLM, or a separate refinement service; rejected for the first phase because they confound model comparison with infrastructure changes

- Decision: Compare models via `shadow_compare`
  - Why: the candidate model can be timed and inspected without changing the current output path
  - Alternatives considered: direct cutover to `phi4-mini`; rejected because the team explicitly wants a before/after comparison first

- Decision: Treat existing `pipeline_metadata` timings as the canonical runtime timing contract
  - Why: the system already emits per-step timing, so the benchmark and telemetry design should extend rather than duplicate it
  - Alternatives considered: a separate benchmark-only timing system; rejected because it would drift from runtime behavior

- Decision: Lower the first-round refinement defaults to `timeout=4.0s` and `max_retries=1`
  - Why: the current `8.0s` and `2` retries are too expensive for synchronous refinement, and the new candidate comparison should reflect realistic latency goals
  - Alternatives considered: keeping `8.0s` for parity; rejected because it defeats the stated optimization goal

- Decision: Use a fixed goldenset with both microbenchmarks and end-to-end runs
  - Why: future optimization work needs repeatable measurements across single steps and whole pipelines
  - Alternatives considered: ad-hoc manual checks or load tests only; rejected because they are not stable enough for objective before/after comparison

- Decision: Execute shadow candidates asynchronously through a bounded background queue
  - Why: a candidate timeout must never increase product response latency. When capacity is exhausted the candidate run is skipped and recorded as `skipped_overload`.
  - Alternatives considered: waiting for both models in the request path; rejected because it defeats the latency objective and can amplify GPU contention.

- Decision: Benchmark end-to-end configurations separately
  - Why: `primary_only` and `candidate_only` runs provide comparable end-to-end measurements. Shadow mode is reserved for non-blocking production-safe telemetry because its extra GPU work would confound latency measurements.

- Decision: Adopt the supplied synthetic duration-set as audio goldenset v1
  - Why: it contains 30 documented, privacy-safe WAV inputs in ten supported source languages, each with short, medium, and long samples.

## Risks / Trade-offs

- Shadow comparison may still create extra compute load during the benchmark phase
  - Mitigation: the first implementation should make shadow mode explicit and limited to controlled runs or explicitly enabled environments

- Smaller models may reduce latency but also alter refinement quality
  - Mitigation: acceptance criteria require both latency comparison and human spot-checks for meaning preservation

- Additional telemetry can increase metric cardinality if labels are not tightly scoped
  - Mitigation: restrict labels to `pipeline_type`, `step`, and the small set of approved refinement model names

- Background candidate jobs can accumulate under load
  - Mitigation: use a bounded queue and count skipped jobs; never retain input text in metrics or queue diagnostics.

## Migration Plan

1. Create and validate the OpenSpec change
2. Review and approve the specification
3. Implement the multi-model refinement contract and benchmark tooling
4. Run baseline measurements on `gpt-oss:20b`
5. Run shadow comparison with `phi4-mini`
6. Decide separately whether to switch the production default

## Open Questions

- None for this spec phase; the benchmark shape, rollout mode, and timeout/retry defaults are fixed for the proposed change.

## Follow-up Evaluation

`qwen3:4b` MAY be measured as an additional candidate using the same controlled,
separate `candidate_only` workflow. Its result is exploratory only and MUST NOT
change the production default without a later approved change.

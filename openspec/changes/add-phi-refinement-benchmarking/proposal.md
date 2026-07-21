# Change: Add Phi Refinement Benchmarking and Multi-Model Evaluation

## Why

The current optional translation refinement uses `gpt-oss:20b` through Ollama. It improves output quality in some cases, but it is expensive in latency and blocks the request path synchronously. The project now needs a commercially usable open-source alternative that can be evaluated safely without immediately replacing the current model in production behavior.

At the same time, the repository already exposes per-step timing in `pipeline_metadata`, but it does not yet provide a durable benchmark workflow for before/after performance comparisons across refinement, intermediate steps, and end-to-end pipeline runs. Without a repeatable benchmark contract, future optimizations to refinement, translation, TTS, or other pipeline parameters will be hard to compare objectively.

## What Changes

- Define a multi-model refinement configuration contract for Ollama-backed evaluation
- Prepare `phi4-mini` as a candidate refinement model beside `gpt-oss:20b`
- Define the supported refinement operating modes:
  - `disabled`
  - `primary_only`
  - `candidate_only`
  - `shadow_compare`
- Define the phase-1 evaluation strategy:
  - `primary = gpt-oss:20b`
  - `candidate = phi4-mini`
  - `mode = shadow_compare`
- Define lower-latency refinement defaults for the first implementation round:
  - `LLM_REFINEMENT_TIMEOUT=4.0s` by default, with an allowed tuning window of `3.0s` to `5.0s`
  - `LLM_REFINEMENT_MAX_RETRIES=1`
- Extend the performance contract so that both pipeline step timings and total pipeline timings can be compared before and after optimization work
- Define a durable benchmark workflow based on a fixed goldenset for:
  - isolated refinement measurements
  - full text-pipeline measurements
  - full audio-pipeline measurements
- Define the comparison and acceptance criteria for the initial `gpt-oss:20b` vs `phi4-mini` evaluation

## Impact

- Affected specs: `pipeline-performance-benchmarking`
- Affected code:
  - `services/api_gateway/translation_refiner.py`
  - `services/api_gateway/pipeline_logic.py`
  - future benchmark tooling under `tests/` or dedicated benchmark scripts
  - monitoring and documentation updates

## Non-Goals

- Replacing the Ollama serving architecture
- Replacing Ollama with a different model-serving architecture in this phase
- Pulling or running new models as part of the specification-only step
- Implementing benchmark tooling or telemetry changes in this step
- Promoting `qwen3:4b` to a production default in this change

## Decision Summary

This change defines a specification-first path for evaluating `phi4-mini` as a lower-latency refinement candidate while preserving the current production behavior. The first implementation round should compare `gpt-oss:20b` and `phi4-mini` using a shadow-mode refinement contract and a fixed goldenset benchmark, with explicit per-step and end-to-end performance reporting. After the OpenSpec change is created and validated, work stops pending review and approval.

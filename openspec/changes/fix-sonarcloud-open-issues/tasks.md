# Implementation Tasks - Fix SonarCloud Open Issues

## 1. Security and Blockers

- [x] 1.1 Fix unsafe HTML reflection and logging in upload and API gateway routes
- [x] 1.2 Replace insecure temporary file handling in enhanced audio validation
- [x] 1.3 Convert FastAPI dependencies to `Annotated[...]` in affected routers
- [x] 1.4 Document raised `HTTPException` responses in affected endpoints
- [x] 1.5 Restrict direct local startup binding to loopback without changing container behavior

## 2. Reliability and Runtime

- [x] 2.1 Rework cancelled-task cleanup so `CancelledError` is not swallowed incorrectly
- [x] 2.2 Fix async/sync file API mismatches in ASR and TTS
- [x] 2.3 Replace naive UTC usage with timezone-aware UTC values
- [x] 2.4 Remove async functions that do not use asynchronous features or make them truly async

## 3. Maintainability

- [x] 3.1 Reduce complexity in API gateway hotspot functions
- [x] 3.2 Reduce complexity in translation and TTS hotspot functions
- [x] 3.3 Remove duplicated literals, unused values, and small rule violations in touched modules

## 4. Frontend and Docker

- [x] 4.1 Fix TypeScript Sonar issues in `services/frontend/src`
- [x] 4.2 Fix Dockerfile ordering and package-cache findings

## 5. Validation

- [x] 5.1 Run backend quality checks
- [x] 5.2 Run frontend lint/build checks
- [ ] 5.3 Re-run SonarCloud analysis and confirm zero open issues

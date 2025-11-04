# Fix Linting Issues - Tasks

## Implementation Tasks

### Phase 1: Remove Unused Imports (F401) - 2 hours

- [ ] **Circuit Breaker Module** (services/api_gateway/circuit_breaker.py)
  - [ ] Remove unused `dataclasses.field` import
  - [ ] Remove unused `datetime.timedelta` import

- [ ] **Circuit Breaker Client** (services/api_gateway/circuit_breaker_client.py)
  - [ ] Remove unused `asyncio` import
  - [ ] Remove unused `json` import
  - [ ] Remove unused `time` import
  - [ ] Remove unused `typing.Union` import

- [ ] **Graceful Degradation** (services/api_gateway/graceful_degradation.py)
  - [ ] Remove unused `asyncio` import
  - [ ] Remove unused `typing.Union` import

- [ ] **Pipeline Logic** (services/api_gateway/pipeline_logic.py)
  - [ ] Remove unused `asyncio` import
  - [ ] Remove unused `struct` import
  - [ ] Remove unused `enum.Enum` import
  - [ ] Remove unused `aiohttp` import
  - [ ] Remove unused `.circuit_breaker.CircuitBreakerOpenException` import
  - [ ] Remove unused `.graceful_degradation.graceful_degradation_manager` import
  - [ ] Remove unused `.service_health.service_health_manager` import

- [ ] **Route Modules**
  - [ ] Circuit breaker routes: Remove unused imports (Optional, Depends, JSONResponse, service_health_manager)
  - [ ] Customer routes: Remove unused JSONResponse import
  - [ ] Health routes: Remove unused HTMLResponse, JSONResponse, health_utils imports
  - [ ] Pipeline routes: Remove unused time, psutil, requests, URL imports
  - [ ] Session routes: Remove unused json, Union, Depends, File, Form, UploadFile, JSONResponse imports
  - [ ] Upload routes: Fix f-string placeholder issue

- [ ] **Core Modules**
  - [ ] Service health: Remove unused dataclasses.field, datetime.timedelta imports
  - [ ] Session: Remove unused JSONResponse import
  - [ ] WebSocket: Remove unused json, math imports

- [ ] **Service Applications**
  - [ ] ASR service: Clean unused imports
  - [ ] Translation service: Clean unused imports
  - [ ] TTS service: Remove unused os, re, base64 imports

- [ ] **Test Files**
  - [ ] Clean unused imports in all test files (os, pytest where unused)

### Phase 2: Fix Code Complexity (C901) - 6 hours

- [ ] **Critical Complexity (20+ complexity)**
  - [ ] `services/translation/app.py:translate()` (31) - Split into validation, processing, response phases
  - [ ] `services/api_gateway/service_health.py:get_gpu_summary()` (27) - Extract GPU metric collection functions
  - [ ] `services/api_gateway/pipeline_logic.py:validate_audio_input()` (20) - Separate validation steps
  - [ ] `services/tts/app.py:synthesize()` (18) - Extract synthesis pipeline functions

- [ ] **Moderate Complexity (11-13 complexity)**
  - [ ] `services/api_gateway/websocket.py:websocket_endpoint()` (13) - Extract message handling functions
  - [ ] `services/api_gateway/pipeline_logic.py:process_text_pipeline()` (12) - Separate pipeline stages
  - [ ] `services/asr/app.py:_collect_gpu_metrics()` (12) - Extract metric collection logic
  - [ ] `services/translation/app.py:_collect_gpu_metrics()` (12) - Extract metric collection logic
  - [ ] `services/tts/app.py:_collect_gpu_metrics()` (12) - Extract metric collection logic
  - [ ] `services/api_gateway/pipeline_logic.py:validate_text_input()` (11) - Split validation logic
  - [ ] `services/api_gateway/session_manager.py:_load_sessions_from_persistence()` (11) - Extract loading logic
  - [ ] `services/asr/app.py:transcribe()` (11) - Split transcription pipeline

### Phase 3: Fix Style and Naming Issues - 1 hour

- [ ] **Whitespace Issues (E226)**
  - [ ] Fix missing whitespace around arithmetic operator in `pipeline_logic.py:148` (2 instances)

- [ ] **Naming Violations**
  - [ ] N805: Fix method parameter naming in `session.py:53` (first argument should be 'self')
  - [ ] N811: Fix TTS constant import naming in `tts/app.py:67` (constant 'TTS' imported as non constant 'TTSApi')
  - [ ] N818: Rename `CircuitBreakerOpenException` to `CircuitBreakerOpenError`

### Phase 4: Fix Variable and Code Issues - 2 hours

- [ ] **Unused Variables (F841)**
  - [ ] Remove unused `bit_depth` variable in `pipeline_logic.py:430`
  - [ ] Remove unused `validation_start` variable in `session.py:346`
  - [ ] Remove unused `results` variable in `service_health.py:227`
  - [ ] Remove unused `e` variable in `asr/app.py:203`

- [ ] **Import Redefinitions (F811)**
  - [ ] Fix duplicate `File` import redefinition in `session.py:301`
  - [ ] Fix duplicate `Form` import redefinition in `session.py:301`
  - [ ] Fix duplicate `UploadFile` import redefinition in `session.py:301`
  - [ ] Fix duplicate `WebSocketDisconnect` redefinition in `websocket.py:1014`

- [ ] **Error Handling (E722)**
  - [ ] Replace bare except clause with specific exception handling in `websocket.py:1090`

- [ ] **F-string Issues (F541)**
  - [ ] Add missing placeholders or convert to regular strings in `circuit_breaker.py:283`
  - [ ] Fix f-string placeholder issue in `upload.py:28`

## Validation Tasks

- [ ] **Phase 1 Validation**
  - [ ] Run `python -m flake8 --select=F401` (should return 0 unused imports)
  - [ ] Run test suite after import cleanup
  - [ ] Verify no functionality broken

- [ ] **Phase 2 Validation**
  - [ ] Run `python -m flake8 --select=C901` (should return 0 complex functions)
  - [ ] Run full test suite after refactoring
  - [ ] Performance regression testing for critical paths

- [ ] **Phase 3 Validation**
  - [ ] Run `python -m flake8 --select=E226,N805,N811,N818`
  - [ ] Verify naming convention compliance

- [ ] **Phase 4 Validation**
  - [ ] Run `python -m flake8 --select=F841,F811,E722,F541`
  - [ ] Final full quality check: `./scripts/quality-check.sh`

## Final Validation

- [ ] **Complete Quality Check**
  - [ ] Run `python -m flake8` (should exit with code 0)
  - [ ] Run `./scripts/quality-check.sh` (should pass all checks)
  - [ ] Run full test suite (`pytest`)
  - [ ] Integration test validation
  - [ ] Code coverage verification

- [ ] **Documentation Updates**
  - [ ] Update code quality documentation
  - [ ] Record lessons learned
  - [ ] Update development guidelines

## Estimated Total Time: 11 hours
- Phase 1: 2 hours
- Phase 2: 6 hours
- Phase 3: 1 hour
- Phase 4: 2 hours

# Implementation Tasks - Fix Remaining Code Quality Issues

## Phase 1: Complex Function Refactoring (C901)

### Priority 1: Critical Complexity Issues (>20 complexity)
- [ ] **services/api_gateway/service_health.py:505** - `ServiceHealthManager.get_gpu_summary` (complexity 27)
  - Extract GPU metrics collection logic into separate methods
  - Create dedicated GPU status validation functions
  - Implement GPU error handling as separate concerns
- [ ] **services/translation/app.py:349** - `translate` function (complexity 31)
  - Split language detection and validation logic
  - Extract translation pipeline steps into separate functions
  - Create dedicated error handling and response formatting methods
- [ ] **services/api_gateway/pipeline_logic.py:109** - `validate_audio_input` (complexity 20)
  - Extract audio format validation logic
  - Create separate audio size and duration validation functions
  - Split error response generation into dedicated methods

### Priority 2: Moderate Complexity Issues (11-19)
- [ ] **services/tts/app.py:319** - `synthesize` function (complexity 18)
- [ ] **test_audio_validation_integration.py:43** - `test_session_endpoint` (complexity 16)
- [ ] **services/api_gateway/websocket.py:1033** - `websocket_endpoint` (complexity 13)
- [ ] **services/api_gateway/pipeline_logic.py:468** - `validate_text_input` (complexity 11)
- [ ] **services/api_gateway/pipeline_logic.py:668** - `process_text_pipeline` (complexity 12)
- [ ] **services/api_gateway/session_manager.py:266** - `_load_sessions_from_persistence` (complexity 11)
- [ ] **services/asr/app.py:71** - `_collect_gpu_metrics` (complexity 12)
- [ ] **services/asr/app.py:228** - `transcribe` (complexity 11)
- [ ] **services/translation/app.py:25** - `_collect_gpu_metrics` (complexity 12)
- [ ] **services/tts/app.py:84** - `_collect_gpu_metrics` (complexity 12)
- [ ] **test_pipeline_audio_validation.py:44** - `test_pipeline_endpoint` (complexity 26)
- [ ] **test_text_pipeline_integration.py:12** - `test_text_pipeline_integration` (complexity 26)
- [ ] **tests/conftest.py:12** - `If 12` (complexity 12)

## Phase 2: Unused Code Cleanup

### Unused Imports (F401) - 34 instances
- [ ] **services/api_gateway/routes/health.py** - Remove unused HTMLResponse, JSONResponse, get_health_status_html
- [ ] **services/api_gateway/websocket.py:1012** - Fix WebSocketDisconnect redefinition
- [ ] **Test files cleanup** - Remove unused imports in all test files:
  - [ ] test_audio_validation_integration.py (json)
  - [ ] test_pipeline_audio_validation.py (io)
  - [ ] test_text_pipeline_integration.py (json)
  - [ ] tests/conftest.py (typing.Any, typing.Dict)
  - [ ] tests/integration_test_audio_validation.py (io)
  - [ ] tests/test_admin_routes.py (asyncio)
  - [ ] tests/test_audio_validation.py (struct, AudioValidationError)
  - [ ] tests/test_circuit_breaker_integration.py (urllib.parse imports)
  - [ ] tests/test_mobile_optimization.py (asyncio, Session, SessionStatus)
  - [ ] tests/test_session_timeout.py (asyncio)
  - [ ] tests/test_text_pipeline.py (TextValidationResult, TextSpecs)
  - [ ] tests/test_translation_refiner.py (pytest)
  - [ ] tests/test_unified_message_endpoint.py (multiple unused imports)
  - [ ] tests/test_websocket_manager.py (multiple unused imports)

### Unused Variables (F841) - 19 instances
- [ ] **services/api_gateway/service_health.py:227** - Remove unused 'results' variable
- [ ] **services/asr/app.py:203** - Remove unused 'e' variable in exception handler
- [ ] **test_pipeline_audio_validation.py** - Remove unused 'e' variables in exception handlers (4 instances)
- [ ] **tests/test_circuit_breaker_integration.py:251** - Remove unused 'result2' variable
- [ ] **tests/test_session_manager.py:220** - Remove unused 'initial_session_count' variable
- [ ] **tests/test_websocket_manager.py** - Remove unused connection variables (11 instances)
- [ ] **tests/test_websocket_manager.py:418** - Remove unused 'admin_conn_id' variable
- [ ] **tests/test_websocket_manager.py:455** - Remove unused 'connection_id' variable

### Import/Function Redefinitions (F811) - 11 instances
- [ ] **tests/test_admin_routes.py:19** - Fix mock_session_manager redefinition
- [ ] **tests/test_unified_message_endpoint.py** - Fix multiple function redefinitions (8 instances)

## Phase 3: Formatting and Style Fixes

### Indentation Issues (E128) - 10 instances
- [ ] **tests/test_websocket_manager.py** - Fix continuation line indentation (10 instances)

### Blank Line Issues (E302, E303, E305, E306) - 20 instances
- [ ] **tests/test_admin_routes.py** - Add missing blank lines before function definitions (8 instances)
- [ ] **tests/test_circuit_breaker_integration.py** - Add missing blank lines (5 instances)
- [ ] **tests/test_rate_limiting.py:31** - Add missing blank line
- [ ] **tests/test_session_timeout.py:81** - Add blank line before nested definition
- [ ] **tests/test_translation_refiner.py:31** - Remove extra blank lines
- [ ] **tests/test_admin_routes.py:325** - Add blank lines after function definition

### Arithmetic Operator Spacing (E226) - 2 instances
- [ ] **test_text_pipeline_integration.py:204,223** - Add spaces around operators

### Boolean Comparison Issues (E712) - 5 instances
- [ ] **tests/test_mobile_optimization.py** - Fix boolean comparisons (4 instances)
- [ ] **tests/test_websocket_manager.py:461** - Fix boolean comparison

### Exception Handling (E722) - 1 instance
- [ ] **services/api_gateway/websocket.py:1088** - Replace bare except with specific exception

### f-string Issues (F541) - 4 instances
- [ ] **test_invalid_audio_validation.py** - Fix f-strings missing placeholders (2 instances)
- [ ] **test_pipeline_audio_validation.py:96** - Fix f-string missing placeholder
- [ ] **tests/test_circuit_breaker_integration.py:171** - Fix f-string missing placeholder

### Naming Convention Issues (N802) - 2 instances
- [ ] **tests/test_circuit_breaker_integration.py** - Fix function names do_GET, do_POST to lowercase

## Phase 4: Quality Validation

### Code Quality Checks
- [ ] Run flake8 with zero violations target
- [ ] Execute complete test suite (maintain 77/77 passing rate)
- [ ] Perform FastAPI application startup test
- [ ] Validate health endpoint functionality
- [ ] Run performance benchmark to ensure no regressions

### Documentation Updates
- [ ] Update code comments where functions were refactored
- [ ] Ensure docstrings are maintained for split functions
- [ ] Update any relevant README sections if architectural changes occurred

## Definition of Complete

Each task is considered complete when:
1. The specific flake8 violation is eliminated
2. Associated tests continue to pass
3. No new violations are introduced
4. Code maintains or improves readability

## Rollback Plan

If any phase introduces regressions:
1. Revert specific changes using git
2. Re-run test suite to confirm functionality restoration
3. Address issue with more targeted approach
4. Continue with remaining tasks

## Success Metrics

- **Primary**: flake8 reports 0 violations
- **Secondary**: All 77 tests pass
- **Tertiary**: FastAPI application starts successfully
- **Quality**: Code review confirms improved maintainability

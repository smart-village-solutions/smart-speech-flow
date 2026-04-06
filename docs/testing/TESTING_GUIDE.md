# Testing Guide

This guide covers all testing aspects of the Smart Speech Flow Backend project.

## Quick Links

- [Integration Tests Status](INTEGRATION_TESTS_STATUS.md) - Current test coverage and results
- [Audio Recording Tests](AUDIO_RECORDING_TEST_SUMMARY.md) - Audio feature test results
- [Manual Test Checklist](AUDIO_RECORDING_MANUAL_TEST_CHECKLIST.md) - Manual testing procedures
- [Browser Compatibility](AUDIO_RECORDING_BROWSER_TEST.md) - Cross-browser testing
- [Code Quality Standards](code-quality.md) - Quality tools and standards

## Test Overview

The repository contains:

- unit tests for service and gateway logic
- integration tests for session, audio and websocket flows
- load tests for production-like websocket scenarios

Because the suite changes over time, this guide intentionally does not hardcode pass/fail counts. Use the latest local `pytest` run or CI results as the source of truth.

## Running Tests

### All Tests
```bash
pytest tests/ -v
```

### Specific Test Categories
```bash
# Integration tests only
pytest tests/integration/ -v

# Unit tests only
pytest tests/ -v --ignore=tests/integration --ignore=tests/load

# Audio upload tests
pytest tests/test_audio_upload_integration.py -v

# WebSocket tests
pytest tests/integration/test_websocket_integration.py -v
```

### With Coverage
```bash
pytest --cov=services tests/ --cov-report=html
open htmlcov/index.html
```

### Quality Checks
```bash
# Run all quality checks (linting, type checking, security)
./scripts/quality-check.sh

# Individual tools
black services/ tests/
isort services/ tests/
flake8 services/ tests/
mypy services/
bandit -r services/
```

## Test Structure

### Unit Tests
Located in `tests/` root directory. Test individual components in isolation.

**Examples:**
- `test_admin_routes.py` - Admin API endpoints
- `test_audio_validation.py` - Audio validation logic
- `test_circuit_breaker_integration.py` - Circuit breaker functionality

### Integration Tests
Located in `tests/integration/`. Test component interactions and full workflows.

**Examples:**
- `test_websocket_integration.py` - WebSocket full flow
- `test_audio_validation_integration.py` - Audio pipeline integration
- `test_text_pipeline_integration.py` - Text translation pipeline

### Load Tests
Located in `tests/load/`. Performance and stress testing.

**Examples:**
- `test_websocket_load_performance.py` - WebSocket under load
- `test_websocket_production_validation.py` - Production readiness

## Testing Strategies

### 1. Unit Testing
Test individual functions and classes in isolation using mocks.

**Best Practices:**
- Mock external dependencies (ASR, TTS, Translation services)
- Test edge cases and error conditions
- Keep tests fast (< 1 second per test)
- Use descriptive test names

**Example:**
```python
def test_audio_upload_missing_file():
    """Test: Audio upload without file should return 400"""
    response = client.post(f"/api/session/{session_id}/message")
    assert response.status_code == 400
```

### 2. Integration Testing
Test component interactions with minimal mocking.

**Best Practices:**
- Test real API flows end-to-end
- Use test databases/fixtures
- Verify side effects (WebSocket broadcasts, storage)
- Test both success and failure paths

**Example:**
```python
def test_audio_pipeline_integration():
    """Test: Complete audio pipeline flow"""
    audio_file = create_test_wav()
    response = client.post(
        f"/api/session/{session_id}/message",
        files={"audio": audio_file},
        data={"client_type": "customer"}
    )
    assert response.status_code == 200
    assert "original_text" in response.json()
```

### 3. Manual Testing
For features requiring human judgment (UI/UX, audio quality).

See [Manual Test Checklist](AUDIO_RECORDING_MANUAL_TEST_CHECKLIST.md) for procedures.

### 4. Browser Compatibility Testing
Test across browsers for frontend-dependent features.

See [Browser Test Matrix](AUDIO_RECORDING_BROWSER_TEST.md) for coverage.

## Test Categories by Feature

### Audio Recording
- **Unit Tests:** `test_audio_upload_integration.py`, `test_audio_validation.py`
- **Integration:** `tests/integration/test_audio_validation_integration.py`
- **Manual:** [Manual Test Checklist](AUDIO_RECORDING_MANUAL_TEST_CHECKLIST.md)
- **Browser:** [Browser Compatibility](AUDIO_RECORDING_BROWSER_TEST.md)
- **Summary:** [Test Summary](AUDIO_RECORDING_TEST_SUMMARY.md)

### WebSocket Communication
- **Unit Tests:** `test_websocket_manager.py`, `test_websocket_fallback.py`
- **Integration:** `tests/integration/test_websocket_integration.py`
- **Load Tests:** `tests/load/test_websocket_load_performance.py`

### Session Management
- **Unit Tests:** `test_admin_routes.py`, `test_session_routes.py`
- **Integration:** Session lifecycle tests in integration suite

### API Contract
- **Validation:** `test_api_contract_integration.py`
- **OpenAPI:** `test_openapi_validation.py`

## Test Fixtures

### Audio Fixtures
Located in `tests/fixtures/`:
- `test_bible_text.json` - Sample text for translation tests

### Creating Test Audio
```python
from tests.conftest import create_test_wav

# Create test WAV file
audio_bytes = create_test_wav(
    duration_seconds=2.0,
    sample_rate=16000,
    channels=1
)
```

### Session Fixtures
```python
@pytest.fixture
def test_session(client):
    """Create a test session"""
    response = client.post("/api/admin/session/create")
    return response.json()["session_id"]
```

## Continuous Integration

### Pre-commit Hooks
Automatically run before commits:
- Code formatting (black, isort)
- Linting (flake8)
- Security checks (bandit)
- File checks (trailing whitespace, large files)

### GitHub Actions (Future)
Planned CI/CD pipeline:
- Run full test suite on PR
- Code coverage reporting
- Docker image builds
- Deployment automation

## Troubleshooting Tests

### Flaky Tests
Some tests may fail intermittently due to:
- **Timing issues:** Use `asyncio.sleep()` or `await` properly
- **Parallel execution:** Tests interfere with shared state
- **Network issues:** Docker service name resolution

**Solution:** Run flaky tests individually to verify they work:
```bash
pytest tests/test_audio_upload_integration.py::test_specific_test -v
```

### Docker Service Issues
If tests fail with connection errors:
```bash
# Check Docker services
docker compose ps

# Restart services
docker compose restart asr translation tts

# Check logs
docker compose logs asr --tail=50
```

### Database State
Tests may fail if database state is polluted:
```bash
# Reset test database (if using separate test DB)
# Add reset logic in conftest.py
```

## Test Metrics

### Current Coverage
- **Overall:** ~85% (estimated)
- **Core API:** 95%+
- **WebSocket:** 90%+
- **Audio Pipeline:** 90%+

### Performance Targets
- Unit tests: < 1s each
- Integration tests: < 5s each
- Full suite: < 60s

## Contributing Tests

### When to Write Tests
- ✅ New features → Add integration + unit tests
- ✅ Bug fixes → Add regression test
- ✅ Refactoring → Ensure existing tests pass
- ✅ API changes → Update contract tests

### Test Naming Convention
```python
def test_<component>_<scenario>_<expected_result>():
    """Test: <Human-readable description>"""
    pass
```

**Examples:**
- `test_audio_upload_missing_file_returns_400()`
- `test_websocket_broadcast_multiple_clients_success()`

### Test Structure (AAA Pattern)
```python
def test_example():
    """Test: Description"""
    # Arrange - Set up test data
    session_id = "TEST-123"
    audio_file = create_test_wav()

    # Act - Execute the test
    response = client.post(url, files={"audio": audio_file})

    # Assert - Verify results
    assert response.status_code == 200
    assert "original_text" in response.json()
```

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [Coverage.py](https://coverage.readthedocs.io/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Integration Tests Status](INTEGRATION_TESTS_STATUS.md)

---

**Last Updated:** 2025-11-13

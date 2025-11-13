# Documentation Index

Welcome to the Smart Speech Flow Backend documentation! This guide helps you find the right documentation for your needs.

## 📚 Quick Navigation

### For Developers
- [Architecture Overview](architecture/SYSTEM_ARCHITECTURE.md) - System design and components
- [Frontend Integration Guide](guides/frontend-integration.md) - How to integrate with the frontend
- [API Conventions](guides/api-conventions.md) - API design patterns and standards
- [Code Quality Standards](testing/code-quality.md) - Coding standards and quality checks

### For Operators
- [Deployment Rollback Procedure](operations/deployment-rollback-procedure.md) - How to rollback deployments
- [WebSocket Production Checklist](operations/WEBSOCKET_PRODUCTION_CHECKLIST.md) - Pre-deployment checklist
- [Audio Recording Rollback Strategy](operations/AUDIO_RECORDING_ROLLBACK_STRATEGY.md) - Rollback procedures
- [WebSocket Broadcast Failures Runbook](operations/runbooks/websocket-broadcast-failures.md) - Troubleshooting guide

### For Testers
- [Integration Tests Status](testing/INTEGRATION_TESTS_STATUS.md) - Current test coverage
- [Audio Recording Test Summary](testing/AUDIO_RECORDING_TEST_SUMMARY.md) - Audio feature test results
- [Manual Test Checklist](testing/AUDIO_RECORDING_MANUAL_TEST_CHECKLIST.md) - Manual testing procedures
- [Browser Test Matrix](testing/AUDIO_RECORDING_BROWSER_TEST.md) - Cross-browser compatibility

## 📖 Documentation Structure

### `/architecture/` - System Architecture
High-level system design, component interactions, and architectural decisions.

**Contents:**
- `SYSTEM_ARCHITECTURE.md` - Overall system architecture
- `websocket-architecture.md` - WebSocket implementation details
- `websocket-architecture-analysis.md` - Architecture analysis and patterns
- `websocket-message-flow-diagrams.md` - Message flow visualizations
- `session-flow.md` - Session lifecycle and state management
- `models.md` - Data models and schemas

### `/guides/` - User & Integration Guides
Step-by-step guides for common tasks and integrations.

**Contents:**
- `frontend-integration.md` - Frontend integration guide
- `audio-format-handling.md` - Audio format conversion and handling
- `audio-recording-monitoring.md` - Post-deployment monitoring
- `api-conventions.md` - API design patterns
- `customer-api.md` - Customer-facing API documentation
- `frontend_api.md` - Frontend API reference

### `/operations/` - Operational Documentation
Deployment procedures, monitoring, and incident response.

**Contents:**
- `deployment-rollback-procedure.md` - How to rollback deployments
- `deployment-websocket-reconnection.md` - WebSocket reconnection handling
- `WEBSOCKET_PRODUCTION_CHECKLIST.md` - Pre-deployment checklist
- `AUDIO_RECORDING_ROLLBACK_STRATEGY.md` - Audio feature rollback
- **`/runbooks/`** - Troubleshooting runbooks
  - `websocket-broadcast-failures.md` - WebSocket broadcast issues

### `/testing/` - Test Documentation
Test strategies, results, and quality assurance procedures.

**Contents:**
- `INTEGRATION_TESTS_STATUS.md` - Integration test coverage
- `AUDIO_RECORDING_TEST_SUMMARY.md` - Audio feature test results
- `AUDIO_RECORDING_MANUAL_TEST_CHECKLIST.md` - Manual testing procedures
- `AUDIO_RECORDING_TEST_MATRIX.md` - Test coverage matrix
- `AUDIO_RECORDING_BROWSER_TEST.md` - Cross-browser testing
- `code-quality.md` - Code quality standards and tools

### `/archive/` - Historical Documentation
Development logs, old decisions, and archived documentation.

**Contents:**
- **`/development-log/`** - Historical development notes
  - Various bug fixes, feature implementations, and debugging sessions
  - Kept for reference but not part of active documentation

### `/adr/` - Architecture Decision Records
Important architectural decisions and their rationale.

### `/frontend-integration/` - Frontend Integration Details
Detailed frontend integration examples and patterns.

### `/reports/` - Analysis Reports
Performance reports, security audits, and analysis documents.

## 🔍 Finding Documentation

### By Topic
- **WebSocket:** `architecture/websocket-*.md`, `operations/WEBSOCKET_*.md`
- **Audio Recording:** `guides/audio-*.md`, `testing/AUDIO_RECORDING_*.md`
- **Frontend:** `guides/frontend-*.md`, `frontend-integration/`
- **Deployment:** `operations/deployment-*.md`
- **Testing:** `testing/` directory

### By Role
- **Backend Developer:** Start with `architecture/SYSTEM_ARCHITECTURE.md`
- **Frontend Developer:** Start with `guides/frontend-integration.md`
- **DevOps Engineer:** Start with `operations/` directory
- **QA Engineer:** Start with `testing/` directory
- **New Contributor:** See main `../README.md` and `../CONTRIBUTING.md` (coming soon)

## 📝 Contributing to Documentation

When adding new documentation:

1. **Choose the right location:**
   - Technical architecture → `/architecture/`
   - How-to guides → `/guides/`
   - Operations/deployment → `/operations/`
   - Testing procedures → `/testing/`
   - Historical/archived → `/archive/`

2. **Follow naming conventions:**
   - Use kebab-case: `my-new-guide.md`
   - Be descriptive but concise
   - Avoid abbreviations in filenames

3. **Update this index:**
   - Add your new document to the appropriate section
   - Update the quick navigation if relevant

4. **Cross-link related documents:**
   - Link to related documentation
   - Use relative paths: `[Link](../architecture/file.md)`

## 🔗 External Resources

- [Main README](../README.md) - Project overview and quick start
- [OpenAPI Specification](openapi.yaml) - REST API documentation
- [Repository](https://github.com/smart-village-solutions/smart-speech-flow-backend) - Source code

## 📮 Questions?

If you can't find what you're looking for:
1. Check the main [README](../README.md)
2. Search the codebase for relevant comments
3. Open an issue on GitHub
4. Contact the maintainers

---

**Last Updated:** 2025-11-13
**Maintained by:** Smart Village Solutions Team

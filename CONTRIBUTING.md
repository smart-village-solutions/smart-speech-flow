# Contributing to Smart Speech Flow Backend

Thank you for your interest in contributing! This guide will help you get started quickly.

## 🚀 Quick Links

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Documentation](docs/README.md)
- [Testing Guide](docs/testing/TESTING_GUIDE.md)
- [Architecture Overview](docs/architecture/SYSTEM_ARCHITECTURE.md)

## 🏁 Getting Started (3 Steps)

### 1. Fork & Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/smart-speech-flow-backend.git
cd smart-speech-flow-backend

# Add upstream remote
git remote add upstream https://github.com/smart-village-solutions/smart-speech-flow-backend.git
```

### 2. Set Up Development Environment

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install development dependencies
pip install -r requirements-dev.txt

# Start services with Docker Compose
docker compose up -d
```

### 3. Create a Feature Branch

```bash
# Update main branch
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name
```

## 🧪 Testing Requirements

**All pull requests must include tests** and pass the existing test suite.

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=services --cov-report=html

# Run specific test categories
pytest tests/integration/           # Integration tests
pytest tests/test_admin_routes.py  # Admin API tests

# View coverage report
open htmlcov/index.html  # Linux/Mac
start htmlcov/index.html # Windows
```

**Test Status:** 234/242 tests passing (96.7%). See [TEST_STATUS.md](TEST_STATUS.md) for details.

**Learn more:** [Testing Guide](docs/testing/TESTING_GUIDE.md)

## 📝 Code Style

We follow strict code quality guidelines to maintain consistency.

### Python Code Style

```bash
# Format code with black
black services/

# Sort imports with isort
isort services/

# Lint with flake8
flake8 services/

# Security check with bandit
bandit -r services/

# Run all quality checks
./scripts/quality-check.sh
```

**Configuration:**
- Black: line length 100, Python 3.12+
- isort: compatible with black
- flake8: max line length 100, ignore E203, W503
- bandit: security-focused linting

### Pre-commit Hooks

We use pre-commit hooks to enforce code quality:

```bash
# Install pre-commit hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

Hooks will automatically:
- Trim trailing whitespace
- Fix end-of-file issues
- Check YAML/JSON syntax
- Run black and isort

## 🔀 Pull Request Process

### 1. Write Quality Code

- Follow Python PEP 8 style guide
- Add docstrings to public functions/classes
- Include type hints where appropriate
- Keep functions small and focused
- Write self-documenting code

### 2. Write Tests

- Add unit tests for new functions
- Add integration tests for new endpoints
- Ensure existing tests still pass
- Aim for >80% code coverage on new code

### 3. Update Documentation

- Update README.md if adding features
- Add/update docstrings
- Update relevant docs in `docs/` folder
- Add examples for new APIs

### 4. Commit Changes

Use [Conventional Commits](https://www.conventionalcommits.org/):

```bash
# Feature
git commit -m "feat: add support for new audio format"

# Bug fix
git commit -m "fix: resolve WebSocket reconnection issue"

# Documentation
git commit -m "docs: update API examples in README"

# Tests
git commit -m "test: add integration tests for translation service"

# Refactoring
git commit -m "refactor: simplify WebSocket manager initialization"

# Performance
git commit -m "perf: optimize model loading with lazy initialization"
```

**Commit types:**
- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `test:` Test additions/modifications
- `refactor:` Code refactoring
- `perf:` Performance improvements
- `chore:` Maintenance tasks

### 5. Push & Create Pull Request

```bash
# Push to your fork
git push origin feature/your-feature-name

# Create pull request on GitHub
```

**Pull Request Template:**

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] New tests added
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings
```

### 6. Review Process

- Maintainers will review your PR within 2-3 business days
- Address any requested changes
- Once approved, maintainers will merge your PR

## 🎯 First-Time Contributors

**Looking for something to work on?** Check these:

1. Issues labeled [`good-first-issue`](https://github.com/smart-village-solutions/smart-speech-flow-backend/labels/good-first-issue)
2. Issues labeled [`help-wanted`](https://github.com/smart-village-solutions/smart-speech-flow-backend/labels/help-wanted)
3. Documentation improvements
4. Test coverage improvements

**Need help?**
- Ask questions in issue comments
- Open a [Discussion](https://github.com/smart-village-solutions/smart-speech-flow-backend/discussions)
- Tag maintainers with `@maintainer-name`

## 🐛 Reporting Bugs

Use the [Bug Report template](https://github.com/smart-village-solutions/smart-speech-flow-backend/issues/new?template=bug_report.md):

**Include:**
- Clear bug description
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, Docker version)
- Relevant logs/screenshots

## 💡 Suggesting Features

Use the [Feature Request template](https://github.com/smart-village-solutions/smart-speech-flow-backend/issues/new?template=feature_request.md):

**Include:**
- Clear feature description
- Use case / problem it solves
- Proposed implementation (optional)
- Alternatives considered

## 📂 Project Structure

```
ssf-backend/
├── services/               # Microservices
│   ├── api_gateway/       # API Gateway & WebSocket manager
│   ├── asr/               # Speech recognition (Whisper)
│   ├── translation/       # Translation (M2M100)
│   └── tts/               # Text-to-speech (Coqui/MMS)
├── tests/                 # Test suite
│   ├── integration/       # Integration tests
│   ├── load/              # Load tests
│   └── fixtures/          # Test fixtures
├── docs/                  # Documentation
│   ├── architecture/      # Architecture docs
│   ├── guides/            # How-to guides
│   ├── operations/        # Operations runbooks
│   └── testing/           # Testing documentation
├── monitoring/            # Prometheus & Grafana config
├── scripts/               # Helper scripts
└── examples/              # Example files
```

## 🔧 Development Workflow

### Local Development

```bash
# Start services in development mode
docker compose up

# Run specific service locally (for debugging)
source .venv/bin/activate
uvicorn services/asr/app:app --port 8001 --reload

# Check logs
docker compose logs -f <service_name>

# Restart service
docker compose restart <service_name>
```

### Testing Workflow

```bash
# 1. Run tests before committing
pytest

# 2. Run quality checks
./scripts/quality-check.sh

# 3. Fix any issues
black services/
isort services/

# 4. Commit changes
git add .
git commit -m "feat: your feature"

# 5. Push to fork
git push origin feature/your-feature
```

### Debugging Tips

```bash
# Check service health
curl http://localhost:8000/health

# Check GPU availability
docker compose exec asr python3 -c "import torch; print(torch.cuda.is_available())"

# View real-time logs
docker compose logs -f --tail=100

# Enter container shell
docker compose exec api_gateway bash

# Check Prometheus metrics
curl http://localhost:8000/metrics
```

## 🔐 Security

**Found a security vulnerability?**

**DO NOT** open a public issue. Instead:
- Email security concerns to the maintainers
- Include detailed description and reproduction steps
- Wait for acknowledgment before public disclosure

See [SECURITY.md](SECURITY.md) for our security policy.

## 📋 Code Review Guidelines

**For reviewers:**
- Be constructive and respectful
- Focus on code quality, not style (automated tools handle that)
- Suggest improvements, don't demand them
- Approve when tests pass and code is maintainable

**For contributors:**
- Be open to feedback
- Ask questions if feedback is unclear
- Make requested changes promptly
- Thank reviewers for their time

## 📜 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

## 🤝 Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## 📞 Getting Help

- 💬 [GitHub Discussions](https://github.com/smart-village-solutions/smart-speech-flow-backend/discussions)
- 🐛 [GitHub Issues](https://github.com/smart-village-solutions/smart-speech-flow-backend/issues)
- 📖 [Documentation](docs/README.md)

---

**Thank you for contributing to Smart Speech Flow!** 🎉

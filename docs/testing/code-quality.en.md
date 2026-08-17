# Code Quality Standards

This document describes the code-quality standards for Smart Speech Flow Backend. All changes must satisfy the applicable quality gates.

## Tools and standards

### Formatting and imports

- **Black** formats Python code. The project configuration uses 100 columns, while the pre-commit hook enforces 88 columns: `black services/`.
- **isort** keeps imports Black-compatible. The pre-commit hook also uses an 88-column setting: `isort services/`.
- Both are included in the pre-commit workflow.

### Static analysis

- **flake8** checks style and potential errors using `setup.cfg`: `flake8 services/`.
- The configured rule set includes `flake8-bugbear`, `flake8-docstrings`, and `pep8-naming`.
- **MyPy** provides gradual type checking: `mypy services/api_gateway/`.

### Security and dependency analysis

- **Bandit** scans Python code: `bandit -r services/`. The current CI job fails only when it finds more than five combined high- or medium-severity findings; all findings should still be reviewed.
- **pip-audit** reports known dependency vulnerabilities: `pip-audit`.

### Centralized analysis

- **SonarCloud** analyzes maintainability, code smells, duplication, and its quality gate in GitHub Actions.
- **Fallow** audits changed TypeScript/JavaScript files in `services/frontend` during pull requests. Run it locally with `npm run fallow` or `npm run fallow:audit` from that directory.

## Quality gates

Pre-commit hooks enforce local formatting, import sorting, linting, and high-severity Bandit checks before a commit. In the current CI workflow, Black and isort findings are reported as warnings, Flake8 is reporting-only, MyPy is non-blocking, and pip-audit is non-blocking. The security job enforces its Bandit threshold; SonarCloud and Fallow enforce their configured pull-request behavior.

Type coverage, medium security findings, and complexity improvements are advisory but should improve over time. Keep functions below complexity 15 where practical.

## Local workflow

```bash
pre-commit install
pre-commit run --all-files

./scripts/quality-check.sh
black services/
isort services/
flake8 services/
bandit -r services/
pip-audit
```

GitHub Actions runs code quality, security, type checking, dependency analysis, and SonarCloud on tracked branches and pull requests. SonarCloud requires the `SONAR_TOKEN` repository secret; `SONAR_ORGANIZATION` and `SONAR_PROJECT_KEY` are optional repository variables. Without the optional variables, the workflow derives values from the repository owner and name.

## Developer expectations

For new code, add type annotations where appropriate, document public APIs, test locally, and commit only after relevant checks pass. Improve nearby legacy code incrementally when changing it; prioritize security issues. During review, check the quality status, type coverage for new work, security implications, and performance impact for large changes.

## Troubleshooting

```bash
# Apply formatting fixes
black services/
isort services/

# Refresh or repair hooks
pre-commit autoupdate
pre-commit clean
pre-commit install --overwrite

# Install common missing type stubs
pip install types-requests types-redis
```

For Flake8 line-length findings, split long strings or comments and use parenthesized multiline expressions. Avoid blanket type ignores; use them only when third-party stubs are genuinely unavailable.

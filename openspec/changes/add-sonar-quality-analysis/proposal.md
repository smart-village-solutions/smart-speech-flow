# Change: Add Sonar Quality Analysis

## Why

The repository already runs formatting, linting, security checks, and limited type checking in GitHub Actions, but it lacks a unified code-quality dashboard and a review-time quality gate. This makes it harder to track code smells, duplication, maintainability hotspots, and long-term quality trends across the project.

Introducing Sonar improves visibility and creates a single place for quality analysis that complements the existing Python tooling instead of replacing it.

## What Changes

- Add Sonar-based quality analysis to the CI pipeline
- Use GitHub-integrated pull request analysis and quality gate feedback
- Define the minimal required project configuration for Sonar analysis
- Decide and document the default operating model:
  - recommended default: **SonarCloud with GitHub Actions**
  - alternative: self-hosted SonarQube for environments with stricter hosting requirements
- Integrate existing test and static-analysis outputs where useful
- Document required repository secrets, onboarding, and failure behavior

## Impact

- Affected specs: `cicd-pipeline`
- Affected code:
  - `.github/workflows/code-quality.yml`
  - potential new `sonar-project.properties`
  - developer and CI documentation

## Non-Goals

- Replacing Black, isort, flake8, Bandit, pip-audit, or MyPy
- Introducing branch protection rules directly in this change
- Refactoring existing code purely to satisfy Sonar findings
- Full self-hosted SonarQube deployment automation

## Decision Summary

This proposal recommends **SonarCloud** as the initial implementation target because the repository already uses GitHub Actions and benefits from simpler setup, hosted analysis infrastructure, and native pull request decoration. If hosting policy later requires a self-managed solution, the CI contract and project configuration defined here should remain largely reusable.

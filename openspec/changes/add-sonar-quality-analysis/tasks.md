## 1. Planning

- [x] 1.1 Confirm Sonar operating model (SonarCloud by default, SonarQube as documented alternative)
- [x] 1.2 Define the initial quality gate policy for pull requests
- [x] 1.3 Define repository secrets and ownership for Sonar administration

## 2. Configuration

- [x] 2.1 Add repository-level Sonar project configuration
- [x] 2.2 Define source, test, exclusion, and report paths for Python and frontend code
- [x] 2.3 Document required environment variables or secrets

## 3. CI Integration

- [x] 3.1 Extend GitHub Actions to run Sonar analysis
- [x] 3.2 Integrate Sonar with pull request analysis and branch analysis
- [x] 3.3 Ensure Sonar execution fits alongside existing code-quality jobs without duplicating their purpose

## 4. Quality Gates

- [x] 4.1 Configure the initial quality gate behavior
- [ ] 4.2 Validate expected CI behavior for passing and failing analyses
- [x] 4.3 Document how Sonar findings should be triaged and resolved

## 5. Documentation

- [x] 5.1 Update contributor or quality documentation with Sonar setup and usage
- [x] 5.2 Document local expectations versus CI-only Sonar execution
- [x] 5.3 Document follow-up work for coverage integration and rule tightening

# Documentation Structure Specification Delta

**Capability:** Documentation Structure
**Change:** prepare-public-launch
**Type:** Repository Maintenance

## MODIFIED Requirements

### Requirement: Documentation Organization (REQ-DOC-001)

**Description:** Documentation must be organized in a logical, discoverable structure that supports both new and experienced contributors.

**Changes:**
- Consolidate scattered documentation into topic-based directories
- Remove redundant and obsolete documentation
- Create clear navigation paths through documentation index

**Rationale:** Current flat structure with 47+ docs is overwhelming. Organized structure helps external contributors find information quickly.

#### Scenario: New Contributor Onboarding
**Given** a developer clones the repository for the first time
**When** they want to understand the WebSocket architecture
**Then** they should find it in `docs/architecture/websocket-architecture.md` (not scattered across 5+ files)

#### Scenario: Operations Team Deployment
**Given** the operations team needs to deploy the system
**When** they look for deployment documentation
**Then** they should find all deployment docs in `docs/operations/` (not mixed with development logs)

### Requirement: Archive Development Artifacts (REQ-DOC-002)

**Description:** Development process documentation (debugging logs, fix documentation, development comparisons) must be archived separately from user-facing documentation.

**Changes:**
- Move completed development logs to `docs/archive/development-log/`
- Keep only current, actionable documentation in main docs/
- Preserve history for future reference but remove from main navigation

**Rationale:** External contributors don't need to see internal debugging process. Archiving maintains history while reducing clutter.

#### Scenario: External Contributor Searches Documentation
**Given** an external contributor searches the docs/ directory
**When** they list the documentation files
**Then** they should see only current, relevant documentation (not 10+ debugging/fix logs from development)

### Requirement: Repository Cleanliness (REQ-DOC-003)

**Description:** Repository must not contain build artifacts, cache files, or development debris.

**Changes:**
- Remove all Python cache files (*.pyc, __pycache__)
- Update .gitignore to prevent future cache file commits
- Move test fixtures to appropriate test directories
- Remove debug artifacts from docs/archive/

**Rationale:** Professional open-source projects maintain clean repositories. Cache files confuse contributors and bloat git history.

#### Scenario: Fresh Repository Clone
**Given** a developer clones the repository
**When** they run `git status` after clone
**Then** they should see no untracked cache files or build artifacts

#### Scenario: Test Execution
**Given** a developer runs the test suite
**When** tests create cache files
**Then** these files should be automatically ignored by .gitignore (not appear in git status)

## ADDED Requirements

### Requirement: Contributor Onboarding Documentation (REQ-DOC-004)

**Description:** Repository MUST include clear, comprehensive documentation that enables new contributors to get started within 5 minutes.

**Changes:**
- Add CONTRIBUTING.md with setup instructions
- Add CODE_OF_CONDUCT.md for community standards
- Add GitHub issue/PR templates
- Enhance README with quick start guide

**Rationale:** Professional open-source projects make it easy for external contributors to participate. Clear onboarding documentation increases community engagement.

#### Scenario: First-Time Contributor Setup
**Given** a developer wants to contribute to the project
**When** they follow the CONTRIBUTING.md guide
**Then** they should have a working development environment in < 5 minutes

#### Scenario: Issue Reporting
**Given** a user encounters a bug
**When** they create a GitHub issue
**Then** they should see a template that guides them to provide necessary information

### Requirement: Launch-Ready README (REQ-DOC-005)

**Description:** README MUST present a professional, welcoming first impression that clearly communicates project value and gets users started quickly.

**Changes:**
- Add badges (license, Python version, Docker)
- Add "Features at a Glance" section
- Restructure for better information flow
- Add clear quick start (3 commands to get running)
- Add placeholder for demo video/screenshots

**Rationale:** README is the first thing press and potential contributors see. Professional presentation builds credibility.

#### Scenario: Press Conference Attendee Visits Repository
**Given** a journalist visits the GitHub repository after the press conference
**When** they view the README
**Then** they should immediately understand what the project does, see it's actively maintained (badges), and have a clear path to try it

#### Scenario: Developer Quick Start
**Given** a developer wants to try the system
**When** they follow the README quick start
**Then** they should have the system running locally with 3 commands: clone, docker compose up, test

## MODIFIED Requirements

### Requirement: OpenSpec Change Management (REQ-DOC-006)

**Description:** Completed OpenSpec changes MUST be archived to maintain clarity about active vs completed work.

**Changes:**
- Archive `enhance-websocket-message-metadata` (100% complete)
- Archive `refactor-websocket-architecture` (100% complete)
- Archive `add-frontend-audio-recording` (101% complete - all done)
- Document status of incomplete changes

**Rationale:** Active changes directory should only show ongoing work. Completed changes should be archived with timestamps for historical reference.

#### Scenario: External Contributor Reviews Active Work
**Given** a contributor wants to understand what features are in development
**When** they run `openspec list`
**Then** they should see only active, ongoing changes (not completed work from previous months)

#### Scenario: Historical Reference
**Given** a developer needs to understand how a feature was implemented
**When** they check the archived changes
**Then** they should find the complete proposal, tasks, and implementation details in `openspec/changes/archive/YYYY-MM-DD-<change-id>/`

## Non-Functional Requirements

### NFR-DOC-001: Zero Breakage Guarantee

**Description:** All cleanup and documentation changes must not break existing functionality.

**Acceptance Criteria:**
- All tests pass before and after changes (10/10 integration tests + unit tests)
- Docker Compose builds and runs successfully
- No changes to production code (services/ directory)
- All commits are atomic and reversible

#### Scenario: Post-Cleanup Testing
**Given** all documentation and cleanup changes are committed
**When** the full test suite is executed
**Then** all tests must pass with 100% success rate (no regressions)

### NFR-DOC-002: Link Integrity

**Description:** All internal documentation links must remain valid after reorganization.

**Acceptance Criteria:**
- No broken internal links in README
- No broken internal links in docs/ directory
- All references updated to new file locations

#### Scenario: Documentation Navigation
**Given** a user is reading documentation
**When** they click any internal link
**Then** the link should navigate to the correct document (no 404s)

### NFR-DOC-003: Timeline Adherence

**Description:** All changes must be completed before press conference (2025-11-14).

**Acceptance Criteria:**
- Phases 1-5 completed in 10-12 hours
- Phase 6 completed 1 hour before press conference
- Emergency rollback plan ready if deadline at risk

#### Scenario: Launch Deadline Pressure
**Given** the press conference is in 2 hours
**When** not all phases are complete
**Then** emergency abort plan should be executed (merge only Phases 1-2, skip documentation reorganization)

## Implementation Notes

### File Operations Safety
- Use `git mv` for moving files (preserves history)
- Commit changes atomically (one logical change per commit)
- Test after each commit (pytest + docker compose)

### Documentation Migration
- Update all internal links when moving files
- Use grep/rg to find references: `rg "old-filename.md" .`
- Verify links manually after reorganization

### Validation Gates
Each phase must pass validation before proceeding:
- Phase 2: All tests pass
- Phase 3: No broken links
- Phase 5: Fresh clone test succeeds

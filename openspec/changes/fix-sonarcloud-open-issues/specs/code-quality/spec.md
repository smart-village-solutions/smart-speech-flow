## ADDED Requirements

### Requirement: SonarCloud Backlog Remediation
The repository SHALL resolve open SonarCloud findings in shipped source paths without intentionally changing documented product behavior.

#### Scenario: Security and blocker findings are removed first
- **WHEN** the SonarCloud backlog is remediated
- **THEN** security and blocker findings are fixed before lower-severity cleanup
- **AND** the resulting code avoids logging unsanitized user-controlled data
- **AND** direct local startup binds to loopback rather than all interfaces

#### Scenario: FastAPI contracts remain documented after cleanup
- **WHEN** API routes raise `HTTPException`
- **THEN** the corresponding route decorators declare those responses in OpenAPI metadata
- **AND** FastAPI dependencies use `Annotated[...]` where required by the framework conventions

#### Scenario: Final validation confirms clean analysis
- **WHEN** the implementation is complete
- **THEN** local code validation passes for the touched modules
- **AND** the SonarCloud project reports no open issues for the remediated change set

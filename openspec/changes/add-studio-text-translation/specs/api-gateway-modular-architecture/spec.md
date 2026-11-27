## MODIFIED Requirements

### Requirement: No legacy one-shot routes

The gateway SHALL NOT serve the legacy `POST /pipeline`, `POST /upload` or `GET /` routes. Conversation speech processing SHALL be reachable only through the tenant-aware session message routes. Explicitly enabled, authenticated text-only translation routes SHALL use a bounded, session-independent text workflow.

#### Scenario: Legacy route requested

- **WHEN** a client calls `POST /pipeline`, `POST /upload` or `GET /`
- **THEN** the gateway answers 404 and runs no pipeline

#### Scenario: Studio requests text translation

- **WHEN** an authorized Studio client submits a valid batch to the enabled `POST /api/v1/translate`
- **THEN** the gateway invokes text translation without creating or accessing a conversation or invoking ASR or TTS

## MODIFIED Requirements

### Requirement: No legacy one-shot routes

The gateway SHALL NOT serve the legacy `POST /pipeline`, `POST /upload` or
`GET /` routes. Conversation speech processing SHALL be reachable only through
the tenant-aware session message routes. The versioned anonymous text-only
translation API SHALL be an explicit exception for session-independent text
translation, without exposing the conversation pipeline, ASR or TTS.

#### Scenario: Legacy route requested

- **WHEN** a client calls `POST /pipeline`, `POST /upload` or `GET /`
- **THEN** the gateway answers 404 and runs no pipeline

#### Scenario: Anonymous text translation requested

- **WHEN** a valid anonymous request reaches the enabled `POST /api/v1/translate`
- **THEN** the gateway invokes only the bounded text translation workflow,
  without creating or accessing a tenant conversation

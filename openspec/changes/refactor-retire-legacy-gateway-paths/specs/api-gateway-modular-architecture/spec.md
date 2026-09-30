## ADDED Requirements

### Requirement: No legacy one-shot routes

The gateway SHALL NOT serve the legacy `POST /pipeline`, `POST /upload` or `GET /` routes. Speech processing SHALL be reachable only through the tenant-aware session message routes.

#### Scenario: Legacy route requested

- **WHEN** a client calls `POST /pipeline`, `POST /upload` or `GET /`
- **THEN** the gateway answers 404 and runs no pipeline

### Requirement: One translation tail for audio and text

Audio and text messages SHALL pass through one shared translation, refinement and TTS implementation, differing only in how the source text is produced.

#### Scenario: Refinement fails for either mode

- **WHEN** refinement fails for an audio or a text message
- **THEN** both keep the unrefined translation and continue to TTS with the same payload shape

#### Scenario: Empty transcript

- **WHEN** ASR returns a transcript that is empty after stripping whitespace
- **THEN** the message route answers 422 with error code `NO_SPEECH_RECOGNIZED`, and no message is created, stored or broadcast

### Requirement: Unhandled-error policy

The gateway SHALL answer an unhandled HTTP exception with a JSON 500 that carries CORS headers, and SHALL log its stack frames and exception type without the exception message. A broad exception handler SHALL exist only where it implements a fallback, a boundary guard or bookkeeping before re-raising.

#### Scenario: Unhandled exception in a route

- **WHEN** a route raises an unexpected exception before its response starts
- **THEN** the client receives `500 {"detail": "Internal server error"}` with CORS headers, and the log carries the stack frames and the original exception type but not the exception message

#### Scenario: New broad handler

- **WHEN** a production module gains a broad exception handler that is not in the inventory
- **THEN** the hermetic test suite fails and names its module and function

### Requirement: Gateway module size budget

No production module in `services/api_gateway` SHALL exceed 800 lines.

#### Scenario: Module grows past the budget

- **WHEN** a gateway production module exceeds 800 lines
- **THEN** the hermetic test suite fails and names the module

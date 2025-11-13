# API Conventions & Terminology Reference

## Overview

This document establishes naming conventions, terminology standards, and API design patterns for the Smart Speech Flow backend. Following these conventions ensures consistency, reduces confusion, and improves code maintainability.

**Last Updated**: 2025-11-05
**Status**: Living Document

---

## Table of Contents

1. [Terminology Reference](#terminology-reference)
2. [Naming Conventions](#naming-conventions)
3. [API Design Patterns](#api-design-patterns)
4. [Type Safety](#type-safety)
5. [Documentation Standards](#documentation-standards)

---

## Terminology Reference

### Core Concepts

#### Admin vs. Customer

| Term | Definition | Usage Context | Examples |
|------|------------|---------------|----------|
| **Admin** | Administrative staff member (German-speaking) | User role, access level | `admin_language`, `admin_connected`, `ClientType.admin` |
| **Customer** | End-user/citizen (multilingual) | User role, service recipient | `customer_language`, `customer_connected`, `ClientType.customer` |
| **Client** | Technical HTTP/WebSocket client | Library, protocol context | `http_client`, `websocket_client`, `client_library` |

**Decision**: Use **"customer"** for end-users, reserve **"client"** for technical contexts only.

**Rationale**:
- Reduces ambiguity ("client" could mean person or software)
- Matches business domain language (admin serves customers)
- Aligns with existing `ClientType.customer` enum value
- Improves code readability and maintainability

#### Correct vs. Incorrect Usage

✅ **Correct**:
```python
customer_id: str
customer_language: str
customer_message: SessionMessage
customer_connected: bool

# Technical context
http_client = httpx.AsyncClient()
websocket_client = WebSocket()
```

❌ **Incorrect**:
```python
client_id: str          # Ambiguous - person or software?
client_language: str    # Use customer_language
client_message: dict    # Use customer_message
```

### Session Concepts

| Term | Definition | Example |
|------|------------|---------|
| **Session** | A conversation between admin and customer | Session ID: `53F795DE` |
| **Session ID** | Short UUID identifier (8 chars) | `ABC12345` |
| **Client Type** | Role in session (admin or customer) | `ClientType.admin`, `ClientType.customer` |
| **Connection ID** | Unique WebSocket connection identifier | `53F795DE_admin_1762347760` |

### Message Concepts

| Term | Definition | Field Name |
|------|------------|------------|
| **Original Text** | ASR-recognized text in source language | `original_text` |
| **Translated Text** | Translation in target language | `translated_text` |
| **Audio Data** | Base64-encoded audio file | `audio_base64` |
| **Audio URL** | Public URL to audio file | `audio_url` |
| **Sender** | Who sent the message (admin or customer) | `sender` |
| **Source Language** | Input language code (ISO 639-1) | `source_lang` |
| **Target Language** | Output language code (ISO 639-1) | `target_lang` |

---

## Naming Conventions

### General Rules

1. **Use snake_case** for all Python identifiers (variables, functions, parameters)
2. **Use PascalCase** for classes and type names
3. **Use UPPER_SNAKE_CASE** for constants
4. **Use kebab-case** for URLs and file names

### Variable Naming

#### Session-Related

```python
# Session identifiers
session_id: str                    # Short UUID (ABC12345)
session_uuid: UUID                 # Full UUID if needed
connection_id: str                 # WebSocket connection ID

# Session metadata
session_status: SessionStatus      # Enum value
created_at: datetime               # ISO 8601 timestamp
message_count: int                 # Number of messages
```

#### User-Related

```python
# Admin (staff member)
admin_language: str                # Always "de"
admin_connected: bool              # WebSocket connection status
admin_session_id: str              # Admin's session reference

# Customer (end-user)
customer_language: str             # ISO 639-1 code
customer_connected: bool           # WebSocket connection status
customer_session_id: str           # Customer's session reference

# Generic (when role doesn't matter)
user_type: ClientType              # admin or customer
client_type: ClientType            # API parameter name (legacy compatibility)
```

#### Message-Related

```python
# Message content
original_text: str                 # Source language text
translated_text: str               # Target language text
audio_base64: Optional[str]        # Base64 audio data
audio_url: Optional[str]           # Public audio URL

# Message metadata
message_id: str                    # Unique identifier
sender: ClientType                 # Who sent it
timestamp: datetime                # When sent
source_lang: str                   # Input language
target_lang: str                   # Output language
```

#### WebSocket-Related

```python
# Connection management
websocket_manager: WebSocketManager    # Singleton instance
websocket_connection: WebSocketConnection
connection_state: ConnectionState      # CONNECTED, DISCONNECTING, CLOSED

# Message types
message_type: MessageType              # Enum value
heartbeat_ping: Dict                   # Heartbeat message
heartbeat_pong: Dict                   # Heartbeat response
```

### Function Naming

#### Verbs for Actions

| Verb | Meaning | Example |
|------|---------|---------|
| `get_*` | Retrieve data | `get_session(session_id)` |
| `create_*` | Create new resource | `create_session()` |
| `update_*` | Modify existing | `update_session_status()` |
| `delete_*` | Remove resource | `delete_session()` |
| `validate_*` | Check validity | `validate_session_active()` |
| `connect_*` | Establish connection | `connect_websocket()` |
| `disconnect_*` | Close connection | `disconnect_websocket()` |
| `broadcast_*` | Send to multiple | `broadcast_message()` |
| `send_*` | Send to one | `send_message()` |

#### Examples

```python
# Session management
async def create_admin_session() -> Session
async def get_session(session_id: str) -> Optional[Session]
async def update_session_language(session_id: str, language: str)
async def terminate_session(session_id: str)

# WebSocket operations
async def connect_websocket(websocket: WebSocket, session_id: str, client_type: ClientType) -> str
async def disconnect_websocket(connection_id: str, reason: str)
async def broadcast_message_to_session(session_id: str, message: SessionMessage)

# Validation
def validate_session_active(session: Session) -> bool
def validate_client_type(client_type: str) -> ClientType
def validate_language_code(lang: str) -> bool
```

### Enum Naming

```python
# Enum class names: PascalCase
class ClientType(str, Enum):
    ADMIN = "admin"          # Use UPPER_CASE for enum values
    CUSTOMER = "customer"

class SessionStatus(str, Enum):
    INACTIVE = "inactive"
    PENDING = "pending"
    ACTIVE = "active"
    TERMINATED = "terminated"

class MessageType(str, Enum):
    MESSAGE = "message"
    HEARTBEAT_PING = "heartbeat_ping"
    HEARTBEAT_PONG = "heartbeat_pong"
    CONNECTION_ACK = "connection_ack"
```

---

## API Design Patterns

### Request/Response Schemas

#### Pydantic Models

```python
from pydantic import BaseModel, Field

class CreateSessionRequest(BaseModel):
    """Request to create new session"""
    # No fields - admin sessions created without parameters
    pass

class ActivateSessionRequest(BaseModel):
    """Request to activate customer session"""
    customer_language: str = Field(
        ...,
        description="Customer's preferred language (ISO 639-1 code)",
        example="en"
    )

class MessageResponse(BaseModel):
    """Unified response for message endpoints"""
    status: str = Field(..., description="Request status", example="success")
    message_id: str = Field(..., description="Unique message identifier")
    session_id: str = Field(..., description="Session identifier")
    original_text: str = Field(..., description="Original/ASR text")
    translated_text: str = Field(..., description="Translated text")
    audio_available: bool = Field(..., description="Whether audio is available")
    audio_url: Optional[str] = Field(None, description="URL to audio file")
    processing_time_ms: int = Field(..., description="Processing time in milliseconds")
    pipeline_type: str = Field(..., description="Pipeline used (audio or text)")
    source_lang: str = Field(..., description="Source language")
    target_lang: str = Field(..., description="Target language")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
```

#### Field Descriptions

✅ **Good descriptions**:
```python
session_id: str = Field(
    ...,
    description="Unique 8-character session identifier (e.g., ABC12345)",
    example="53F795DE"
)

customer_language: str = Field(
    ...,
    description="Customer's preferred language as ISO 639-1 two-letter code",
    example="en"
)
```

❌ **Bad descriptions**:
```python
id: str = Field(..., description="ID")  # Too vague
lang: str = Field(..., description="Language")  # No format specified
```

### URL Patterns

#### RESTful Conventions

```
# Sessions
POST   /api/admin/session/create          # Create new admin session
POST   /api/customer/session/activate     # Activate customer session
GET    /api/session/{session_id}          # Get session details
DELETE /api/session/{session_id}          # Terminate session

# Messages
POST   /api/session/{session_id}/message  # Send message (audio or text)
GET    /api/session/{session_id}/messages # Get message history

# WebSocket
WS     /ws/{session_id}/{client_type}     # WebSocket connection endpoint
```

#### Query Parameters

```python
# Pagination
@router.get("/api/sessions")
async def list_sessions(
    skip: int = Query(0, ge=0, description="Number of sessions to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum sessions to return")
):
    ...

# Filtering
@router.get("/api/sessions")
async def list_sessions(
    status: Optional[SessionStatus] = Query(None, description="Filter by status"),
    language: Optional[str] = Query(None, description="Filter by language")
):
    ...
```

### Error Responses

```python
class ErrorResponse(BaseModel):
    """Standard error response"""
    error_code: str = Field(..., description="Machine-readable error code")
    error_message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    timestamp: str = Field(..., description="Error timestamp (ISO 8601)")

# Usage
raise HTTPException(
    status_code=400,
    detail=ErrorResponse(
        error_code="SESSION_NOT_FOUND",
        error_message="No session found with ID: ABC12345",
        details={"session_id": "ABC12345"},
        timestamp=datetime.now().isoformat()
    ).dict()
)
```

---

## Type Safety

### Type Annotations

**Required for all public functions**:
```python
# ✅ Good: Full type annotations
async def get_session(session_id: str) -> Optional[Session]:
    ...

async def create_session() -> Session:
    ...

def validate_language(lang: str) -> bool:
    ...

# ❌ Bad: Missing annotations
async def get_session(session_id):  # No types!
    ...
```

### Complex Types

```python
from typing import List, Dict, Optional, Union, Any

# Lists
message_ids: List[str] = []
connections: List[WebSocketConnection] = []

# Dictionaries
session_data: Dict[str, Session] = {}
metadata: Dict[str, Any] = {}

# Optional
customer_language: Optional[str] = None  # May be None
audio_url: Optional[str] = None

# Union (multiple types)
identifier: Union[str, UUID]  # Can be string or UUID

# Callable
callback: Callable[[str], None]  # Function taking str, returning None
```

### Pydantic Validators

```python
from pydantic import field_validator

class MessageRequest(BaseModel):
    text: str
    language: str

    @field_validator("text")
    @classmethod
    def validate_text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Text content cannot be empty")
        return v.strip()

    @field_validator("language")
    @classmethod
    def validate_language_code(cls, v: str) -> str:
        if len(v) != 2:
            raise ValueError("Language must be ISO 639-1 two-letter code")
        return v.lower()
```

---

## Documentation Standards

### Docstring Format

Use Google-style docstrings:

```python
async def broadcast_message_to_session(
    session_id: str,
    message: SessionMessage,
    sender_type: ClientType,
    manager: WebSocketManager
) -> BroadcastResult:
    """
    Broadcast message to all session participants except sender.

    Sends differentiated content:
    - Sender receives original_text (ASR confirmation)
    - Receiver receives translated_text + audio_url

    Args:
        session_id: Unique session identifier
        message: Message to broadcast
        sender_type: Who sent the message (admin or customer)
        manager: WebSocketManager singleton instance

    Returns:
        BroadcastResult with success status and metrics

    Raises:
        ValueError: If session_id is invalid
        RuntimeError: If manager has no connections

    Example:
        >>> result = await broadcast_message_to_session(
        ...     session_id="ABC12345",
        ...     message=message,
        ...     sender_type=ClientType.admin,
        ...     manager=get_websocket_manager()
        ... )
        >>> print(f"Sent to {result.sent_count} connections")
    """
    ...
```

### API Endpoint Documentation

```python
@router.post(
    "/api/session/{session_id}/message",
    response_model=MessageResponse,
    summary="Send message in session",
    description="""
    Send an audio or text message in an active session.

    The endpoint automatically detects input type:
    - multipart/form-data → Audio pipeline (ASR → Translation → TTS)
    - application/json → Text pipeline (Translation → TTS)

    Messages are broadcast in real-time to all session participants via WebSocket.

    Rate limit: 100 requests per minute per session.
    """,
    responses={
        200: {"description": "Message processed successfully"},
        400: {"description": "Invalid request (session not active, invalid audio format)"},
        404: {"description": "Session not found"},
        429: {"description": "Rate limit exceeded"},
    },
    tags=["messaging"]
)
async def send_unified_message(...):
    ...
```

### Example Requests/Responses

Include realistic examples in OpenAPI schema:

```python
class MessageResponse(BaseModel):
    # ... fields ...

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "message_id": "msg_12345",
                "session_id": "ABC12345",
                "original_text": "Hallo, wie kann ich helfen?",
                "translated_text": "Hello, how can I help?",
                "audio_available": True,
                "audio_url": "/api/audio/msg_12345.wav",
                "processing_time_ms": 2500,
                "pipeline_type": "audio",
                "source_lang": "de",
                "target_lang": "en",
                "timestamp": "2025-09-28T14:30:00Z"
            }
        }
    )
```

---

## Migration Guide

### Updating Existing Code

#### Step 1: Search and Replace

```bash
# Find all client references (excluding technical contexts)
grep -r "client_language" services/
grep -r "client_message" services/
grep -r "client_connected" services/

# Automated replacement (review carefully!)
sed -i 's/client_language/customer_language/g' services/**/*.py
sed -i 's/client_message/customer_message/g' services/**/*.py
sed -i 's/client_connected/customer_connected/g' services/**/*.py
```

#### Step 2: Verify Changes

```bash
# Should find 0 results (all converted)
grep -r "client_language" services/

# Should find only technical contexts
grep -r "client" services/ | grep -v "customer" | grep -v "http_client" | grep -v "websocket_client"
```

#### Step 3: Update Tests

```python
# Before
def test_client_message():
    client_msg = create_client_message()
    assert client_msg.sender == "client"

# After
def test_customer_message():
    customer_msg = create_customer_message()
    assert customer_msg.sender == "customer"
```

---

## References

- [PEP 8 - Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [FastAPI Best Practices](https://fastapi.tiangolo.com/tutorial/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)

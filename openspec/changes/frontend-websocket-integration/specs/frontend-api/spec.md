# Frontend API Specification: WebSocket Integration Enhancements

## ADDED Requirements

### Requirement: Cross-Origin WebSocket Support
**ID**: REQ-WS-001
**Priority**: High
**Component**: API Gateway CORS Configuration

The API Gateway MUST support WebSocket connections from external frontend applications by implementing enhanced CORS configuration for WebSocket upgrade requests.#### Scenario: External Frontend WebSocket Connection
**Given** an external frontend application running on a different domain
**When** the frontend attempts to establish a WebSocket connection to `/ws/{session_id}/{client_type}`
**Then** the connection SHOULD succeed if the origin is in the allowed origins list
**And** the WebSocket upgrade handshake SHOULD complete successfully
**And** the connection SHOULD be registered in the WebSocket manager

#### Scenario: Development Environment Flexibility
**Given** a development environment with `ENVIRONMENT=development`
**When** a WebSocket connection is attempted from `localhost` or configured development origins
**Then** the connection SHOULD be allowed without strict domain validation
**And** all localhost ports SHOULD be automatically permitted

### Requirement: WebSocket-Specific CORS Headers
**ID**: REQ-WS-002
**Priority**: High
**Component**: CORS Middleware

The CORS middleware MUST include WebSocket-specific headers in the allowed headers and expose headers configuration.#### Scenario: WebSocket Upgrade Headers
**Given** a WebSocket upgrade request with standard WebSocket headers
**When** the request includes headers: `Upgrade`, `Connection`, `Sec-WebSocket-Key`, `Sec-WebSocket-Version`
**Then** these headers SHOULD be explicitly allowed in the CORS configuration
**And** the WebSocket upgrade SHOULD proceed without CORS rejection

#### Scenario: WebSocket Response Headers
**Given** a successful WebSocket upgrade response
**When** the server responds with WebSocket upgrade headers
**Then** headers `Upgrade`, `Connection`, `Sec-WebSocket-Accept` SHOULD be exposed to the client
**And** the client SHOULD be able to access these headers via JavaScript

### Requirement: Origin Validation for WebSocket Connections
**ID**: REQ-WS-003
**Priority**: High
**Component**: WebSocket Endpoint

WebSocket connections MUST validate the Origin header to prevent unauthorized cross-origin access.#### Scenario: Valid Origin WebSocket Connection
**Given** a WebSocket connection request with a valid Origin header
**When** the origin matches the configured allowed origins pattern
**Then** the WebSocket connection SHOULD be established
**And** the origin SHOULD be logged for monitoring purposes

#### Scenario: Invalid Origin Rejection
**Given** a WebSocket connection request with an invalid Origin header
**When** the origin does not match any allowed origins
**Then** the WebSocket connection SHOULD be rejected with code 1008
**And** the rejection reason SHOULD be "Origin not allowed"

### Requirement: WebSocket Connection Debugging
**ID**: REQ-WS-004
**Priority**: Medium
**Component**: Debug Endpoints

The API Gateway MUST provide debugging endpoints to help diagnose WebSocket connection issues.

#### Scenario: Connection Test Endpoint
**Given** a frontend developer experiencing WebSocket connection issues
**When** they send a GET request to `/api/websocket/debug/connection-test` with Origin header
**Then** the response SHOULD include origin validation status, CORS headers, and troubleshooting suggestions
**And** the response SHOULD indicate whether the origin would be allowed for WebSocket connections

#### Scenario: Connection Diagnostics
**Given** WebSocket connection failures
**When** diagnostics are requested via the debug endpoint
**Then** the response SHOULD include environment information, allowed origins, and configuration status
**And** specific error reasons SHOULD be provided for failed validations

## MODIFIED Requirements

### Requirement: CORS Configuration (Enhanced)
**ID**: REQ-API-001
**Priority**: High
**Component**: API Gateway Middleware
**Previous**: Basic CORS configuration for REST endpoints
**Modified**: Enhanced CORS configuration supporting both REST and WebSocket protocols

The CORS middleware MUST support both REST API requests and WebSocket upgrade requests with environment-specific origin policies.

#### Scenario: Environment-Based CORS Policies
**Given** different deployment environments (development, production)
**When** CORS configuration is applied
**Then** development environment SHOULD allow localhost and configured development origins
**And** production environment SHOULD only allow strict domain pattern matching
**And** the configuration SHOULD be controllable via environment variables

### Requirement: WebSocket Connection Establishment (Enhanced)
**ID**: REQ-WS-ENDPOINT-001
**Priority**: High
**Component**: WebSocket Handler
**Previous**: Basic WebSocket connection with session validation
**Modified**: Enhanced connection with explicit origin validation and detailed logging

The WebSocket endpoint MUST perform comprehensive validation including origin checking before establishing connections.

#### Scenario: Enhanced Connection Validation
**Given** a WebSocket connection request
**When** the endpoint receives the connection request
**Then** origin validation SHOULD be performed before session validation
**And** client information including origin SHOULD be stored with the connection
**And** connection establishment events SHOULD be logged with origin details

## ADDED Endpoints

### GET /api/websocket/debug/connection-test
**Purpose**: Debug WebSocket connection compatibility
**Headers**: Origin (required for testing)
**Response**:
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "origin": "https://external-app.example.com",
  "origin_allowed": true,
  "cors_headers": {
    "Access-Control-Allow-Origin": "https://external-app.example.com",
    "Access-Control-Allow-Headers": "Upgrade, Connection, Sec-WebSocket-Key",
    "Access-Control-Allow-Methods": "GET, OPTIONS"
  },
  "websocket_endpoint": "/ws/{session_id}/{client_type}",
  "environment": "production",
  "suggestions": [
    "Origin is allowed for WebSocket connections",
    "Use wss:// protocol for production connections"
  ]
}
```

### POST /api/websocket/sessions/{session_id}/polling/enable
**Purpose**: Enable polling fallback for WebSocket connection issues
**Body**: `{"client_type": "admin|customer"}`
**Response**: `{"polling_id": "uuid", "polling_interval": 2000}`

### GET /api/websocket/polling/{polling_id}/messages
**Purpose**: Retrieve messages for polling clients
**Response**: Array of queued messages in WebSocket message format

## Configuration Changes

### Environment Variables

#### DEVELOPMENT_CORS_ORIGINS
**Type**: Comma-separated string
**Purpose**: Additional origins allowed in development environment
**Example**: `"https://dev.example.com,http://localhost:3000"`
**Default**: `""`

#### ENVIRONMENT
**Type**: String
**Purpose**: Deployment environment identifier
**Values**: `"development"`, `"production"`
**Default**: `"production"`

### Docker Compose Integration
```yaml
environment:
  - ENVIRONMENT=development
  - DEVELOPMENT_CORS_ORIGINS=http://localhost:3000,https://dev-frontend.example.com
```

## Security Requirements

### Requirement: Origin-Based Access Control
**ID**: REQ-SEC-001
**Priority**: High
**Component**: Origin Validation

WebSocket connections MUST implement origin-based access control to prevent unauthorized cross-origin access.#### Scenario: Production Security
**Given** a production environment deployment
**When** WebSocket connections are attempted
**Then** only origins matching the strict production pattern SHOULD be allowed
**And** all connection attempts SHOULD be logged with origin information

#### Scenario: Development Security
**Given** a development environment
**When** WebSocket connections are attempted from localhost
**Then** localhost connections SHOULD be allowed for development convenience
**But** the same strict validation SHOULD apply to non-localhost origins

### Requirement: Connection Rate Limiting
**ID**: REQ-SEC-002
**Priority**: Medium
**Component**: Rate Limiter

WebSocket connection attempts MUST be rate-limited to prevent denial-of-service attacks.#### Scenario: Connection Attempt Rate Limiting
**Given** multiple rapid WebSocket connection attempts from the same origin
**When** the connection rate exceeds configured thresholds
**Then** subsequent connection attempts SHOULD be temporarily blocked
**And** appropriate HTTP 429 responses SHOULD be returned

## Compatibility Requirements

### Requirement: Backward Compatibility
**ID**: REQ-COMPAT-001
**Priority**: High
**Component**: Existing WebSocket Clients

All existing WebSocket functionality MUST remain unchanged for current clients.#### Scenario: Existing Client Compatibility
**Given** existing WebSocket clients using the current API
**When** the enhanced CORS configuration is deployed
**Then** all existing connections SHOULD continue to work without modification
**And** no breaking changes SHOULD be introduced to the WebSocket message format

### Requirement: Browser Compatibility
**ID**: REQ-COMPAT-002
**Priority**: High
**Component**: WebSocket Client Support

The WebSocket implementation MUST support all modern browsers with graceful fallback mechanisms.#### Scenario: Cross-Browser WebSocket Support
**Given** WebSocket connections from different browsers (Chrome, Firefox, Safari, Edge)
**When** connections are established from external origins
**Then** all supported browsers SHOULD successfully connect
**And** browser-specific WebSocket implementations SHOULD be handled transparently

## Monitoring Requirements

### Requirement: WebSocket CORS Metrics
**ID**: REQ-MON-001
**Priority**: Medium
**Component**: Metrics Collection

WebSocket connection attempts and CORS validation results MUST be tracked via metrics.#### Scenario: CORS Failure Tracking
**Given** WebSocket connection attempts with various origins
**When** CORS validation is performed
**Then** successful and failed validations SHOULD be counted by origin
**And** failure reasons SHOULD be categorized in metrics

#### Scenario: Connection Performance Tracking
**Given** WebSocket connections from different origin types
**When** connections are established
**Then** connection establishment duration SHOULD be measured
**And** metrics SHOULD distinguish between same-origin and cross-origin connections

## ADDED Requirements

### Requirement: Terminology Consistency - Admin vs Customer
The system SHALL use consistent terminology to distinguish between administrative users and end-users.

#### Scenario: Variable naming in Python code
- **GIVEN** code that handles end-user data
- **WHEN** naming variables, function parameters, or class attributes
- **THEN** the term "customer" SHALL be used (e.g., `customer_id`, `customer_message`, `customer_language`)
- **AND** the term "client" SHALL NOT be used to refer to end-users

#### Scenario: API parameter naming
- **GIVEN** an API endpoint that accepts user type
- **WHEN** defining the parameter schema
- **THEN** the parameter name SHALL be `client_type` for backward compatibility
- **AND** the documentation SHALL explicitly state it accepts values `admin` or `customer`
- **AND** the parameter description SHALL clarify "customer" refers to end-users

#### Scenario: Enum value consistency
- **GIVEN** the `ClientType` enum definition
- **WHEN** referencing enum values in code
- **THEN** `ClientType.admin` SHALL refer to administrative staff
- **AND** `ClientType.customer` SHALL refer to end-users
- **AND** no enum value SHALL use ambiguous terms like "user" or "client"

#### Scenario: Technical context exceptions
- **GIVEN** code dealing with HTTP or WebSocket client libraries
- **WHEN** naming variables or writing documentation
- **THEN** "client" MAY be used in technical contexts (e.g., `http_client`, `websocket_client`, `client_library`)
- **AND** such usage SHALL be clearly distinguished from user roles

### Requirement: API Field Naming Conventions
The system SHALL follow consistent naming conventions for all API request and response fields.

#### Scenario: Session-related fields
- **GIVEN** an API response containing session information
- **WHEN** serializing the response
- **THEN** field names SHALL use snake_case (e.g., `session_id`, `created_at`, `message_count`)
- **AND** date fields SHALL use ISO 8601 format with timezone
- **AND** language fields SHALL use ISO 639-1 two-letter codes

#### Scenario: Message-related fields
- **GIVEN** an API response containing message data
- **WHEN** serializing the message
- **THEN** original speaker input SHALL be in `original_text` field
- **AND** translated output SHALL be in `translated_text` field
- **AND** audio data SHALL be in `audio_url` or `audio_base64` field
- **AND** sender SHALL be in `sender` field with values `admin` or `customer`

#### Scenario: WebSocket message types
- **GIVEN** a WebSocket message being sent
- **WHEN** setting the message type
- **THEN** the `type` field SHALL use snake_case values from `MessageType` enum
- **AND** custom message types SHALL follow pattern `{category}_{action}` (e.g., `translation_ready`, `heartbeat_ping`)

### Requirement: Type Safety and Validation
The system SHALL enforce type safety for all user role references and API parameters.

#### Scenario: ClientType enum validation
- **GIVEN** an API endpoint receiving `client_type` parameter
- **WHEN** parsing the request
- **THEN** the parameter value SHALL be validated against `ClientType` enum
- **AND** invalid values SHALL return HTTP 400 with clear error message
- **AND** valid values (`admin`, `customer`) SHALL be case-insensitive

#### Scenario: Pydantic model field validation
- **GIVEN** a Pydantic model with `client_type` field
- **WHEN** validating request data
- **THEN** the field SHALL use `ClientType` enum as type annotation
- **AND** validation errors SHALL include allowed values in error message

### Requirement: Documentation Standards
All API endpoints and data models SHALL have comprehensive, consistent documentation.

#### Scenario: Endpoint documentation
- **GIVEN** a FastAPI route definition
- **WHEN** declaring the route
- **THEN** the route SHALL have a summary describing its purpose
- **AND** all parameters SHALL have descriptions explaining their usage
- **AND** response models SHALL be documented with field-level descriptions
- **AND** examples SHALL use realistic data matching production patterns

#### Scenario: Type annotation completeness
- **GIVEN** any public function or method
- **WHEN** defining the function signature
- **THEN** all parameters SHALL have type annotations
- **AND** the return type SHALL be explicitly annotated
- **AND** complex types SHALL use typing module generics (List, Dict, Optional)

## MODIFIED Requirements

None. This is a new specification.

## REMOVED Requirements

None. This is a new specification.

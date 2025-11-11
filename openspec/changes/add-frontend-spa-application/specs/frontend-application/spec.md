## ADDED Requirements

### Requirement: Landing Page with Optional Password Protection

The system SHALL provide a landing page that serves as the entry point for both Admin and Customer users.

#### Scenario: User accesses landing page without password protection (Option B)
- **GIVEN** the password protection is disabled in configuration
- **WHEN** user navigates to `/`
- **THEN** system displays two navigation options: "Admin" and "Kunde"
- **AND** clicking "Admin" redirects to `/admin`
- **AND** clicking "Kunde" redirects to `/customer`

#### Scenario: User accesses landing page with password protection (Option A)
- **GIVEN** the password protection is enabled (frontend-only)
- **WHEN** user navigates to `/`
- **THEN** system displays password input field
- **AND** user enters correct password "ssf2025kassel"
- **THEN** system stores authentication state in sessionStorage
- **AND** system displays navigation options "Admin" and "Kunde"

#### Scenario: User enters wrong password
- **GIVEN** password protection is enabled
- **WHEN** user enters incorrect password
- **THEN** system displays error message "Ungültiges Passwort"
- **AND** input field remains visible for retry

### Requirement: Admin Session Creation Interface

The system SHALL provide an admin interface for creating and managing translation sessions.

#### Scenario: Admin creates new session
- **GIVEN** user is on `/admin` page
- **WHEN** user clicks "Neue Session erstellen" button
- **THEN** system sends `POST /api/admin/session/create` request
- **AND** system receives session ID and join URL in response
- **AND** system displays QR code with join URL
- **AND** system displays session status as "Warte auf Kunden..."
- **AND** system enables WebSocket connection to `/ws/{sessionId}/admin`

#### Scenario: Admin monitors session activation
- **GIVEN** admin has created a session
- **WHEN** customer activates the session via `/api/customer/session/activate`
- **THEN** system receives WebSocket notification or detects status change via polling
- **AND** system updates session status to "Aktiv"
- **AND** system enables message input controls (audio and text)

#### Scenario: Admin switches to different session
- **GIVEN** admin is in an active session
- **WHEN** admin clicks "Neue Session" button
- **THEN** system navigates back to session creation view
- **AND** previous session remains active in backend (not terminated)

#### Scenario: Admin terminates active session
- **GIVEN** admin is in an active session
- **WHEN** admin clicks "Session beenden" button
- **THEN** system sends `DELETE /api/admin/session/{sessionId}/terminate` request
- **AND** system closes WebSocket connection
- **AND** system navigates back to session creation view

### Requirement: Customer Session Activation Interface

The system SHALL provide a customer interface for joining and activating translation sessions via manual session ID input or URL routing.

#### Scenario: Customer accesses customer page and enters session ID manually
- **GIVEN** admin has created session with ID "ABC12345" and shared it verbally or via text
- **WHEN** customer navigates to `/customer` page
- **THEN** system displays session ID input field with placeholder "Session-ID eingeben"
- **AND** customer types "ABC12345" into input field
- **WHEN** customer presses Enter or clicks "Weiter" button
- **THEN** system validates session ID format (8 characters, uppercase)
- **AND** system verifies session exists via backend API
- **AND** system displays language selection interface

#### Scenario: Customer enters invalid session ID format
- **GIVEN** customer is on `/customer` page with session ID input
- **WHEN** customer enters "12345" (too short) or "abcdefgh" (lowercase)
- **THEN** system displays inline validation error "Session-ID muss 8 Großbuchstaben enthalten"
- **AND** "Weiter" button remains disabled until valid format

#### Scenario: Customer enters non-existent session ID
- **GIVEN** customer enters valid format "INVALID1" that does not exist in backend
- **WHEN** system verifies session via backend
- **THEN** system receives 404 Not Found response
- **AND** system displays error message "Session nicht gefunden. Bitte überprüfen Sie die ID."
- **AND** input field remains editable for correction

#### Scenario: Customer accesses join URL with session ID (alternative flow)
- **GIVEN** admin has created session with ID "ABC12345" and shared QR code
- **WHEN** customer scans QR code and navigates to `/join/ABC12345`
- **THEN** system extracts session ID from URL parameter
- **AND** system automatically verifies session exists via backend
- **AND** system skips manual input and displays language selection interface directly

#### Scenario: Customer accesses invalid session ID
- **GIVEN** customer navigates to `/join/INVALID123` via URL or enters it manually
- **WHEN** system verifies session via backend
- **THEN** system receives 404 Not Found response
- **AND** system displays error message "Session nicht gefunden"
- **AND** system provides button to return to `/customer` page for manual input

#### Scenario: Customer selects language and activates session
- **GIVEN** customer has entered valid session ID and sees language selection
- **WHEN** customer selects "English" from dropdown (fetched from `GET /api/languages/supported`)
- **AND** customer clicks "Session starten" button
- **THEN** system sends `POST /api/customer/session/activate` with `{session_id: "ABC12345", customer_language: "en"}`
- **AND** system receives confirmation response
- **AND** system transitions to communication interface
- **AND** system enables WebSocket connection to `/ws/ABC12345/customer`
- **AND** system loads message history via `GET /api/session/ABC12345/messages`

#### Scenario: Customer returns to session selection
- **GIVEN** customer is in an active session
- **WHEN** customer clicks "Zurück" or "Neue Session" button
- **THEN** system closes WebSocket connection
- **AND** system navigates to `/customer` page with empty input field
- **AND** session remains active in backend (not terminated)

### Requirement: Unified Message Input Interface

The system SHALL provide a unified interface for sending messages via audio recording or text input.

#### Scenario: User toggles between audio and text input modes
- **GIVEN** user is in active session (admin or customer)
- **WHEN** user clicks toggle switch to select "Audio" mode
- **THEN** system displays audio recording controls (microphone button)
- **WHEN** user clicks toggle switch to select "Text" mode
- **THEN** system displays text input field with send button

#### Scenario: User sends audio message
- **GIVEN** user has selected audio input mode
- **WHEN** user presses and holds microphone button
- **THEN** system starts audio recording via WebRTC MediaRecorder API
- **WHEN** user releases microphone button after 3 seconds
- **THEN** system stops recording and converts audio to WAV format
- **AND** system immediately displays message bubble with pulsing dots ("...")
- **AND** system sends `POST /api/session/{sessionId}/message` with multipart/form-data payload
- **WHEN** backend responds with processed message
- **THEN** system receives WebSocket `receiver_message` notification
- **AND** system replaces pulsing bubble with final translated message
- **AND** system displays audio player with TTS output

#### Scenario: User sends text message
- **GIVEN** user has selected text input mode
- **WHEN** user types "Hello, I need help" in text field
- **AND** user clicks send button
- **THEN** system immediately displays message bubble with pulsing dots ("...")
- **AND** system sends `POST /api/session/{sessionId}/message` with JSON payload `{text: "Hello, I need help"}`
- **WHEN** backend responds with processed message
- **THEN** system receives WebSocket `receiver_message` notification
- **AND** system replaces pulsing bubble with final translated message
- **AND** system displays audio player with TTS output

#### Scenario: User tries to send message before session is active
- **GIVEN** admin has created session but customer has not joined yet
- **WHEN** admin attempts to send message
- **THEN** system displays error "Session noch nicht aktiv"
- **AND** input controls remain disabled

### Requirement: Real-time Message Updates via WebSocket

The system SHALL provide real-time bidirectional message updates using WebSocket connections with automatic fallback to HTTP polling.

#### Scenario: System establishes WebSocket connection on session activation
- **GIVEN** user (admin or customer) has activated session
- **WHEN** communication interface loads
- **THEN** system connects to `wss://ssf.smart-village.solutions/ws/{sessionId}/{clientType}`
- **AND** system verifies connection is established (readyState === OPEN)
- **AND** system displays connection status indicator (green dot)

#### Scenario: System receives sender confirmation via WebSocket
- **GIVEN** admin sends message "Guten Tag"
- **WHEN** backend processes message and broadcasts WebSocket notifications
- **THEN** admin's frontend receives message with `role: "sender_confirmation"`
- **AND** system displays ASR-recognized text "Guten Tag" in admin's message bubble
- **AND** message bubble transitions from pulsing to confirmed state

#### Scenario: System receives receiver message via WebSocket
- **GIVEN** admin sends message "Guten Tag"
- **WHEN** backend processes message and broadcasts WebSocket notifications
- **THEN** customer's frontend receives message with `role: "receiver_message"`
- **AND** system displays translated text "Good day" in customer's message bubble
- **AND** system automatically plays TTS audio from `audio_url` field without requiring user interaction (after initial user gesture)
- **AND** system displays all pipeline metadata (processing time, languages, steps)

#### Scenario: WebSocket connection fails and system activates polling fallback
- **GIVEN** user attempts to establish WebSocket connection
- **WHEN** connection fails (CORS issue, network problem, or firewall block)
- **THEN** system receives WebSocket error event
- **AND** system activates HTTP polling mode via `GET /api/websocket/poll/{polling_id}`
- **AND** system polls every 2 seconds for new messages
- **AND** system displays connection status indicator (yellow dot with "Fallback-Modus")

#### Scenario: System handles session termination via WebSocket
- **GIVEN** user is in active session with WebSocket connection
- **WHEN** other party terminates session via API
- **THEN** system receives WebSocket message with `type: "session_terminated"`
- **AND** system closes WebSocket connection
- **AND** system displays notification "Session wurde beendet"
- **AND** system navigates user back to start page (admin: `/admin`, customer: `/customer`)

### Requirement: Message Bubble Display with Pipeline Metadata

The system SHALL display messages in conversation bubbles with visual differentiation between sender and receiver, including detailed pipeline processing metadata.

#### Scenario: System displays sender's message bubble (optimistic UI)
- **GIVEN** user sends message (audio or text)
- **WHEN** message is submitted to backend
- **THEN** system immediately displays bubble on sender's side with pulsing dots indicator
- **AND** bubble is styled as "outgoing" (right-aligned, blue background)
- **WHEN** sender confirmation is received via WebSocket
- **THEN** system replaces pulsing dots with actual message content
- **AND** bubble displays ASR-recognized or entered text

#### Scenario: System displays receiver's message bubble with metadata
- **GIVEN** receiver's frontend receives `receiver_message` via WebSocket
- **WHEN** message data includes `translation`, `audio_url`, and `pipeline_metadata`
- **THEN** system displays bubble on receiver's side (left-aligned, gray background)
- **AND** bubble shows translated text prominently
- **AND** bubble includes collapsible metadata section showing:
  - Processing time (e.g., "2.3s")
  - Source language (e.g., "Deutsch")
  - Target language (e.g., "English")
  - Pipeline steps (ASR → Translation → TTS) with individual timings
- **AND** bubble includes audio player controls for TTS output
- **AND** system auto-plays audio (if user interaction has occurred previously)

#### Scenario: User expands pipeline metadata details
- **GIVEN** message bubble is displayed with collapsed metadata
- **WHEN** user clicks "Details anzeigen" button
- **THEN** system expands metadata section to show complete `pipeline_metadata` structure:
  - Input type (audio vs text)
  - ASR confidence score (if applicable)
  - Translation model used
  - TTS model used
  - Individual step durations
  - Total processing time

#### Scenario: System displays message history on session load
- **GIVEN** user joins active session that already has message history
- **WHEN** communication interface loads
- **THEN** system fetches messages via `GET /api/session/{sessionId}/messages`
- **AND** system renders all previous messages in chronological order
- **AND** system differentiates between own messages (right-aligned) and partner messages (left-aligned)
- **AND** system scrolls to most recent message
- **AND** system does NOT auto-play audio for historical messages (only live messages)

### Requirement: Responsive Design and Mobile Optimization

The system SHALL provide a fully responsive interface optimized for mobile devices and tablets.

#### Scenario: User accesses interface on mobile device
- **GIVEN** user opens application on smartphone (viewport width < 768px)
- **WHEN** any page renders
- **THEN** system adapts layout to single-column mobile view
- **AND** navigation buttons are touch-friendly (min. 44px tap targets)
- **AND** text input fields use appropriate mobile keyboards (type="text", type="email")
- **AND** audio recording uses native mobile controls where available

#### Scenario: User switches device orientation
- **GIVEN** user is using tablet or smartphone
- **WHEN** user rotates device from portrait to landscape
- **THEN** system re-renders layout to optimize horizontal space
- **AND** message bubbles remain readable without horizontal scrolling
- **AND** input controls remain accessible at bottom of viewport

### Requirement: Error Handling and User Feedback

The system SHALL provide clear error messages and visual feedback for all user actions and system states.

#### Scenario: API request fails due to network error
- **GIVEN** user sends message or triggers API call
- **WHEN** network request fails (timeout, no connection, 5xx error)
- **THEN** system displays toast notification with error message
- **AND** system keeps pulsing bubble visible with retry button
- **WHEN** user clicks retry button
- **THEN** system re-sends original request

#### Scenario: Session becomes inactive during communication
- **GIVEN** user is in active session
- **WHEN** session timeout occurs in backend (30min inactivity)
- **THEN** system receives `SESSION_NOT_ACTIVE` error from message endpoint
- **OR** system receives `session_terminated` WebSocket notification
- **THEN** system disables input controls
- **AND** system displays persistent notification "Session ist abgelaufen"
- **AND** system provides button to return to start page

#### Scenario: Audio recording permission is denied
- **GIVEN** user selects audio input mode
- **WHEN** user clicks microphone button
- **AND** browser requests microphone permission
- **AND** user denies permission
- **THEN** system displays error message "Mikrofon-Zugriff verweigert"
- **AND** system automatically switches to text input mode

### Requirement: Docker Build and Deployment

The system SHALL be containerized with Docker and integrate seamlessly with the existing docker-compose setup.

#### Scenario: Development build with hot-reload
- **GIVEN** developer runs `docker compose up frontend`
- **WHEN** container starts in development mode
- **THEN** system mounts source code as volume
- **AND** Vite dev server runs with hot-module-replacement
- **AND** application is accessible at `http://localhost:5173`
- **AND** API calls are proxied to `http://api_gateway:8000`

#### Scenario: Production build with Nginx
- **GIVEN** production Dockerfile builds application
- **WHEN** `npm run build` executes
- **THEN** system generates optimized static files in `/dist`
- **AND** Nginx serves static files from `/usr/share/nginx/html`
- **AND** Nginx reverse-proxies `/api/*` requests to backend
- **AND** application is accessible via Traefik at `https://translate.smart-village.solutions`

#### Scenario: Container health check passes
- **GIVEN** frontend container is running
- **WHEN** Docker health check executes `curl -f http://localhost:5173`
- **THEN** Nginx returns HTTP 200 OK with index.html
- **AND** Docker marks container as healthy

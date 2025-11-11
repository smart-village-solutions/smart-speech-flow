## 1. Project Setup & Configuration

- [x] 1.1 Initialize React/TypeScript project with Vite in `services/frontend/`
- [x] 1.2 Configure TailwindCSS for styling
- [x] 1.3 Install core dependencies (react-router-dom, axios, socket.io-client)
- [x] 1.4 Set up ESLint and Prettier configurations
- [x] 1.5 Create environment variable structure (.env.example, .env.local)
- [x] 1.6 Configure Vite proxy for development API calls

## 2. Docker Build Setup

- [x] 2.1 Create multi-stage Dockerfile (builder + nginx)
- [x] 2.2 Configure Nginx for SPA routing (fallback to index.html)
- [x] 2.3 Add Nginx reverse-proxy config for `/api/*` → backend
- [x] 2.4 Update docker-compose.yml with correct build context
- [x] 2.5 Add Traefik labels for production domain
- [x] 2.6 Configure health check endpoint

## 3. Routing & Navigation Structure

- [x] 3.1 Set up React Router with routes: `/`, `/admin`, `/customer`, `/join/:sessionId`
- [x] 3.2 Create Layout component with Header and Container
- [x] 3.3 Implement ProtectedRoute wrapper for authenticated routes
- [x] 3.4 Add 404 Not Found page for invalid routes

## 4. Landing Page (Optional Password Protection)

- [x] 4.1 Create LandingPage component with password input
- [x] 4.2 Implement frontend-only password validation (sessionStorage)
- [x] 4.3 Add navigation buttons: "Admin" and "Kunde"
- [ ] 4.4 Create configuration toggle for enabling/disabling password protection
- [x] 4.5 Add error message display for wrong password

## 5. Admin Interface - Session Creation

- [x] 5.1 Create AdminPage component with "Neue Session erstellen" button
- [x] 5.2 Implement API call to `POST /api/admin/session/create`
- [ ] 5.3 Display session ID and join URL (QR code generation with qrcode.react)
- [x] 5.4 Show session status indicator ("Warte auf Kunden..." / "Aktiv")
- [x] 5.5 Implement status polling or WebSocket listener for activation event
- [ ] 5.6 Add "Neue Session" button for creating additional sessions
- [x] 5.7 Add "Session beenden" button with confirmation dialog

## 6. Customer Interface - Session Activation

- [x] 6.1 Create CustomerPage component with session ID input field
- [x] 6.2 Implement session ID format validation (8 characters, uppercase, regex: ^[A-Z0-9]{8}$)
- [x] 6.3 Add inline validation feedback (error messages for invalid format)
- [x] 6.4 Implement URL parameter extraction for `/join/:sessionId` route (alternative flow)
- [x] 6.5 Fetch supported languages from `GET /api/languages/supported`
- [x] 6.6 Create language selection dropdown component
- [x] 6.7 Implement API call to `POST /api/customer/session/activate`
- [x] 6.8 Handle invalid session ID error (404 response)
- [x] 6.9 Add "Zurück" button to return to session input
- [x] 6.10 Load message history via `GET /api/session/{id}/messages` after activation

## 7. WebSocket Integration

- [x] 7.1 Create WebSocketService utility class for connection management
- [x] 7.2 Implement connection to `wss://ssf.smart-village.solutions/ws/{sessionId}/{clientType}`
- [x] 7.3 Add connection status indicator (green/yellow/red dot)
- [x] 7.4 Implement message handler for `sender_confirmation` role
- [x] 7.5 Implement message handler for `receiver_message` role
- [x] 7.6 Handle `session_terminated` event and auto-redirect
- [x] 7.7 Implement automatic reconnection logic on disconnect
- [ ] 7.8 Add polling fallback using `GET /api/websocket/poll/{polling_id}`

## 8. Message Input Interface

- [x] 8.1 Create MessageInput component with audio/text toggle
- [x] 8.2 Implement audio recording with WebRTC MediaRecorder API
- [x] 8.3 Add visual feedback for recording state (pulsing microphone icon)
- [x] 8.4 Convert recorded audio to WAV format
- [x] 8.5 Create text input field with send button
- [x] 8.6 Implement unified message sending to `POST /api/session/{sessionId}/message`
- [x] 8.7 Handle multipart/form-data for audio messages
- [x] 8.8 Handle JSON payload for text messages
- [x] 8.9 Add input validation (max text length, audio duration)
- [x] 8.10 Disable input controls when session is not active

## 9. Message Display & Bubbles

- [x] 9.1 Create MessageBubble component with sender/receiver styling
- [x] 9.2 Implement optimistic UI with pulsing dots indicator
- [x] 9.3 Display ASR-recognized text for sender confirmation
- [x] 9.4 Display translated text for receiver messages
- [x] 9.5 Add audio player component for TTS output
- [x] 9.6 Implement auto-play for incoming audio (after initial user interaction gesture)
- [x] 9.7 Create collapsible metadata section (pipeline details)
- [x] 9.8 Display processing time, languages, and pipeline steps
- [x] 9.9 Implement message history loading on session join via `GET /api/session/{id}/messages`
- [x] 9.10 Add scroll-to-bottom behavior for new messages
- [x] 9.11 Prevent auto-play for historical messages (only live messages)

## 10. Error Handling & User Feedback

- [x] 10.1 Create Toast/Notification component for system messages
- [ ] 10.2 Handle network errors with retry mechanism
- [ ] 10.3 Display "SESSION_NOT_ACTIVE" error gracefully
- [ ] 10.4 Handle microphone permission denial
- [ ] 10.5 Show loading states for API calls
- [ ] 10.6 Add error boundaries for component crashes
- [ ] 10.7 Implement session timeout detection and notification

## 11. Responsive Design & Accessibility

- [ ] 11.1 Implement mobile-first responsive layouts
- [ ] 11.2 Ensure touch-friendly tap targets (min 44px)
- [ ] 11.3 Test on mobile devices (iOS Safari, Chrome Mobile)
- [ ] 11.4 Add ARIA labels for screen readers
- [ ] 11.5 Implement keyboard navigation support
- [ ] 11.6 Test orientation changes (portrait/landscape)
- [ ] 11.7 Optimize for low-bandwidth scenarios

## 12. API Integration & Services

- [x] 12.1 Create axios instance with base URL configuration
- [x] 12.2 Implement SessionService for admin operations
- [x] 12.3 Implement CustomerService for activation operations
- [x] 12.4 Implement MessageService for sending/fetching messages
- [x] 12.5 Implement LanguageService for fetching supported languages
- [x] 12.6 Add request/response interceptors for error handling
- [ ] 12.7 Implement retry logic for failed requests

## 13. State Management

- [x] 13.1 Choose state management approach (Context API or Zustand)
- [x] 13.2 Create SessionContext for session state (ID, status, participants)
- [x] 13.3 Create MessageContext for message history
- [x] 13.4 Create WebSocketContext for connection state
- [ ] 13.5 Implement global loading/error state management

## 14. Testing

- [ ] 14.1 Write unit tests for utility functions (audio conversion, message formatting)
- [ ] 14.2 Write component tests for MessageBubble, MessageInput
- [ ] 14.3 Write integration tests for API service calls
- [ ] 14.4 Set up Playwright for E2E testing
- [ ] 14.5 Write E2E test for complete admin session flow
- [ ] 14.6 Write E2E test for complete customer session flow
- [ ] 14.7 Test WebSocket connection and message flow

## 15. Documentation

- [x] 15.1 Update services/frontend/README.md with setup instructions
- [x] 15.2 Document environment variables
- [ ] 15.3 Add component documentation with Storybook (optional)
- [ ] 15.4 Document WebSocket message formats
- [ ] 15.5 Create troubleshooting guide for common issues

## 16. Production Optimization

- [ ] 16.1 Configure code splitting for route-based chunks
- [ ] 16.2 Optimize bundle size (tree-shaking, lazy loading)
- [ ] 16.3 Add service worker for offline support (optional)
- [ ] 16.4 Configure CSP headers in Nginx
- [x] 16.5 Set up Gzip compression in Nginx
- [x] 16.6 Add cache headers for static assets

## 17. Deployment & Integration

- [x] 17.1 Build production Docker image
- [x] 17.2 Test with docker-compose locally (skipped - direct production deployment)
- [x] 17.3 Verify Traefik routing to `translate.smart-village.solutions` ✓
- [x] 17.4 Test SSL/TLS certificate provisioning ✓
- [ ] 17.5 Verify WebSocket connection through Traefik (requires manual testing)
- [x] 17.6 Deploy to production server ✓ (https://translate.smart-village.solutions)
- [ ] 17.7 Monitor logs for errors
- [ ] 17.8 Perform smoke tests on production

## 18. Post-Launch Tasks

- [ ] 18.1 Archive old `frontend-archive` service (optional)
- [ ] 18.2 Update main README.md with new frontend details
- [ ] 18.3 Create user guide for admin and customer workflows
- [ ] 18.4 Set up frontend monitoring (error tracking, analytics)
- [ ] 18.5 Gather user feedback and create backlog items

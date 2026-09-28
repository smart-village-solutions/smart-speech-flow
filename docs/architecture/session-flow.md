# Session Lifecycle Overview

This document summarizes the actual session logic implemented in the backend so the frontend can align with it.

## 1. Admin session creation

- Endpoint: `POST /api/admin/session/create`
- Effect: creates a new pending session with an auto generated 8-char ID, under the tenant of the admin's signed token.
- Response includes the session ID and a shareable join URL.
- By default a tenant has one active session at a time: creating a session ends that tenant's previous one. `SSF_ALLOW_PARALLEL_SESSIONS=true` allows parallel sessions.

## 2. Pending state

- New sessions start with status `pending`.
- They become `active` when the customer joins; there is no automatic transition.
- Frontend should poll `GET /api/admin/session/current?session_id=…` or `GET /api/admin/session/{session_id}/status` to observe status.

## 3. Customer activation

- REST endpoint: `POST /api/customer/session/activate`.
- No automatic transition happens when a customer opens a WebSocket connection or sends a message.
- Customer activation workflow:
  1. Customer scans QR code and selects language
  2. Frontend calls `POST /api/customer/session/activate` with `session_id` and `customer_language`
  3. Session transitions from `pending` to `active`
  4. Messaging becomes available for both admin and customer

## 4. Active state & messaging

- `POST /api/admin/session/{session_id}/message` and `POST /api/customer/session/{session_id}/message` work only while the session status is `active`; otherwise the request fails with `SESSION_NOT_ACTIVE`.
- Audio payloads use multipart/form-data, text payloads use application/json.
- Once accepted, `ConversationService` stores the message and its differentiated broadcast pushes the sender and receiver views to the session's sockets and pollers.

## 5. WebSocket behaviour

- Endpoints: `ws://…/ws/admin/{session_id}?ticket=…` and `ws://…/ws/customer/{session_id}` (no `/api` prefix), defined in `services/api_gateway/websocket.py`.
- The admin socket needs a single-use ticket from `POST /api/admin/session/{session_id}/realtime-ticket`.
- Connecting does **not** activate the session; it merely registers the socket so broadcasts can reach the client once the session is active.
- A client that cannot keep a socket open uses the polling fallback below `/api/{admin|customer}/session/{session_id}/polling`. See `websocket-architecture.md`.

## 6. Termination

- Sessions can transition to `terminated` via:
  - Admin endpoint `DELETE /api/admin/session/{session_id}/terminate`.
  - Automatic timeout: the lifespan's session-timeout task ends a session after the admin's reconnect grace or at its maximum lifetime.
  - A new admin session for the same tenant, unless parallel sessions are allowed.
- Terminated sessions show status `terminated`; re-connecting WebSockets should be prevented.

## 7. Fetching session info

- Admin endpoints:
  - `GET /api/admin/session/current?session_id=…` – returns status/details for a specific session.
  - `GET /api/admin/session/{session_id}/status` – the session's status.
  - `GET /api/admin/session/history` – lists terminated sessions and active sessions.
- Customer endpoint: `GET /api/customer/session/{session_id}` – returns the session's status, language and connection state.

## 8. Frontend responsibilities

### Admin Frontend:
- Create sessions via `POST /api/admin/session/create`
- Poll `GET /api/admin/session/current?session_id=...` until the backend reports `active`
- Provide manual termination controls via `DELETE /api/admin/session/{id}/terminate`

### Customer Frontend:
- After language selection, call `POST /api/customer/session/activate` to activate the session
- Use `GET /api/customer/session/{id}` to check session state
- Only allow sending messages once `can_send_messages` is `true`

### Both Frontends:
- Connect sockets to `/ws/admin/{session_id}` or `/ws/customer/{session_id}` for realtime updates and handle disconnects/termination events
- Handle `SESSION_NOT_ACTIVE` errors gracefully if they occur

# Session Lifecycle Overview

This document summarizes the actual session logic implemented in the backend so the frontend can align with it.

## 1. Admin session creation

- Endpoint: `POST /api/admin/session/create`
- Effect: creates a new pending session with an auto generated 8-char ID.
- Response includes the session ID and a shareable join URL.
- Existing sessions remain active; multiple concurrent sessions are possible.

## 2. Pending state

- New sessions start with status `pending`.
- They become `active` when the customer joins; there is no automatic transition.
- Frontend should poll `GET /api/admin/session/current?session_id=…` or `GET /api/session/{id}` (when available) to observe status.

## 3. Customer activation

- ✅ **NEW:** REST endpoint `POST /api/customer/session/activate` is now available.
- No automatic transition happens when a customer opens a WebSocket connection or sends a message.
- Customer activation workflow:
  1. Customer scans QR code and selects language
  2. Frontend calls `POST /api/customer/session/activate` with `session_id` and `customer_language`
  3. Session transitions from `pending` to `active`
  4. Messaging becomes available for both admin and customer

## 4. Active state & messaging

- `POST /api/session/{session_id}/message` works only while the session status is `active`; otherwise the request fails with `SESSION_NOT_ACTIVE`.
- Audio payloads use multipart/form-data, text payloads use application/json.
- Once accepted, the message is stored and `WebSocketManager.broadcast_with_differentiated_content` pushes sender/receiver views.

## 5. WebSocket behaviour

- Primary endpoint: `ws://…/ws/{session_id}/{client_type}` (no `/api` prefix) defined in `services/api_gateway/websocket.py`.
- The legacy `/api/ws/…` endpoint that lives in `routes/session.py` is a heartbeat stub and does **not** integrate with the WebSocket manager.
- Connecting does **not** activate the session; it merely registers the socket so broadcasts can reach the client once the session is active.
- WebSocket stats/polling helpers live under `/api/websocket/*` (see `websocket.py`).

## 6. Termination

- Sessions can transition to `terminated` via:
  - Admin endpoint `DELETE /api/admin/session/{session_id}/terminate`.
  - Automatic timeout (SessionManager's inactivity timer).
  - Manual cleanup via `terminate_all_active_sessions` helper.
- Terminated sessions show status `terminated`; re-connecting WebSockets should be prevented.

## 7. Fetching session info

- Admin endpoints:
  - `GET /api/admin/session/current?session_id=…` – returns status/details for a specific session.
  - `GET /api/admin/session/history` – lists terminated sessions and active sessions.
- General endpoint: `GET /api/session/{session_id}` – returns session data (status, participants).

## 8. Frontend responsibilities

### Admin Frontend:
- Create sessions via `POST /api/admin/session/create`
- Poll `GET /api/admin/session/current?session_id=...` until the backend reports `active`
- Provide manual termination controls via `DELETE /api/admin/session/{id}/terminate`

### Customer Frontend:
- After language selection, call `POST /api/customer/session/activate` to activate the session
- Use `GET /api/customer/session/{id}/status` to check session state
- Only allow sending messages once `can_send_messages` is `true`

### Both Frontends:
- Connect sockets to `/ws/{session_id}/{client_type}` for realtime updates and handle disconnects/termination events
- Handle `SESSION_NOT_ACTIVE` errors gracefully if they occur
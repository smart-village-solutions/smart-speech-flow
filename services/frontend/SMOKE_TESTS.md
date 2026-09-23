# Frontend Smoke Tests

Run these after every frontend or gateway deployment. The production frontend
is served at `https://dialog.kassel.de` and the API at
`https://ssf.smart-village.solutions`.

Staff screens are in German; each step names the English label with the German
one in brackets. Customer screens follow the language the customer picks.

## Automated checks

Run from the repository root on the production host. A bare `docker compose`
there targets the development stack, so use the production helper:

```bash
source scripts/lib/production-common.sh

# Frontend and its health endpoint
curl -sI https://dialog.kassel.de | head -1          # HTTP/2 200
curl -s https://dialog.kassel.de/health              # healthy

# Gateway language list
curl -s https://ssf.smart-village.solutions/api/languages/supported | jq '.languages | keys'

# Administrative API refuses anything but a bearer token (both print 401)
curl -s -o /dev/null -w '%{http_code}\n' \
  https://ssf.smart-village.solutions/api/admin/session/history
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-SSF-Legacy-Access: any' \
  https://ssf.smart-village.solutions/api/admin/session/history

# Containers
production_compose ps frontend api_gateway
production_compose logs --since 10m frontend api_gateway | grep -iE "error|exception"
```

## Manual checks

Use two browsers, or one normal and one private window: one for staff, one for
the customer. Keep the browser console (F12) open on both.

### 1. Entry points

1. Open `https://dialog.kassel.de`. The "Enter code" (Code eingeben) screen
   appears, with an "Admin login" (Admin-Login) link.
2. Open `https://dialog.kassel.de/admin`. The not-found page appears; there is
   no password form.
3. Open `https://dialog.kassel.de/customer`. The not-found page appears.

### 2. Staff login

1. Follow "Admin login", or open `https://dialog.kassel.de/login`.
2. The organisation list appears in alphabetical order. Pick one.
3. Sign in with a Keycloak account that has the `ssf-user` role.
4. The dashboard shows "Start a new conversation" (Neues Gespräch starten),
   the system load card and "Past conversations" (Vergangene Gespräche).

A user without `ssf-user` must not reach the dashboard.

### 3. Start a conversation

1. Click "Start a new conversation". If a conversation is still running, a
   dialog asks to end it; confirm with "Start anyway" (Trotzdem starten).
2. The invite shows an eight-character session code, "Copy link"
   (Link kopieren) and "QR code" (QR-Code). The link has the form
   `https://dialog.kassel.de/join/<code>`.
3. Click "Go to the conversation" (Zum Gespräch wechseln). The conversation
   screen names the session code and shows "Connected" (Verbunden).

### 4. Customer joins

Do each variant with a fresh conversation at least once per release:

- **QR code or link:** scan the QR code, or open the copied link, in the
  customer browser. It lands directly on "Choose your language".
- **Code:** open `https://dialog.kassel.de`, enter the eight-character code on
  "Enter code" and press "Continue".

Then:

1. Choose a language, for example Arabic.
2. The information screen explains recording and data retention. Leave the
   storage checkbox as it is and press "Get started".
3. The customer conversation screen opens. On the staff side the conversation
   shows the chosen language.

An unknown code shows "That code does not match an open session."

### 5. Messages

1. **Staff, text:** open the keyboard, send "Hallo, willkommen!". The customer
   receives the translation with a playable audio reply.
2. **Customer, voice:** press "Record", allow the microphone, speak for a few
   seconds, then "Send recording". Staff receive the German translation and
   audio.
3. **Customer, text:** send a short text; staff receive the translation.

Microphone access works over HTTPS only. If it is declined, the customer sees
a hint to type instead.

### 6. Reconnect

1. Reload the customer browser during a conversation. It returns to the same
   conversation and the message history is still there.
2. Take the staff browser offline for a few seconds (DevTools → Network →
   Offline), then back online. The status shows "Connection interrupted"
   (Verbindung unterbrochen), then "Connected" again, and new messages arrive.

### 7. End the conversation

1. On the staff conversation screen, click "End conversation"
   (Gespräch beenden) and confirm with "End it" (Beenden).
2. Staff return to the dashboard; the conversation appears as completed under
   "Past conversations".
3. The customer sees "This conversation has ended."

### 8. Sign out

1. Open "User account" (Benutzerkonto) and choose "Sign out" (Abmelden).
2. The organisation list appears. Picking the organisation again asks for
   Keycloak credentials unless the Keycloak session is still valid.

## Pass criteria

- Every automated check prints the expected value.
- `/admin` and `/customer` show the not-found page; staff can only sign in
  through `/login`.
- Staff can start, enter, and end a conversation.
- A customer can join by QR code, link, and code, and both sides exchange
  translated text and voice messages.
- The browser consoles show no CORS or JavaScript errors, and the logs show no
  unexpected errors.

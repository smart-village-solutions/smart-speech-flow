# Customer API Endpoints

This document describes the new customer-facing endpoints for session activation.

## POST /api/customer/session/activate

Activates a pending session when a customer joins.

### Request

```json
{
  "session_id": "ABC12345",
  "customer_language": "en"
}
```

### Response (Success - 200)

```json
{
  "session_id": "ABC12345",
  "status": "active",
  "customer_language": "en",
  "message": "Session ABC12345 wurde erfolgreich aktiviert",
  "timestamp": "2025-11-03T10:30:00Z"
}
```

### Response (Idempotent - 200)

If session is already active:

```json
{
  "session_id": "ABC12345",
  "status": "active",
  "customer_language": "en",
  "message": "Session ABC12345 ist bereits aktiv",
  "timestamp": "2025-11-03T10:30:00Z"
}
```

### Response (Error - 404)

```json
{
  "detail": "Session ABC12345 nicht gefunden oder abgelaufen"
}
```

### Response (Error - 400)

```json
{
  "detail": "Session ABC12345 wurde bereits beendet und kann nicht aktiviert werden"
}
```

## GET /api/customer/session/{session_id}/status

Gets session status from customer perspective.

### Response (200)

```json
{
  "session_id": "ABC12345",
  "status": "active",
  "customer_language": "en",
  "admin_connected": true,
  "customer_connected": false,
  "is_active": true,
  "can_send_messages": true,
  "created_at": "2025-11-03T10:25:00Z"
}
```

### Key Fields

- `is_active`: `true` if session status is "active"
- `can_send_messages`: `true` if messaging is enabled (same as `is_active`)
- `customer_language`: Language selected during activation

## GET /api/customer/languages/supported

Returns supported languages for customer interface.

### Response (200)

```json
{
  "languages": {
    "de": {"name": "Deutsch", "native": "Deutsch"},
    "en": {"name": "English", "native": "English"},
    "ar": {"name": "Arabic", "native": "العربية"},
    "tr": {"name": "Turkish", "native": "Türkçe"},
    "ru": {"name": "Russian", "native": "Русский"},
    "uk": {"name": "Ukrainian", "native": "Українська"},
    "am": {"name": "Amharic", "native": "አማርኛ"},
    "ti": {"name": "Tigrinya", "native": "ትግርኛ"},
    "ku": {"name": "Kurdish", "native": "Kurmancî"},
    "fa": {"name": "Persian", "native": "فارسی"}
  },
  "admin_default": "de",
  "popular": ["en", "ar", "tr", "ru", "fa"]
}
```

## Usage Workflow

### 1. Customer joins session

```typescript
// After QR code scan and language selection
const activateResponse = await fetch('/api/customer/session/activate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: sessionId,
    customer_language: selectedLanguage.code
  })
});

if (activateResponse.ok) {
  console.log('✅ Session activated successfully');
  // Proceed to messaging interface
} else {
  console.error('❌ Failed to activate session');
  // Handle error
}
```

### 2. Check session status

```typescript
const statusResponse = await fetch(`/api/customer/session/${sessionId}/status`);
const status = await statusResponse.json();

if (status.can_send_messages) {
  // Enable messaging UI
} else {
  // Show waiting state
}
```

### 3. Frontend Integration Points

- **Language Selection**: Use `/api/customer/languages/supported` to populate language picker
- **Session Activation**: Call `/api/customer/session/activate` after language selection
- **Status Polling**: Use `/api/customer/session/{id}/status` to monitor session state
- **Error Handling**: Handle 404 (session not found) and 400 (already terminated) appropriately

## Error Handling

### Common Error Patterns

```typescript
try {
  const response = await fetch('/api/customer/session/activate', { ... });

  if (!response.ok) {
    const error = await response.json();

    switch (response.status) {
      case 404:
        // Session expired or invalid QR code
        showError('Session nicht gefunden. Bitte neuen QR-Code scannen.');
        break;
      case 400:
        // Session already terminated
        showError('Session bereits beendet. Bitte Admin kontaktieren.');
        break;
      default:
        showError('Unbekannter Fehler beim Beitreten zur Session.');
    }
  }
} catch (networkError) {
  showError('Netzwerkfehler. Bitte Verbindung prüfen.');
}
```

## Testing

Run customer endpoint tests:

```bash
cd /root/projects/ssf-backend
python3 -m pytest services/api_gateway/tests/test_customer.py -v
```

All tests should pass, covering:
- ✅ Successful activation
- ✅ Session not found (404)
- ✅ Idempotent activation
- ✅ Terminated session handling (400)
- ✅ Status retrieval
- ✅ Supported languages
- ✅ Unsupported language warning
- ✅ Message enablement after activation

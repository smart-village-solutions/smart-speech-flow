# WebSocket Test Page - Kritische Fixes & Verbesserungen

**Datum:** 2025-11-05
**Priorität:** 🔴 HIGH
**Betrifft:** `WebSocketTestPage.tsx`
**Status:** 4 kritische Bugs identifiziert

---

## 🐛 Kritische Bugs (MUST FIX)

### Bug 1: Scope-Problem bei `sendCustomerMessage()` ❌

**Problem:**
```typescript
// ❌ FEHLER: Funktion außerhalb des Scopes
multiWebSocketManager.onMessage('customer', (msg) => {
  if (!adminMessageReceivedRef.current) {
    setTimeout(() => sendCustomerMessage(), 1000); // ReferenceError!
  }
});

// Funktion wird SPÄTER definiert
const sendCustomerMessage = async () => { /* ... */ };
```

**Fix Option A - Funktion vorher definieren:**
```typescript
const runTest = async () => {
  // ✅ Definiere ALLE Funktionen zuerst
  const sendAdminMessage = async () => {
    updateStep('5', 'running');
    updateStep('6', 'running');
    const adminText = 'Hallo, ich bin der Admin!';
    const response = await apiService.sendTextMessage(
      session.session_id, adminText, 'de', 'en', 'admin'
    );
    const msg: TestMessage = {
      id: response.message_id,
      sender: 'admin',
      text: response.original_text,
      timestamp: new Date(),
      received: false
    };
    setMessages(prev => [...prev, msg]);
    updateStep('5', 'success', `"${adminText}"`);
  };

  const sendCustomerMessage = async () => {
    updateStep('7', 'running');
    updateStep('8', 'running');
    const customerText = 'Hello, I am the customer!';
    const response = await apiService.sendTextMessage(
      session.session_id, customerText, 'en', 'de', 'customer'
    );
    const msg: TestMessage = {
      id: response.message_id,
      sender: 'customer',
      text: response.original_text,
      timestamp: new Date(),
      received: false
    };
    setMessages(prev => [...prev, msg]);
    updateStep('7', 'success', `"${customerText}"`);
  };

  // ✅ JETZT kann der Handler die Funktion aufrufen
  multiWebSocketManager.onMessage('customer', (msg) => {
    if (!adminMessageReceivedRef.current) {
      adminMessageReceivedRef.current = true;
      updateStep('6', 'success', `"${msg.text}"`);
      setTimeout(() => sendCustomerMessage(), 1000); // ✅ Funktioniert
    }
  });

  // Später: Funktionen aufrufen
  await sendAdminMessage();
};
```

**Fix Option B - State-basierter Trigger (besser):**
```typescript
const [shouldSendCustomerMessage, setShouldSendCustomerMessage] = useState(false);

useEffect(() => {
  if (shouldSendCustomerMessage) {
    sendCustomerMessage();
    setShouldSendCustomerMessage(false);
  }
}, [shouldSendCustomerMessage]);

// Im Message Handler:
if (!adminMessageReceivedRef.current) {
  adminMessageReceivedRef.current = true;
  updateStep('6', 'success');
  setShouldSendCustomerMessage(true); // ✅ Trigger über State
}
```

---

### Bug 2: Falscher Feldname `translated_text` ❌

**Problem:**
```typescript
// ❌ Backend sendet "text", nicht "translated_text"!
addLog(`📨 Customer empfängt: "${msg.translated_text}"`);
```

**Backend WebSocket Message Format:**
```json
{
  "type": "message",
  "role": "receiver_message",
  "text": "Übersetzter Text",
  "message_id": "uuid-xxx",
  "sender": "admin"
}
```

**Fix:**
```typescript
// ✅ Verwende "text"
multiWebSocketManager.onMessage('customer', (msg) => {
  // Nur receiver_message verarbeiten
  if (msg.role !== 'receiver_message') {
    addLog(`📤 Ignoriere ${msg.role}`);
    return;
  }

  addLog(`📨 Customer empfängt: "${msg.text}" (von ${msg.sender})`);

  setMessages(prev => {
    const existing = prev.find(m => m.id === msg.message_id);
    if (existing) {
      return prev.map(m =>
        m.id === msg.message_id
          ? { ...m, received: true, text: msg.text }
          : m
      );
    } else {
      // ✅ Füge neue Nachricht hinzu
      return [...prev, {
        id: msg.message_id,
        sender: msg.sender as 'admin' | 'customer',
        text: msg.text,
        timestamp: new Date(),
        received: true,
      }];
    }
  });

  if (!adminMessageReceivedRef.current) {
    adminMessageReceivedRef.current = true;
    updateStep('6', 'success', `"${msg.text}"`);
    setShouldSendCustomerMessage(true);
  }
});
```

**Gleiches für Admin:**
```typescript
multiWebSocketManager.onMessage('admin', (msg) => {
  if (msg.role !== 'receiver_message') return;

  addLog(`📨 Admin empfängt: "${msg.text}" (von Customer)`);
  // ... rest
});
```

---

### Bug 3: Message Deduplication unvollständig ❌

**Problem:**
```typescript
setMessages(prev => {
  const existing = prev.find(m => m.id === msg.message_id);
  if (existing) {
    return prev.map(m =>
      m.id === msg.message_id ? { ...m, received: true } : m
    );
  }
  return prev; // ❌ Nachricht wird NICHT hinzugefügt wenn neu!
});
```

**Was passiert:**
1. Admin sendet Nachricht → Nachricht in `messages` Array ✅
2. Customer empfängt → Nachricht existiert NICHT im Array ❌
3. `return prev` → Nichts passiert ❌

**Fix:**
```typescript
setMessages(prev => {
  const existing = prev.find(m => m.id === msg.message_id);

  if (existing) {
    // ✅ Update existing message
    return prev.map(m =>
      m.id === msg.message_id
        ? { ...m, received: true }
        : m
    );
  } else {
    // ✅ Add new message if not exists
    return [...prev, {
      id: msg.message_id,
      sender: msg.sender as 'admin' | 'customer',
      text: msg.text,
      timestamp: new Date(),
      received: true, // Direkt als empfangen markieren
    }];
  }
});
```

---

### Bug 4: Memory Leak - Handler nicht aufgeräumt ❌

**Problem:**
```typescript
useEffect(() => {
  return () => {
    multiWebSocketManager.disconnect('admin');
    multiWebSocketManager.disconnect('customer');
    // ❌ Message Handler bleiben registriert!
  };
}, []);
```

**Fix Option A - Handler in useEffect:**
```typescript
useEffect(() => {
  if (!testRunning || !sessionId) return;

  // ✅ Setup handlers
  const adminCleanup = multiWebSocketManager.onMessage('admin', (msg) => {
    if (msg.role !== 'receiver_message') return;
    addLog(`📨 Admin empfängt: "${msg.text}"`);
    // ... handler logic
  });

  const customerCleanup = multiWebSocketManager.onMessage('customer', (msg) => {
    if (msg.role !== 'receiver_message') return;
    addLog(`📨 Customer empfängt: "${msg.text}"`);
    // ... handler logic
  });

  // ✅ Cleanup
  return () => {
    adminCleanup?.();
    customerCleanup?.();
  };
}, [testRunning, sessionId]);
```

**Fix Option B - Cleanup-Refs:**
```typescript
const cleanupRefsRef = useRef<(() => void)[]>([]);

const runTest = async () => {
  // Setup handlers
  const adminCleanup = multiWebSocketManager.onMessage('admin', handler);
  const customerCleanup = multiWebSocketManager.onMessage('customer', handler);

  cleanupRefsRef.current = [adminCleanup, customerCleanup];
};

useEffect(() => {
  return () => {
    // ✅ Cleanup all handlers
    cleanupRefsRef.current.forEach(cleanup => cleanup());
    cleanupRefsRef.current = [];

    multiWebSocketManager.disconnect('admin');
    multiWebSocketManager.disconnect('customer');
  };
}, []);
```

---

## 💡 Verbesserungsvorschläge (Nice-to-Have)

### 1. TypeScript Interfaces

```typescript
// ✅ Erstelle Type Definitions
interface WebSocketMessage {
  type: 'message' | 'connection_ack' | 'client_joined';
  role: 'sender_confirmation' | 'receiver_message';
  message_id: string;
  text: string;
  sender: 'admin' | 'customer';
  timestamp: string;
  session_id: string;
  source_lang: string;
  target_lang: string;
  audio_available?: boolean;
  audio_url?: string;
}

// Verwende in Handlers
multiWebSocketManager.onMessage('admin', (msg: WebSocketMessage) => {
  // TypeScript weiß jetzt alle Felder
  console.log(msg.text); // ✅ Type-safe
});
```

### 2. Test Reset Button

```typescript
const resetTest = () => {
  setTestRunning(false);
  testCompletedRef.current = false;
  adminMessageReceivedRef.current = false;
  customerMessageReceivedRef.current = false;
  setMessages([]);
  setLogs([]);
  setSessionId('');

  setSteps(prev => prev.map(s => ({
    ...s,
    status: 'pending' as const,
    message: undefined,
    timestamp: undefined
  })));

  // Cleanup
  multiWebSocketManager.disconnect('admin');
  multiWebSocketManager.disconnect('customer');
};

// In UI
<Button onClick={resetTest} variant="outline">
  Test zurücksetzen
</Button>
```

### 3. Retry-Mechanismus

```typescript
const [failedStep, setFailedStep] = useState<string | null>(null);

const retryFromStep = async (stepId: string) => {
  // Reset steps after failed one
  setSteps(prev => prev.map(s => {
    const stepNumber = parseInt(s.id);
    const failedNumber = parseInt(stepId);

    return stepNumber >= failedNumber
      ? { ...s, status: 'pending' as const, message: undefined }
      : s;
  }));

  // Resume test from failed step
  await runTestFromStep(stepId);
};

// In catch block
catch (error: any) {
  const currentStep = steps.find(s => s.status === 'running');
  if (currentStep) {
    updateStep(currentStep.id, 'error', error.message);
    setFailedStep(currentStep.id);
  }
}

// In UI
{failedStep && (
  <Button onClick={() => retryFromStep(failedStep)}>
    Wiederholen ab Schritt {failedStep}
  </Button>
)}
```

### 4. Message Filters im UI

```typescript
const [messageFilter, setMessageFilter] = useState<'all' | 'admin' | 'customer'>('all');

const filteredMessages = messages.filter(m =>
  messageFilter === 'all' || m.sender === messageFilter
);

// In UI
<div className="flex gap-2 mb-4">
  <Button
    variant={messageFilter === 'all' ? 'default' : 'outline'}
    onClick={() => setMessageFilter('all')}
  >
    Alle
  </Button>
  <Button
    variant={messageFilter === 'admin' ? 'default' : 'outline'}
    onClick={() => setMessageFilter('admin')}
  >
    Admin
  </Button>
  <Button
    variant={messageFilter === 'customer' ? 'default' : 'outline'}
    onClick={() => setMessageFilter('customer')}
  >
    Customer
  </Button>
</div>
```

### 5. Export Test Report

```typescript
const exportTestReport = () => {
  const report = {
    sessionId,
    timestamp: new Date().toISOString(),
    steps: steps.map(s => ({
      id: s.id,
      name: s.name,
      status: s.status,
      message: s.message,
      duration: s.timestamp ? s.timestamp.getTime() - testStartTime : null
    })),
    messages: messages.map(m => ({
      id: m.id,
      sender: m.sender,
      text: m.text,
      received: m.received,
      timestamp: m.timestamp.toISOString()
    })),
    logs: logs,
    success: testCompletedRef.current,
  };

  const blob = new Blob([JSON.stringify(report, null, 2)], {
    type: 'application/json'
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `websocket-test-${sessionId}-${Date.now()}.json`;
  a.click();
};

// In UI
<Button onClick={exportTestReport} variant="outline">
  📄 Bericht exportieren
</Button>
```

---

## 📋 Fix-Checklist

Reihenfolge der Implementierung:

### Phase 1: Kritische Bugs (MUST) ⚠️
- [ ] **Bug 1:** `sendCustomerMessage()` Scope-Problem beheben
- [ ] **Bug 2:** `msg.translated_text` → `msg.text` ändern
- [ ] **Bug 3:** Message Deduplication vervollständigen
- [ ] **Bug 4:** Handler Cleanup implementieren

### Phase 2: Stabilität (SHOULD) 💪
- [ ] TypeScript Interfaces für WebSocket Messages
- [ ] Test Reset Button hinzufügen
- [ ] Error Recovery mit Retry-Mechanismus

### Phase 3: UX (NICE-TO-HAVE) 🎨
- [ ] Message Filters
- [ ] Test Report Export
- [ ] Timing-Informationen pro Step
- [ ] Screenshots/Video-Recording

---

## 🧪 Test nach Fixes

```typescript
// Erwartetes Verhalten:
1. ✅ Session wird erstellt
2. ✅ Admin WebSocket connected
3. ✅ Session aktiviert
4. ✅ Customer WebSocket connected
5. ✅ Admin sendet "Hallo, ich bin der Admin!"
6. ✅ Customer empfängt übersetzten Text
7. ✅ Customer sendet automatisch "Hello, I am the customer!"
8. ✅ Admin empfängt übersetzten Text
9. ✅ Test erfolgreich abgeschlossen
10. ✅ Keine Memory Leaks
11. ✅ Test kann wiederholt werden
```

---

## 📊 Erwartete Console-Logs nach Fixes

```
[10:30:15.123] Step 1: Session erstellen - RUNNING
[10:30:15.456] Step 1: Session erstellen - SUCCESS (Session ID: abc-123)
[10:30:15.789] Admin WebSocket Status: connecting
[10:30:16.012] Admin WebSocket Status: connected
[10:30:16.234] Step 2: Admin WebSocket verbinden - SUCCESS
[10:30:16.567] Step 3: Session aktivieren (Kunde) - RUNNING
[10:30:16.890] Step 3: Session aktivieren (Kunde) - SUCCESS (Sprache: English)
[10:30:17.123] Customer WebSocket Status: connecting
[10:30:17.456] Customer WebSocket Status: connected
[10:30:17.789] Step 4: Customer WebSocket verbinden - SUCCESS
[10:30:18.012] Step 5: Nachricht von Admin senden - RUNNING
[10:30:18.234] ✅ Admin hat Nachricht gesendet: "Hallo, ich bin der Admin!"
[10:30:18.456] Step 5: Nachricht von Admin senden - SUCCESS
[10:30:18.678] 📨 Customer empfängt: "Hello, I am the admin!" (von admin)
[10:30:18.901] Step 6: Nachricht von Admin empfangen (Customer) - SUCCESS
[10:30:19.123] Step 7: Nachricht von Customer senden - RUNNING
[10:30:19.345] ✅ Customer hat Nachricht gesendet: "Hello, I am the customer!"
[10:30:19.567] Step 7: Nachricht von Customer senden - SUCCESS
[10:30:19.789] 📨 Admin empfängt: "Hallo, ich bin der Kunde!" (von customer)
[10:30:20.012] Step 8: Nachricht von Customer empfangen (Admin) - SUCCESS
[10:30:20.234] 🎉 TEST ERFOLGREICH ABGESCHLOSSEN!
```

---

**Priorität:** Fixe zuerst die 4 kritischen Bugs, dann sind Nice-to-Haves optional.

**Geschätzte Zeit:**
- Phase 1 (Kritische Bugs): ~2-3 Stunden
- Phase 2 (Stabilität): ~2 Stunden
- Phase 3 (UX): ~3-4 Stunden

**Status:** ✅ Ready for Implementation

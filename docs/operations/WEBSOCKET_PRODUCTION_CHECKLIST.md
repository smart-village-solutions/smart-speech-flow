# WebSocket-Produktionsdiagnose - Schnellreferenz

**Update:** Debug-Endpunkt `/api/websocket/debug/connection-test` ist in Docker-Produktion verfügbar! ✅

## ⚡ Schnelle Produktionstests

### 1. WebSocket-Verbindungstest (Browser)
```javascript
// In Browser-Konsole auf https://raven-source-75385470.figma.site:
const ws = new WebSocket('wss://ssf.smart-village.solutions/ws/TEST123/customer');
ws.onopen = () => console.log('✅ WebSocket OK');
ws.onerror = (e) => console.log('❌ WebSocket Error:', e);
ws.onclose = (e) => console.log('WebSocket Closed:', e.code, e.reason);
```

### 2. CORS-Test
```javascript
// Teste API-CORS:
fetch('https://ssf.smart-village.solutions/api/languages/supported')
  .then(r => console.log('✅ API CORS OK:', r.status))
  .catch(e => console.log('❌ API CORS Error:', e));
```

### 3. Session-Test
```javascript
// Erstelle Session und teste WebSocket:
fetch('https://ssf.smart-village.solutions/api/admin/session/create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' }
})
.then(r => r.json())
.then(data => {
  console.log('Session:', data.session_id);
  const ws = new WebSocket(`wss://ssf.smart-village.solutions/ws/${data.session_id}/admin`);
  ws.onopen = () => console.log('✅ Session WebSocket OK');
});
```

## 🚨 Erwartete Ergebnisse

| Test | Erwartetes Ergebnis | Bei Fehler |
|------|-------------------|------------|
| **API CORS** | ✅ Status 200 | CORS nicht konfiguriert |
| **WebSocket** | ❌ Code 1003 "Session not found" | CORS/Network-Problem |
| **Session WebSocket** | ✅ Verbindung erfolgreich | Server-Problem |

## ✅ Produktionsstatus (4. Nov 2025)

- **API Gateway:** ✅ Läuft in Docker mit Traefik auf ssf.smart-village.solutions
- **SSL/TLS:** ✅ Automatisches HTTPS über Let's Encrypt
- **CORS:** ✅ Figma-Domains konfiguriert (`*.figma.site`)
- **WebSocket:** ✅ Endpunkt verfügbar (`/ws/`) mit WebSocket-Upgrade-Support
- **Debug-API:** ✅ Verfügbar in Docker-Produktion (`/api/websocket/debug/connection-test`)
- **Fallback:** ✅ Automatisches Polling bei WebSocket-Problemen## 🎯 Nächste Schritte

1. **Führe Browser-Tests aus** (siehe oben)
2. **Bei WebSocket-Fehlern:** System aktiviert automatisch Polling
3. **Funktionalität bleibt 100% erhalten** - kein manueller Eingriff nötig
4. **Monitoring:** Verwende Browser DevTools für detaillierte Fehleranalyse

**Bottom Line:** Das System ist production-ready mit resilientem Fallback. Figma-Integration funktioniert auch bei WebSocket-Problemen durch automatisches Polling. ✅

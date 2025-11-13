# Audio Recording Feature - Rollback Strategy

## Übersicht
Dieses Dokument beschreibt die Rollback-Strategie für das Audio-Recording-Feature im Frontend.

**Feature:** Audio-Aufnahme mit WAV-Konvertierung und Upload
**Status:** Deployed (November 12, 2025)
**Commits:** dd10314, b56fbeb, adaa116, f162307, 9b40a13, 9cf10c2, 2e20bd2, 8932fbd, 7351033, 3b3ba6f

## Rollback-Szenarien

### 1. Kritischer Bug - Sofortiger Rollback

**Wann:**
- Audio-Upload funktioniert gar nicht mehr
- Frontend crasht beim Aufnehmen
- Kritische Performance-Probleme

**Schritte:**
```bash
# 1. Zum letzten stabilen Commit vor Audio-Feature
cd /root/projects/ssf-backend
git checkout <commit-vor-dd10314>

# 2. Frontend neu bauen und deployen
docker compose build frontend
docker compose up -d frontend

# 3. Verifizieren
curl -I https://translate.smart-village.solutions
```

**Letzter stabiler Commit vor Feature:** Siehe Git-Log vor `dd10314`

### 2. Partieller Rollback - UI deaktivieren

**Wann:**
- Backend-Audio-Processing funktioniert
- Nur Frontend-UI hat Probleme
- Text-Modus soll weiter funktionieren

**Schritte:**
1. Audio-Button im UI ausblenden:
```typescript
// In MessageInput.tsx - Audio-Toggle verstecken
const ENABLE_AUDIO_RECORDING = false; // Feature-Flag

// In JSX:
{ENABLE_AUDIO_RECORDING && (
  <button /* Audio-Button */ />
)}
```

2. Deployen:
```bash
docker compose build frontend
docker compose up -d frontend
```

### 3. Backend-Fallback - Graceful Degradation

**Wann:**
- ASR-Service nicht erreichbar
- Audio-Processing-Probleme im Backend

**Bereits implementiert:**
- Circuit Breaker im Backend
- Graceful Degradation für ASR-Ausfälle
- Fehler-Messages werden im Frontend angezeigt

**Monitoring:**
```bash
# Backend-Logs prüfen
docker compose logs -f api_gateway | grep -E "(audio|ASR|circuit)"

# Fehlerrate prüfen
curl http://localhost:9090/api/v1/query?query=circuit_breaker_state
```

## Rollback-Trigger

### Automatische Triggers
- Circuit Breaker öffnet sich (> 50% Fehlerrate)
- Response Time > 10s für Audio-Upload
- Memory Leaks detektiert (> 500MB Frontend)

### Manuelle Triggers
- User-Reports: "Audio funktioniert nicht"
- Cross-Browser-Inkompatibilität
- Produktions-Monitoring zeigt Anomalien

## Rollback-Validierung

Nach jedem Rollback:

1. **Frontend-Funktionalität:**
```bash
# Text-Nachrichten testen
curl -X POST https://translate.smart-village.solutions/api/session/{id}/message \
  -F "content=Test" \
  -F "source_lang=de" \
  -F "target_lang=en" \
  -F "client_type=customer"
```

2. **WebSocket-Verbindung:**
- Admin und Customer öffnen
- Text-Nachricht senden
- Verifizieren: Nachricht kommt beim Empfänger an

3. **Monitoring:**
- Prometheus: Error-Rate < 1%
- Grafana: Response Times normal
- Logs: Keine kritischen Fehler

## Feature-Flag-Ansatz (Empfohlen für Zukunft)

```typescript
// config/features.ts
export const FEATURES = {
  AUDIO_RECORDING: import.meta.env.VITE_ENABLE_AUDIO_RECORDING === 'true',
  UPLOAD_PROGRESS: false, // Noch nicht implementiert
};

// In MessageInput.tsx
import { FEATURES } from '@/config/features';

if (!FEATURES.AUDIO_RECORDING) {
  return <TextOnlyInput />;
}
```

**Vorteil:** Rollback ohne Code-Änderung über Umgebungsvariable

## Kommunikation

### Bei Rollback:
1. **Intern:** Slack/Team-Chat
2. **User:** Status-Page aktualisieren
3. **Dokumentation:** Git-Commit mit Rollback-Grund

### Template:
```
🔄 Rollback: Audio Recording Feature

Grund: [Beschreibung]
Betroffene Versionen: [Commits]
Auswirkung: Audio-Aufnahme temporär deaktiviert, Text-Modus funktioniert
ETA Fix: [Zeitrahmen]
```

## Recovery-Plan

Nach Rollback:

1. **Root Cause Analysis:**
   - Logs analysieren
   - Fehler reproduzieren
   - Unit/Integration-Tests erweitern

2. **Fix entwickeln:**
   - Branch erstellen: `fix/audio-recording-{issue}`
   - Tests schreiben
   - Code-Review

3. **Staged Rollout:**
   - Zuerst in Test-Environment
   - Dann Canary-Deployment (10% User)
   - Bei Erfolg: 100% Deployment

## Backup-Strategien

### Docker-Images aufbewahren
```bash
# Alle Frontend-Images
docker images | grep ssf-backend-frontend

# Image taggen für Backup
docker tag ssf-backend-frontend:latest ssf-backend-frontend:pre-audio-feature
```

### Git-Tags für Releases
```bash
# Stable Release taggen
git tag -a v1.0.0-stable -m "Last stable before audio feature"
git push origin v1.0.0-stable
```

## Kontakte

**Tech Lead:** [Name]
**DevOps:** [Name]
**On-Call:** [Rotation]

## Checkliste: Rollback durchgeführt

- [ ] Git-Rollback ausgeführt
- [ ] Docker-Container neu deployed
- [ ] Frontend erreichbar (HTTPS)
- [ ] Text-Modus funktioniert
- [ ] WebSocket-Verbindungen stabil
- [ ] Monitoring: Keine kritischen Alerts
- [ ] Team informiert
- [ ] Incident-Report erstellt
- [ ] Recovery-Plan definiert

---

**Letzte Aktualisierung:** 12. November 2025
**Version:** 1.0

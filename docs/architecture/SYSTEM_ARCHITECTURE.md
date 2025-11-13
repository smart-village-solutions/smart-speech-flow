# System-Architektur: Smart Speech Flow Backend

## 🏗️ Überblick

Das Smart Speech Flow System ist eine verteilte Mikroservice-Architektur für mehrsprachige Kommunikation zwischen Verwaltungsmitarbeitern und Bürgern. Das System ermöglicht bidirektionale Sprachkommunikation mit automatischer Übersetzung in Echtzeit.

## 🎯 Zielgruppen
- **Admin-Benutzer:** Deutschsprachige Verwaltungsmitarbeiter
- **Client-Benutzer:** Mehrsprachige Bürger und Kunden
- **System-Administratoren:** IT-Personal für Monitoring und Wartung

## 🌍 Produktiv-Setup & öffentliche Endpunkte

| Komponente | Produktions-URL | Hinweise |
|------------|-----------------|----------|
| Frontend (Nginx) | `https://translate.smart-village.solutions` | React SPA (Nginx-Container) mit Admin-Startseite (`/admin`) und Client-Deeplinks (`/join/{sessionId}`). Statische Assets werden direkt ausgeliefert. |
| REST & WebSocket API | `https://ssf.smart-village.solutions` | FastAPI-Gateway; WebSocket-Einstieg `wss://ssf.smart-village.solutions/ws/{sessionId}/{clientType}`. API-Endpunkte unter `/api/*`. |
| Monitoring (Prometheus) | `https://prometheus-ssf.smart-village.solutions` | Read-Only Zugriff auf Prometheus UI und Metriken (`/graph`, `/alerts`). |
| Monitoring (Grafana) | `https://grafana-ssf.smart-village.solutions` | Dashboard-Zugang; Standard-Credentials `admin`/`admin` (nach Erstlogin ändern). |
| TLS & Routing | Traefik | Let's Encrypt Zertifikate für alle Domains, automatisches Routing basierend auf Host-Header. |

**Deployment-Architektur:**
- **Frontend:** Eigener Nginx-Container (`ssf-backend-frontend-1`) auf Port 80, exponiert via Traefik
- **API Gateway:** FastAPI-Container (`ssf-backend-api_gateway-1`) auf Port 8000, exponiert via Traefik
- **Hot-Deploy:** `docker cp dist/. ssf-backend-frontend-1:/usr/share/nginx/html/` für schnelle Frontend-Updates ohne Container-Rebuild

Interne Service-Kommunikation erfolgt über das Docker-Netzwerk (`http://api_gateway:8000`, `http://asr:8000` usw.). Persistente Sitzungen nutzen den Redis-Container (`redis://redis:6379/0`, Namespace `ssf`).

## 🔐 Backend-Validierung

**Unified Endpoint Logic (`https://ssf.smart-village.solutions/api/session/{id}/message`):**
- **Content-Type Detection:** Automatische Erkennung von Audio vs. Text
- **Request-Schema-Validation:** Pydantic-Modelle für beide Input-Typen
- **Pipeline-Routing:** Intelligente Weiterleitung basierend auf Input-Format

**Audio-Validierung (Multipart):**
- **Datei-Validierung:** Format, Dauer, Größe prüfen
- **Audio-Normalisierung:** Konsistente Lautstärke und Qualität
- **Error-Handling:** Ungültige Dateien ablehnen mit klarer Fehlermeldung

**Text-Validierung (JSON):**
- **Längen-Prüfung:** Maximale Zeichenanzahl (500) enforcing
- **Content-Filtering:** Spam-Erkennung und schädliche Inhalte filtern
- **Encoding-Validation:** UTF-8 Konformität sicherstellen
- **Rate-Limiting:** Schutz vor Message-Flooding

**Unified Response Format:**
- **Konsistente Struktur:** Beide Input-Modi verwenden identisches Response-Schema
- **Pipeline-Metadata:** Input-Typ, verwendete Services, Verarbeitungszeit sowie Hinweise für Monitoring und Wartung

## 🔧 Komponenten-Architektur

### **Frontend Layer**

**React Frontend (Nginx)** *(Prod: `https://translate.smart-village.solutions`, Dev: `http://localhost:5173`)* - Unified Admin & Client Interface

**Technologie-Stack:**
- React 18 + TypeScript + Vite
- TailwindCSS v3 für responsives Styling
- WebRTC für browserbasierte Audio-Aufnahme
- Nginx-Container für Production-Serving

**Admin Interface** (`/admin`):
- Session Management: UUID-basierte Session erstellen, Client-URL anzeigen, Status überwachen
- Voice & Text Interface: Deutsch sprechen/schreiben, Übersetzungen hören, Chat-History
- Multi-Session Support: Parallele Sessions verwalten und zwischen ihnen wechseln

**Client Interface** (`/join/{sessionId}`):
- URL-Routing: Session-UUID aus URL extrahieren, Session-Gültigkeit prüfen
- Language Selection: Sprache aus 100+ Optionen auswählen, Session aktivieren
- Voice & Text Interface: In Muttersprache sprechen/schreiben, deutsche Übersetzung hören, Chat-History

**Kommunikation:**
- HTTP REST API (`https://ssf.smart-village.solutions/api/*`) für Session-Management
- WebSocket (`wss://ssf.smart-village.solutions/ws/{sessionId}/{clientType}`) für Echtzeit-Updates mit Polling-Fallback

### **Backend Layer**

**API Gateway** *(Prod: `https://ssf.smart-village.solutions`, Dev: `http://localhost:8000`)* - Zentrale Orchestrierung
- Session Management: UUID-basierte Session-Erstellung, Client-Sprachauswahl-Integration, Status-Tracking und Timeouts, WebSocket-Koordination
- Unified Input Processing: Content-Type-basierte Audio/Text-Erkennung über einheitlichen `/message` Endpunkt
- Pipeline Orchestration: Audio-Pipeline (ASR → Translation → TTS) oder Text-Pipeline (Translation → TTS), Request-Routing an Mikroservices, Error-Handling und Retry-Logic, Response-Aggregation

### **Microservices Layer**

**ASR Service** *(Interner Host: `http://asr:8000`, Port nach außen via Traefik nicht freigegeben)* - Spracherkennung
- Whisper Models: Mehrsprachig, GPU-optimiert
- Audio Processing: Format Detection, Normalisierung, Quality Enhancement

**Translation Service** *(Interner Host: `http://translation:8000`)* - Textübersetzung
- M2M100 Model: 100+ Sprachen, bidirektional, GPU-beschleunigt
- Text Processing: Chunking, Romanisierung, Error Recovery

**TTS Service** *(Interner Host: `http://tts:8000`)* - Sprachsynthese
- Coqui-TTS Models: Hochqualitäts-Stimmen, europäische Sprachen
- HuggingFace MMS-TTS: 1000+ Sprachen, Romanisierung, Auto-Fallback

### **Infrastructure Layer**

**Load Balancer (Traefik):** Terminiert TLS für `translate.smart-village.solutions` und `ssf.smart-village.solutions`, verwaltet Routing-Regeln und Health Checks.

**Container Orchestration (Docker Compose):** Service Discovery, GPU-Support (NVIDIA Runtime), Auto-Restart

**Session Storage (Redis/Memory):** Session State, Message Cache, Timeout Management (`redis://redis:6379/0`, Namespace `ssf`)

**NVIDIA GPU:** CUDA 13.0, Shared Memory, Multi-Service Support

- Prometheus: Metriken-Sammlung, Performance-Tracking, Resource-Monitoring (`https://prometheus-ssf.smart-village.solutions`)
- Grafana: Dashboard-Anzeige, Alerting, Trend-Analyse (`https://grafana-ssf.smart-village.solutions`)
- Application Logs: Structured Logging, Error Aggregation, Audit Trail

## 🔄 Datenfluss-Architektur

### **1. Session-Initiierung (Admin → Client)**

**Parallele Sessions:** Ein Admin kann mehrere aktive Sessions gleichzeitig betreuen; jede Session wird über ihre eigene Session-ID adressiert.

**Workflow:**
1. Admin Frontend sendet POST-Request an `https://ssf.smart-village.solutions/api/admin/session/create`.
2. Der Session Manager erstellt eine neue Session und ergänzt sie zum Satz aktiver Sessions (persistiert optional in Redis).
3. Eine kurze Session-UUID wird generiert (z.B. 550E8400).
4. Das Admin Frontend erhält die vollständige Client-URL mit eingebetteter Session-UUID.
5. Die URL wird dem Kunden gezeigt oder geteilt.
6. Der Client ruft die URL direkt auf (`/join/{session_id}`).
7. Das Client Frontend lädt verfügbare Sprachen und zeigt die Sprachauswahl.
8. Der Client wählt eine Sprache und sendet einen POST-Request an `https://ssf.smart-village.solutions/api/customer/session/activate`.
9. Die Session wird mit der gewählten Kundensprache aktiviert (Admin führt weiterhin Deutsch).
10. Beide Clients erhalten eine Bestätigung: Session ist aktiv und bereit für Kommunikation.

*Hinweis:* Bestehende Sessions bleiben bestehen, bis sie manuell beendet oder automatisch aufgrund von Timeouts geschlossen werden.

### **2. Audio- und Text-Kommunikation (Bidirektional)**

**Workflow:**
1. **Input-Optionen:** Benutzer (Admin oder Client) wählt zwischen:
   - **Audio-Aufnahme:** WebRTC/MediaRecorder (max. 20 Sekunden)
   - **Text-Eingabe:** Direkte Texteingabe über Eingabefeld
2. **Einheitlicher Endpunkt:** Frontend sendet POST-Request an `https://ssf.smart-village.solutions/api/session/{id}/message`
   - **Audio-Input:** Multipart-Upload mit WAV-Datei + Metadaten
   - **Text-Input:** JSON mit Text-Inhalt + Input-Type-Flag
3. **API Gateway Auto-Detection:** Content-Type-basierte Input-Erkennung
   - `multipart/form-data` → Audio-Pipeline
   - `application/json` → Text-Pipeline
4. **Pipeline Orchestration:** API Gateway startet entsprechende Verarbeitung
5. **Text-Extraktion:**
   - **Audio:** ASR Service (Whisper) konvertiert Audio zu Text (Originalsprache)
   - **Text:** Direkter Text wird übernommen (ASR-Pipeline wird übersprungen)
5. Translation Service (M2M100) übersetzt Text (+ romanisierte Version für TTS)
6. TTS Service (Coqui/MMS-TTS) generiert Audio (Zielsprache)
7. API Gateway kodiert Ergebnis (Base64) und strukturiert Response
8. Pipeline Result wird zurückgesendet
9. **Echtzeit-Benachrichtigung erfolgt über:**
   - **Primär:** WebSocket-Broadcast an Gesprächspartner (< 100ms Latenz)
   - **Fallback:** Polling bei WebSocket-Verbindungsabbruch (2-10s Intervall)
   - **Mobile-optimiert:** Reduzierte Frequenz bei inaktiven Tabs
10. **Text-Anzeige erfolgt differenziert:**
    - **Sprecher-Frontend:** Zeigt ASR-Originaltext (zur Bestätigung der Erkennung)
    - **Empfänger-Frontend:** Zeigt übersetzten Text + spielt übersetzte Audio ab

**Beispiel-Szenarien:**

**Audio-Kommunikation:**
- Admin spricht: "Guten Tag, wie kann ich Ihnen helfen?"
- Admin sieht: "Guten Tag, wie kann ich Ihnen helfen?" (ASR-Bestätigung)
- Client sieht: "Good day, how can I help you?" + hört englische Audio
- Client antwortet: "I need help with my documents"
- Client sieht: "I need help with my documents" (ASR-Bestätigung)
- Admin sieht: "Ich brauche Hilfe mit meinen Dokumenten" + hört deutsche Audio

**Text-Kommunikation:**
- Admin tippt: "Welche Dokumente benötigen Sie?"
- Admin sieht: "Welche Dokumente benötigen Sie?" (Eingabe-Bestätigung)
- Client sieht: "What documents do you need?" + hört englische Audio
- Client tippt: "My passport and visa documents"
- Client sieht: "My passport and visa documents" (Eingabe-Bestätigung)
- Admin sieht: "Meine Pass- und Visa-Dokumente" + hört deutsche Audio

**Gemischte Kommunikation:**
- Admin spricht Audio, Client antwortet per Text (oder umgekehrt)
- Beide Input-Modi können frei kombiniert werden

## 🌐 Frontend-Architektur

### **Unified React Frontend** *(Prod: `https://translate.smart-village.solutions`, Dev: `http://localhost:5173`)*

**Deployment:**
- **Production:** Nginx-Container (`ssf-backend-frontend-1`) auf Port 80
- **Traefik-Routing:** `Host(translate.smart-village.solutions)` → Frontend-Container
- **Hot-Deploy:** `docker cp dist/. ssf-backend-frontend-1:/usr/share/nginx/html/`
- **Build-Pipeline:** `npm run build` → Vite generiert optimierte Bundles in `dist/`

**Technologie-Stack:**
- React 18 + TypeScript + Vite
- TailwindCSS v3 (CSS: ~18 KB gzipped)
- React Router für Client-side Routing
- WebRTC für browserbasierte Audio-Aufnahme

**Routing-Struktur:**
- `/` → Landing Page mit Admin-Login
- `/admin` → Admin Interface (Session Management)
- `/customer` → Customer Interface (nach Activation)

**Shared Components:**

**SessionContext:**
- Global State Management für Messages, Session-ID, Client-Type
- WebSocket-Service-Integration mit automatischem Reconnect
- Temp-ID-Mapping für optimistische UI-Updates
- Message-History-Verwaltung mit Deduplication

**MessageComponents:**
- **MessageList:** Scrollbare Chat-History mit Auto-Scroll
- **MessageBubble:** Nachrichtendarstellung mit Pipeline-Metadata (expandable)
- **MessageInput:** Unified Input für Text mit Character-Counter (500 max)
- **AudioPlayer:** Audio-Wiedergabe mit Play/Pause-Controls

**WebSocketService:**
- Connection Management mit exponential backoff
- Message-Queue für offline Messages
- Automatic Reconnection bei Verbindungsabbruch
- Status-Monitoring (connected, connecting, disconnected)

**Admin-Specific Components:**

**SessionManager:**
- Session-Erstellung mit UUID-Generierung
- Client-URL-Display mit Copy-Button
- Session-Status-Monitoring (inactive, pending, active)
- Multi-Session-Support (parallele Sessions möglich)

**AdminDashboard:**
- Active Sessions Overview
- Session-Switching via Session-ID
- Manual Session-Termination
- Connection Status Indicators

**Customer-Specific Components:**

**SessionJoin:**
- URL-Parameter-Extraktion (`/customer?session_id={uuid}`)
- Session-Validation API-Call
- Error-Handling für ungültige Sessions

**LanguageSelector:**
- 100+ Sprachen mit Flaggen-Icons
- Search/Filter-Funktionalität
- Session-Activation mit gewählter Sprache

**CustomerInterface:**
- Welcome-Screen nach Activation
- Language-specific Instructions
- Audio/Text Input Interface
- Real-time Translation Display

## ⚙️ Backend-Architektur

### **API Gateway** *(Prod: `https://ssf.smart-village.solutions`, Dev: `http://localhost:8000`)*

**Technologie-Stack:**
- FastAPI + Uvicorn für moderne Python-API-Entwicklung
- Pydantic für robuste Datenvalidierung
- asyncio für hohe Concurrency-Performance
- WebSocket-Support für Echtzeit-Features

**Hauptmodule:**

**API-Endpunkte:**

**Unified Message Endpoint:** `POST https://ssf.smart-village.solutions/api/session/{session_id}/message`
```json
// Audio-Input (multipart/form-data)
{
  "audio_file": "<WAV-Datei>",
  "metadata": {
    "sender": "admin|client",
    "timestamp": "2025-09-28T10:30:00Z"
  }
}

// Text-Input (application/json)
{
  "text": "Hallo, wie kann ich helfen?",
  "sender": "admin|client",
  "timestamp": "2025-09-28T10:30:00Z",
  "input_type": "text"
}

// Unified Response
{
  "message_id": "uuid",
  "session_id": "uuid",
  "original_text": "Hallo, wie kann ich helfen?",
  "translated_text": "Hello, how can I help?",
  "audio_url": "https://ssf.smart-village.solutions/api/audio/uuid.wav",
  "input_type": "audio|text",
  "processing_time": 1.2,
  "timestamp": "2025-09-28T10:30:01Z"
}
```

**session_manager.py:**
- **SessionManager:** Paralleles Session-Management mit optionalem Cleanup
  - **Active Session Tracking:** Menge aktiver Admin-Sessions (Redis-persistiert)
  - **Session Termination Logic:** Manuelles oder Timeout-basiertes Beenden bestehender Sessions
  - **WebSocket-Connection-Pool:** Verbindungsmanagement pro Session
  - **Graceful Disconnect:** Client-Benachrichtigung bei Session-Beendigung
  - **Broadcast-Funktionalität:** Echtzeit-Updates an alle Session-Teilnehmer
  - **Persistence Layer:** Redis-gestütztes Session- und Message-Storage (Fallback: In-Memory)
- **Session:** Session-Model mit paralleler Nutzung
  - **State:** inactive → pending → active → terminated
  - **Language-Pair:** Admin (DE) ↔ Customer (selected language)
  - **Timeout-Management:** Automatische Cleanup nach Inaktivität
- **SessionMessage:** Nachrichten-Datenstrukturen mit differenzierter Text-Ausgabe
  - original_text: ASR-erkannter Text oder eingegebener Text (für Sprecher-Anzeige)
  - translated_text: Übersetzter Text (für Empfänger-Anzeige)
  - audio_data: Übersetzte Audio-Datei (für Empfänger-Wiedergabe)
- **ClientType:** Admin/Customer-Unterscheidung mit Role-basierter Session-Control

> **Failover:** Ist Redis nicht erreichbar, schaltet der SessionManager automatisch auf den bewährten In-Memory-Betrieb zurück (Startup-Log-Hinweis). In Docker-Deployments stellt `docker-compose.yml` den Redis-Dienst inklusive AOF-Persistenz und Namespace-Konfiguration bereit.

**routes-Module:**
- session.py: Session-CRUD-Operationen mit UUID-Support
- admin.py: Admin-Session-Erstellung ohne Sprachauswahl
- customer.py: Client-Session-Aktivierung mit Sprachauswahl
- websocket.py: WebSocket-Handler für bidirektionale Echtzeit-Kommunikation
  - Connection-Management pro Session und Client-Typ
  - Message-Broadcasting mit Sender-Ausschluss
  - Heartbeat und Reconnect-Logic
  - Graceful Degradation zu Polling-Fallback

**pipeline_logic.py:**
- process_wav(): Audio-Pipeline-Orchestrierung mit differenzierter Response-Strukturierung
  - original_text: Für Sprecher-Frontend (ASR-Bestätigung)
  - translated_text: Für Empfänger-Frontend (Anzeige)
  - translated_audio: Für Empfänger-Frontend (Wiedergabe)
- service_health_check(): Mikroservice-Monitoring
- error_recovery(): Retry-Logic und Fallbacks

**middleware-Module:**
- cors.py: Cross-Origin-Konfiguration
- rate_limiting.py: Request-Rate-Begrenzung
- authentication.py: Zukünftige Auth-Integration

### **ASR Service** *(Interner Host: `http://asr:8000`)*

**Whisper-basierte Spracherkennung:**

**Models:**
- whisper-base: Schnell, moderate Genauigkeit
- whisper-medium: Balance zwischen Speed und Accuracy
- whisper-large: Höchste Genauigkeit, langsamer

**Processing-Module:**
- audio_normalization: WAV-Konvertierung, Rauschreduzierung
- language_detection: Automatische Spracherkennung
- confidence_scoring: Qualitätsbewertung der Transkription

**API-Endpunkte (intern):**
- `http://asr:8000/transcribe`: Hauptendpunkt für Audio-zu-Text-Konvertierung
- `http://asr:8000/languages`: Unterstützte Sprachen abrufen
- `http://asr:8000/health`: Service-Status und GPU-Informationen

### **Translation Service** *(Interner Host: `http://translation:8000`)*

**M2M100-basierte Übersetzung:**

**Models:**
- m2m100_418M: Schneller, weniger Speicherverbrauch
- m2m100_1.2B: Höhere Qualität, mehr Ressourcen benötigt

**Processing-Module:**
- text_chunking: Lange Texte intelligent aufteilen
- romanization: uroman für TTS-Vorbereitung
- quality_assessment: Übersetzungsqualität bewerten

**API-Endpunkte (intern):**
- `http://translation:8000/translate`: Text-zu-Text-Übersetzung
- `http://translation:8000/languages`: 100+ unterstützte Sprachpaare
- `http://translation:8000/health`: Model-Status und Performance-Metriken

### **TTS Service** *(Interner Host: `http://tts:8000`)*

**Multi-Provider TTS-System:**

**Models:**

**Coqui-TTS (Hochqualität):**
- Deutsche Stimme: tts_models--de--thorsten--tacotron2-DDC
- Englische Stimme: tts_models--en--ljspeech--tacotron2-DDC
- Multilingual: tts_models--multilingual--multi-dataset

**HuggingFace-MMS (Breite Sprachunterstützung):**
- Arabisch: facebook/mms-tts-ara
- Russisch: facebook/mms-tts-rus
- Amharisch: facebook/mms-tts-amh (1000+ weitere Sprachen)

**Processing-Module:**
- voice_selection: Optimale Stimme pro Sprache wählen
- audio_optimization: Qualität, Lautstärke, Tempo anpassen
- format_conversion: WAV-Output-Standardisierung

**API-Endpunkte (intern):**
- `http://tts:8000/synthesize`: Text-zu-Audio-Konvertierung (WAV)
- `http://tts:8000/voices`: Verfügbare Stimmen pro Sprache
- `http://tts:8000/health`: TTS-Model-Status und Verfügbarkeit

## 📊 Monitoring & Logging-Architektur

### **Metriken-Sammlung (Prometheus)**

**Gesammelte Metriken:**

**System-Metriken:**
- CPU/RAM/GPU-Auslastung pro Service
- Container-Health und Restart-Counts
- Network-Latenz zwischen Services

**Performance-Metriken:**
- Request-Latenz pro Endpunkt
- Pipeline-Durchlaufzeiten (ASR→Translation→TTS)
- Model-Inferenz-Zeiten
- Audio-Verarbeitungsqualität
- **WebSocket-Metriken:**
  - Verbindungs-Latenz (< 100ms Ziel)
  - Message-Delivery-Rate (> 99.5%)
  - Reconnect-Häufigkeit
  - Polling-Fallback-Nutzung

**Business-Metriken:**
- Sessions pro Stunde/Tag
- Sprachen-Verteilung
- Erfolgs-/Fehlerrate der Kommunikation
- Durchschnittliche Session-Dauer
- **Kommunikations-Effizienz:**
  - Echtzeit-Update-Rate (WebSocket vs. Polling)
  - Nachrichtenaustausch-Latenz
  - User-Engagement pro Session

**GPU-Metriken (DCGM-Exporter):**
- GPU-Auslastung und Memory-Usage
- Model-Loading-Zeiten
- Concurrent-Request-Handling

### **GPU Resource Management (Phase 6.1)**

- Aggregierte GPU-Metriken werden im API-Gateway gesammelt und über `/circuit-breaker/health/summary` ausgespielt.
- Schwellwerte: Warnung ab ≥75 % Auslastung, kritisch ab ≥90 % (GPU) bzw. ≥95 % (Memory).
- Alerts: "gpu_pressure" für kritische Services, "gpu_unavailable" wenn ein Service keine GPU meldet.
- Autoscaling-Signale pro Service werden kombiniert und als `scale_up_recommendations` ausgewiesen.
- Ops-Workflow: Dashboard nutzt `gpu_summary` zur Skalierungsentscheidung (z. B. zusätzliche GPU-Worker ausrollen, Graceful-Degradation-Modus prüfen).

### **Visualisierung (Grafana)**

**Dashboards:**

**System-Overview:**
- Service-Health-Status: Rot/Grün-Status aller Services
- Resource-Utilization: CPU/RAM/GPU-Auslastung
- Request-Volume: Traffic-Patterns und Lastverteilung

**Performance-Analysis:**
- Pipeline-Latenz: End-to-End Response-Times
- Bottleneck-Identification: Langsamste Service-Stufe identifizieren
- Quality-Metrics: Transkriptions-/Übersetzungsqualität, ASR-Bestätigungs-Accuracy

**Business-Intelligence:**
- Session-Analytics: Nutzungsmuster und Trends
- Language-Statistics: Häufigste Sprachkombinationen
- User-Experience: Session-Erfolgsrate, ASR-Text-Bestätigungs-Rate, Kommunikations-Zufriedenheit

**Alerting:**
- Service-Downtime: Sofortige Benachrichtigungen bei Ausfällen
- Performance-Degradation: Latenz-Schwellenwerte überwachen
- Resource-Exhaustion: GPU/Memory-Limits erreicht

### **Logging-Strategie**

**Structured Logging (JSON-Format):**

**Log-Levels:**
- ERROR: Service-Ausfälle, Pipeline-Fehler
- WARN: Performance-Probleme, Timeouts
- INFO: Session-Events, Request-Flow
- DEBUG: Detaillierte Pipeline-Steps

**Log-Quellen:**

**API-Gateway:**
- Session-Lifecycle: Erstellung, Timeouts, Cleanup
- Request-Routing: Service-Calls und Responses
- Error-Recovery: Retry-Attempts und Fallbacks

**Microservices:**
- Model-Loading: Startup und Memory-Allocation
- Inference-Performance: Processing-Times pro Request
- Quality-Metrics: Confidence-Scores, Fehlerrate

**Infrastructure:**
- Container-Events: Starts, Stops, Crashes
- GPU-Allocation: Memory-Management
- Network-Communication: Inter-Service-Latenz

**Log-Aggregation:**
- Centralized Collection via ELK Stack (optional)
- Retention Policy: 30 Tage für DEBUG, 90 Tage für ERROR
- Real-time Error Alerting via Webhook-Integration

## 🔒 Sicherheit & Skalierung

### **Sicherheitsmaßnahmen**
- **CORS-Policy:** Restricted Origins für Frontend-Zugriff
- **Rate-Limiting:** Schutz vor API-Missbrauch
- **Input-Validation:** Pydantic-basierte Request-Validierung
- **Audio-Sanitization:** Dateiformat- und Größenbegrenzung
- **Session-Timeouts:** Automatische Cleanup nach Inaktivität
- **SSL/TLS:** Traefik-managed Certificates für HTTPS

### **Skalierungsstrategien**
- **Horizontal Scaling:** Docker Compose → Kubernetes-Migration
- **Load Balancing:** Traefik-basierte Request-Distribution
- **GPU-Sharing:** Multi-Tenant GPU-Nutzung optimieren
- **Model-Caching:** Shared Memory für häufig genutzte Models
- **CDN-Integration:** Static Asset Delivery optimieren

## 🚀 Deployment & DevOps

### **Container-Orchestrierung**

**Docker Compose Struktur:**
- traefik: Load Balancer + SSL-Terminierung + Let's Encrypt
- frontend: Unified React SPA (Nginx) → `translate.smart-village.solutions`
- api_gateway: Session-Management + Pipeline-Orchestration → `ssf.smart-village.solutions`
- asr: Speech-to-Text Service (intern)
- translation: Text-to-Text Service (intern)
- tts: Text-to-Speech Service (intern)
- prometheus: Metrics Collection → `prometheus-ssf.smart-village.solutions`
- grafana: Visualization Dashboard → `grafana-ssf.smart-village.solutions`
- redis: Session Storage mit AOF-Persistenz

**GPU-Resource-Sharing:**
Alle KI-Services können auf verfügbare NVIDIA-GPUs zugreifen durch:
- Driver: nvidia
- Count: all (alle verfügbaren GPUs)
- Capabilities: gpu (GPU-Compute-Zugriff)

### **CI/CD-Pipeline (Vorbereitet)**

**Pipeline-Stages:**

**Development-Stage:**
- Unit Tests: Komponenten-Tests für alle Module
- Linting: Code-Quality-Checks (flake8, pylint)
- Type-Check: TypeScript/Python Type-Validation

**Testing-Stage:**
- Integration Tests: Service-übergreifende Tests
- Load Testing: Performance unter Last
- Security Scan: Vulnerability-Assessment

**Staging-Stage:**
- Canary Deploy: Schrittweise Bereitstellung
- Health Monitoring: Automated Health-Checks
- Rollback-Ready: Sofortige Rücknahme bei Problemen

**Production-Stage:**
- Zero-Downtime Deployment
- Automated Monitoring
- Performance-Validation

## 🎵 Input-Spezifikationen

### **Audio-Parameter**
- **Format:** WAV (16kHz, 16-bit, Mono)
- **Maximale Dauer (Backend):** 200 Sekunden *(Frontend setzt engere Limits, default 20s)*
- **Dateigröße-Limit (Backend):** 32 MB *(Frontend limitiert enger)*
- **Qualitäts-Optimierung:** 16kHz für Whisper-Modelle optimiert

### **Text-Parameter**
- **Maximale Länge:** 500 Zeichen pro Nachricht
- **Unterstützte Zeichen:** UTF-8 (alle Sprachen und Emojis)
- **Eingabe-Validierung:** Echtzeit-Zeichenzähler und Längenbegrenzung
- **Auto-Formatierung:** Automatische Bereinigung von Leerzeichen und Sonderzeichen

### **Frontend-Implementation**

**Audio-Features:**
- **WebRTC MediaRecorder:** Browserbasierte Audio-Aufnahme
- **Real-time Validation:** Dauer-Monitoring während Aufnahme
- **Auto-Stop:** Automatischer Stopp bei 20 Sekunden
- **Format-Conversion:** Client-seitige WAV-Konvertierung
- **Upload-Optimierung:** Chunked Upload für große Dateien

**Text-Features:**
- **Rich Text Editor:** Mehrsprachige Texteingabe mit Sprachunterstützung
- **Character Counter:** Live-Anzeige verbleibender Zeichen (500 max)
- **Input Validation:** Client-seitige Längenbegrenzung und Formatprüfung
- **Auto-Submit:** Enter-Taste oder Send-Button für Nachrichtenversand
- **Accessibility:** Screen Reader Support und Tastaturnavigation

### **Backend-Validierung**

**Audio-Validierung:**
- **Datei-Validierung:** Format, Dauer, Größe prüfen
- **Audio-Normalisierung:** Konsistente Lautstärke und Qualität
- **Error-Handling:** Ungültige Dateien ablehnen mit klarer Fehlermeldung

**Text-Validierung:**
- **Längen-Prüfung:** Maximale Zeichenanzahl (500) enforcing
- **Content-Filtering:** Spam-Erkennung und schädliche Inhalte filtern
- **Encoding-Validation:** UTF-8 Konformität sicherstellen
- **Rate-Limiting:** Schutz vor Message-Flooding

**Performance-Monitoring:**
- **Input-Statistiken:** Audio vs. Text Nutzungsverteilung
- **Pipeline-Optimierung:** ASR-Skip bei Text-Input reduziert Latenz
- **Resource-Usage:** CPU-Einsparung durch direkten Text-Input

### **Benutzerführung**

**Audio-UX:**
- **Visual Feedback:** Countdown-Timer während Aufnahme
- **Progress Indicator:** Verbleibende Zeit anzeigen
- **Warning Notifications:** Bei Annäherung an 20s-Limit
- **Quality Guidelines:** Optimale Aufnahme-Bedingungen erklären

**Text-UX:**
- **Character Counter:** Verbleibende Zeichen live anzeigen (500 max)
- **Input Mode Toggle:** Eindeutige Buttons für Audio/Text-Wechsel
- **Language Hints:** Eingabe-Unterstützung für gewählte Sprache
- **Send Confirmation:** Kurze Bestätigung bei erfolgreichem Versand

**Unified UX:**
- **Mode Selection:** Klare visuelle Unterscheidung zwischen Audio/Text-Modus
- **Accessibility:** Tastatur-Shortcuts und Screen Reader Support
- **Mobile Optimization:** Touch-optimierte Buttons und Eingabefelder

##📈 Performance-Ziele

### **Latenz-Ziele**
- **ASR (Whisper):** < 2 Sekunden für 20s Audio
- **Translation:** < 500ms für 100 Wörter
- **TTS:** < 3 Sekunden Audio-Generation
- **End-to-End Pipeline:** < 6 Sekunden total
- **Session-Join:** < 200ms Response
- **WebSocket-Updates:** < 100ms Nachrichten-Zustellung
- **Polling-Fallback:** < 2 Sekunden Update-Intervall
- **Mobile-Polling:** < 10 Sekunden bei inaktiven Tabs

### **Durchsatz-Ziele**
- **Single Active Session:** Ein Administrator, eine aktive Session (sequenziell)
- **Session-Switching:** < 2 Sekunden für Session-Termination + Creation
- **Request-Rate:** 1000+ API-Calls pro Minute
- **Audio-Processing:** 100+ Stunden Audio pro Tag (über alle Sessions)
- **Multi-Language Support:** 100+ Sprachen verfügbar

### **Verfügbarkeit-Ziele**
- **System-Uptime:** 99.5% (4 Stunden Downtime/Monat)
- **Service-Recovery:** < 30 Sekunden nach Ausfall
- **Data-Persistence:** Session-Daten überleben Service-Restarts
- **Graceful-Degradation:** Basis-Funktionen auch bei Teilausfall
- **WebSocket-Verfügbarkeit:** 99.9% (automatischer Polling-Fallback bei Ausfall)
- **Connection-Recovery:** < 5 Sekunden Reconnect bei Verbindungsabbruch
- **Cross-Platform-Support:** Konsistente Performance auf Desktop/Mobile

## 🚨 Exception-Handling & Resilience

### **Kritische Ausnahmesituationen**

#### **🔧 Service-Level Exceptions**

#### **🌐 Network & Connection Exceptions**

**WebSocket-Verbindungsabbrüche:**
- **Problem:** Instabile Internetverbindung, Server-Restarts
- **Lösung:**
  - Automatische Reconnection mit exponential backoff
  - Message-Queue für verlorene Nachrichten
  - Seamless Fallback auf HTTP-Polling
- **Recovery:** < 5 Sekunden ohne Datenverlust

**Session-Parallel-Handling:**
- **Problem:** Admin startet zusätzliche Sessions, während andere aktiv bleiben.
- **Lösung:**
  - **Parallele Session-Verwaltung:** Session Manager verwaltet mehrere aktive Sessions im Set.
  - **Gezielte Termination:** Admin kann einzelne Sessions manuell beenden; Clients erhalten nur dann Disconnect-Messages.
  - **Resource Management:** Inaktive Sessions werden über Timeouts oder Admin-Aktionen bereinigt.
- **User-Experience:** Admins können mehrere Gespräche parallel betreuen und per Session-ID zwischen ihnen wechseln.

**Session-Timeout-Handling:**
- **Problem:** Inaktive Sessions blockieren Ressourcen bei längerer Parallel-Nutzung
- **Lösung:**
  - Configurable Timeouts: 15min Inaktivität → Warning, 30min → Auto-Close
  - Session-Heartbeat über WebSocket-Ping
  - Automatic Session-Cleanup bei Admin-Disconnect
- **User-Notification:** Countdown-Warning vor Session-Ablauf

#### **💾 Data & Storage Exceptions**

**Session-Daten-Korruption:**
- **Problem:** Inkonsistente Session-States nach Crashes
- **Lösung:**
  - Transaction-basierte Session-Updates
  - Session-State-Validation bei jedem Request
  - Auto-Recovery durch Session-Rebuild
- **Backup:** Redis-Persistenz + JSON-Backup alle 5 Minuten

**Audio-File-Upload-Fehler:**
- **Problem:** Korrupte Audio-Dateien, unvollständige Uploads
- **Lösung:**
  - Multi-stage Validation: Header → Content → Playability
  - Chunked Upload mit Integrity-Checks
  - Automatic Cleanup für failed Uploads
- **User-Guidance:** Retry-Mechanismus mit Erfolgs-Feedback

**Message-History-Verlust:**
- **Problem:** Chat-History geht bei Session-Crash verloren
- **Lösung:**
  - Real-time Message-Persistence in Redis
  - Automatic Backup nach jedem Message
  - Session-Recovery mit vollständiger History
- **Data-Integrity:** Message-ID-based Deduplication

### **🔄 Resilience-Patterns**

**Graceful Degradation-Hierarchie:**
1. **Full-Feature:** Audio + Text + Real-time Translation
2. **Degraded:** Text-Only + Translation + Polling-Updates


---

**Diese Architektur bietet eine skalierbare, robuste Grundlage für mehrsprachige Echtzeit-Kommunikation in Verwaltungsumgebungen mit professionellem Monitoring und Wartbarkeit.**

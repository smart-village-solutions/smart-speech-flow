# System-Architektur: Smart Speech Flow Backend

## 🏗️ Überblick

Das Smart Speech Flow System ist eine verteilte Mikroservice-Architektur für mehrsprachige Kommunikation zwischen Verwaltungsmitarbeitern und Bürgern. Das System ermöglicht bidirektionale Sprachkommunikation mit automatischer Übersetzung in Echtzeit.

## 🎯 Zielgruppen

- **Admin-Benutzer:** Deutschsprachige Verwaltungsmitarbeiter
- **Client-Benutzer:** Mehrsprachige Bürger und Kunden
- **System-Administratoren:** IT-Pers**Backend-Validierung:**

**Unified Endpoint Logic (`/api/session/{id}/message`):**
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
- **Pipeline-Metadata:** Input-Typ, verwendete Services, Verarbeitungszeititoring und Wartung

## 🔧 Komponenten-Architektur

### **Frontend Layer**

**Admin Frontend (Port: 5173)** - Deutsche Verwaltungsoberfläche
- Session Management: UUID-basierte Session erstellen, Client-URL anzeigen, Status überwachen
- Voice Interface: Deutsch sprechen, Übersetzungen hören, Chat-History

**Client Frontend (Port: 5174)** - Mehrsprachige Bürgeroberfläche
- URL-Routing: Session-UUID aus URL extrahieren, Session-Gültigkeit prüfen
- Language Selection: Sprache aus 100+ Optionen auswählen, Session aktivieren
- Voice Interface: In Muttersprache sprechen, deutsche Übersetzung hören, Chat-History

**Kommunikation:** HTTP REST API für Session-Management, WebSocket für Echtzeit-Updates (mit Polling-Fallback)

### **Backend Layer**

**API Gateway (Port: 8000)** - Zentrale Orchestrierung
- Session Management: UUID-basierte Session-Erstellung, Client-Sprachauswahl-Integration, Status-Tracking und Timeouts, WebSocket-Koordination
- Unified Input Processing: Content-Type-basierte Audio/Text-Erkennung über einheitlichen `/message` Endpunkt
- Pipeline Orchestration: Audio-Pipeline (ASR → Translation → TTS) oder Text-Pipeline (Translation → TTS), Request-Routing an Mikroservices, Error-Handling und Retry-Logic, Response-Aggregation

### **Microservices Layer**

**ASR Service (Port: 8001)** - Spracherkennung
- Whisper Models: Mehrsprachig, GPU-optimiert
- Audio Processing: Format Detection, Normalisierung, Quality Enhancement

**Translation Service (Port: 8002)** - Textübersetzung
- M2M100 Model: 100+ Sprachen, bidirektional, GPU-beschleunigt
- Text Processing: Chunking, Romanisierung, Error Recovery

**TTS Service (Port: 8003)** - Sprachsynthese
- Coqui-TTS Models: Hochqualitäts-Stimmen, europäische Sprachen
- HuggingFace MMS-TTS: 1000+ Sprachen, Romanisierung, Auto-Fallback

### **Infrastructure Layer**

**Load Balancer (Traefik):** SSL/TLS, Routing, Health Checks

**Container Orchestration (Docker Compose):** Service Discovery, GPU-Support, Auto-Restart

**Session Storage (Redis/Memory):** Session State, Message Cache, Timeout Management

**NVIDIA GPU:** CUDA 13.0, Shared Memory, Multi-Service Support

**Monitoring & Logging:**
- Prometheus: Metriken-Sammlung, Performance-Tracking, Resource-Monitoring
- Grafana: Dashboard-Anzeige, Alerting, Trend-Analyse
- Application Logs: Structured Logging, Error Aggregation, Audit Trail

## 🔄 Datenfluss-Architektur

### **1. Session-Initiierung (Admin → Client)**

**Single-Session-Regel:** Es darf immer nur eine aktive Session pro Admin geben.

**Workflow:**
1. **Session-Cleanup:** Admin Frontend sendet POST-Request an /api/admin/session/create
2. **Existing Session Termination:** API Gateway beendet automatisch alle bestehenden Admin-Sessions
   - Aktive WebSocket-Verbindungen werden geschlossen
   - Client-Benutzer erhalten Disconnect-Notification: "Session wurde vom Administrator beendet"
   - Session-Cleanup und Resource-Freigabe
3. **New Session Creation:** Session Manager erstellt neue Session
4. Session-UUID wird generiert (z.B. 550e8400-e29b-41d4-a716-446655440000)
5. Admin Frontend erhält vollständige Client-URL mit eingebetteter Session-UUID
5. URL wird dem Kunden gezeigt oder geteilt
6. Client ruft URL direkt auf (/join/{session_id})
7. Client Frontend lädt verfügbare Sprachen und zeigt Sprachauswahl
8. Client wählt Sprache und sendet POST-Request an /api/customer/session/activate
9. Session wird mit gewählter Kundensprache aktiviert (Admin spricht immer Deutsch)
10. Beide Clients erhalten Bestätigung: Session ist aktiv und bereit für Kommunikation

### **2. Audio- und Text-Kommunikation (Bidirektional)**

**Workflow:**
1. **Input-Optionen:** Benutzer (Admin oder Client) wählt zwischen:
   - **Audio-Aufnahme:** WebRTC/MediaRecorder (max. 20 Sekunden)
   - **Text-Eingabe:** Direkte Texteingabe über Eingabefeld
2. **Einheitlicher Endpunkt:** Frontend sendet POST-Request an `/api/session/{id}/message`
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

### **Admin Frontend (Port: 5173)**

**Technologie-Stack:**
- React 18 + TypeScript für moderne Komponentenentwicklung
- Vite für schnelle Build-Pipeline
- TailwindCSS für responsives Styling
- WebRTC für browserbasierte Audio-Aufnahme

**Hauptkomponenten:**

**SessionManager-Module:**
- **CreateSession:** Single-Session-Regel enforcing
  - Bestehende Sessions automatisch beenden
  - Neue Session erstellen (ohne Sprachauswahl)
  - Client-Disconnect-Notifications versenden
- **URLDisplay:** Client-URL prominent anzeigen und teilen
- **StatusMonitor:** Client-Join und Sprachauswahl überwachen
- **SessionHistory:** Beendete Sessions verwalten (aktive Session ist immer singular)

**CommunicationInterface-Module:**
- **InputSelector:** Toggle zwischen Audio-Aufnahme und Text-Eingabe
- **AudioRecorder:** Deutsche Audio-Aufnahme (max. 20 Sekunden)
- **TextInput:** Deutsche Text-Eingabe mit Live-Vorschau
- **MessageDisplay:** Chat-History mit Audio-Player
- **TranslationView:** Originaler Input (ASR/Text) vs. Übersetzung (empfangene Nachrichten)
- **InputConfirmation:** Anzeige des ASR-Texts oder eingegebenen Texts zur Bestätigung
- **RealtimeCommunication:** WebSocket-Verbindung mit Polling-Fallback
- **ConnectionStatus:** Session- und WebSocket-Verbindungsstatus

**AdminDashboard-Module:**
- **CurrentSession:** Einzelne aktive Session-Anzeige (statt Multiple Sessions)
  - Session-Status und Client-Information
  - Session-Terminate-Button für manuelles Beenden
- **SessionHistory:** Vergangene Sessions mit Zeitstempel und Dauer
- **Statistics:** Nutzungsstatistiken pro Session
- **Settings:** Konfiguration und Einstellungen

### **Client Frontend (Port: 5174)**

**Technologie-Stack:**
- React 18 + TypeScript für moderne Komponentenentwicklung
- i18next für vollständige Internationalisierung
- WebRTC für browserbasierte Audio-Aufnahme
- PWA-Support für optimale mobile Nutzung

**Hauptkomponenten:**

**SessionJoin-Module:**
- URLRouter: Session-UUID aus URL extrahieren
- SessionValidation: Session-Gültigkeit prüfen
- LanguagePicker: Sprache aus 100+ Optionen auswählen
- SessionActivation: Session mit gewählter Sprache aktivieren

**LanguageSelection-Module:**
- InfoPage: Anweisungen in der gewählten Zielsprache
- FlagDisplay: Visuelle Sprachendarstellung mit Flaggen
- WelcomeScreen: Begrüßung in Muttersprache

**CommunicationInterface-Module:**
- **InputModeSelector:** Wahl zwischen Audio-Aufnahme und Text-Eingabe
- **RecordButton:** Audio-Aufnahme in Muttersprache (max. 20 Sekunden)
- **TextInputField:** Text-Eingabe in Muttersprache mit Sprachunterstützung
- **PlaybackQueue:** Deutsche Audio-Antworten wiedergeben
- **VisualFeedback:** Audio-Wellenformen und Status-Anzeigen
- **InputConfirmation:** Anzeige des ASR-Texts oder eingegebenen Texts in Muttersprache
- **RealtimeCommunication:** WebSocket-Verbindung mit Polling-Fallback und Mobile-Optimierung
- **ChatHistory:** Gesprächsverlauf mit differenzierter Text-Anzeige
  - Eigene Nachrichten: ASR-/Text-Original
  - Empfangene Nachrichten: Übersetzter Text

**UserExperience-Module:**
- OfflineMode: Basis-Funktionen ohne Internet
- AccessibilityTools: Screen Reader Support, große Icons
- HelpSystem: Mehrsprachige Hilfe und Tutorials

## ⚙️ Backend-Architektur

### **API Gateway (Port: 8000)**

**Technologie-Stack:**
- FastAPI + Uvicorn für moderne Python-API-Entwicklung
- Pydantic für robuste Datenvalidierung
- asyncio für hohe Concurrency-Performance
- WebSocket-Support für Echtzeit-Features

**Hauptmodule:**

**API-Endpunkte:**

**Unified Message Endpoint:** `POST /api/session/{session_id}/message`
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
  "audio_url": "/api/audio/uuid.wav",
  "input_type": "audio|text",
  "processing_time": 1.2,
  "timestamp": "2025-09-28T10:30:01Z"
}
```

**session_manager.py:**
- **SessionManager:** Single-Session-Policy mit automatischem Session-Cleanup
  - **Active Session Tracking:** Maximal eine aktive Admin-Session
  - **Session Termination Logic:** Automatisches Beenden bestehender Sessions
  - **WebSocket-Connection-Pool:** Verbindungsmanagement pro Session
  - **Graceful Disconnect:** Client-Benachrichtigung bei Session-Beendigung
  - **Broadcast-Funktionalität:** Echtzeit-Updates an alle Session-Teilnehmer
- **Session:** Single-Instance Session-Model
  - **State:** inactive → pending → active → terminated
  - **Language-Pair:** Admin (DE) ↔ Customer (selected language)
  - **Timeout-Management:** Automatische Cleanup nach Inaktivität
- **SessionMessage:** Nachrichten-Datenstrukturen mit differenzierter Text-Ausgabe
  - original_text: ASR-erkannter Text oder eingegebener Text (für Sprecher-Anzeige)
  - translated_text: Übersetzter Text (für Empfänger-Anzeige)
  - audio_data: Übersetzte Audio-Datei (für Empfänger-Wiedergabe)
- **ClientType:** Admin/Customer-Unterscheidung mit Role-basierter Session-Control

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

### **ASR Service (Port: 8001)**

**Whisper-basierte Spracherkennung:**

**Models:**
- whisper-base: Schnell, moderate Genauigkeit
- whisper-medium: Balance zwischen Speed und Accuracy
- whisper-large: Höchste Genauigkeit, langsamer

**Processing-Module:**
- audio_normalization: WAV-Konvertierung, Rauschreduzierung
- language_detection: Automatische Spracherkennung
- confidence_scoring: Qualitätsbewertung der Transkription

**API-Endpunkte:**
- /transcribe: Hauptendpunkt für Audio-zu-Text-Konvertierung
- /languages: Unterstützte Sprachen abrufen
- /health: Service-Status und GPU-Informationen

### **Translation Service (Port: 8002)**

**M2M100-basierte Übersetzung:**

**Models:**
- m2m100_418M: Schneller, weniger Speicherverbrauch
- m2m100_1.2B: Höhere Qualität, mehr Ressourcen benötigt

**Processing-Module:**
- text_chunking: Lange Texte intelligent aufteilen
- romanization: uroman für TTS-Vorbereitung
- quality_assessment: Übersetzungsqualität bewerten

**API-Endpunkte:**
- /translate: Text-zu-Text-Übersetzung
- /languages: 100+ unterstützte Sprachpaare
- /health: Model-Status und Performance-Metriken

### **TTS Service (Port: 8003)**

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

**API-Endpunkte:**
- /synthesize: Text-zu-Audio-Konvertierung (WAV)
- /voices: Verfügbare Stimmen pro Sprache
- /health: TTS-Model-Status und Verfügbarkeit

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
- traefik: Load Balancer + SSL-Terminierung
- api_gateway: Session-Management + Pipeline-Orchestration
- asr: Speech-to-Text Service
- translation: Text-to-Text Service
- tts: Text-to-Speech Service
- frontend-admin: Admin-Interface
- frontend-client: Customer-Interface
- prometheus: Metrics Collection
- grafana: Visualization Dashboard
- redis: Session Storage (optional)

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
- **Maximale Dauer:** 20 Sekunden
- **Dateigröße-Limit:** 3.2 MB (bei 20s WAV 16kHz)
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

**Session-Conflict-Handling:**
- **Problem:** Admin versucht neue Session zu starten während eine aktive existiert
- **Lösung:**
  - **Automatic Session Termination:** Bestehende Session wird sofort beendet
  - **Client Notification:** Aktive Client-Benutzer erhalten Disconnect-Message
  - **Graceful Cleanup:** WebSocket-Verbindungen ordnungsgemäß schließen
  - **Resource Liberation:** Memory und Redis-Keys der alten Session freigeben
- **User-Experience:** Nahtloser Übergang zur neuen Session ohne manuelle Eingriffe

**Session-Timeout-Handling:**
- **Problem:** Inaktive Sessions blockieren Ressourcen (bei Single-Session besonders kritisch)
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
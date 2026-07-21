# Project Context

## Purpose
Smart Speech Flow Backend ist ein containerisiertes Microservice-System für mehrsprachige Echtzeit-Kommunikation zwischen Verwaltungsmitarbeitern und Bürgern. Das System ermöglicht bidirektionale Sprachkommunikation mit automatischer Übersetzung in über 100 Sprachen durch eine vollständige Audio-Pipeline (ASR → Translation → TTS).

**Hauptziele:**
- Barrierefreie Kommunikation zwischen deutschsprachigen Verwaltungsmitarbeitern und mehrsprachigen Bürgern
- Session-basierte Gespräche mit persistenter Message-History
- Echtzeit-WebSocket-Kommunikation mit Polling-Fallback für mobile Clients
- GPU-beschleunigte KI-Inferenz für hohe Performance

## Tech Stack

### Backend Services
- **Python 3.12** - Hauptprogrammiersprache für alle Services
- **FastAPI** - Web-Framework für REST APIs und WebSocket-Endpunkte
- **Docker & Docker Compose** - Containerisierung und Service-Orchestrierung
- **Traefik** - Load Balancer und TLS-Termination (Let's Encrypt)
- **Redis** - Session-Persistierung und Message-Caching
- **NVIDIA CUDA 13.0** - GPU-Beschleunigung für KI-Modelle

### AI/ML Components
- **OpenAI Whisper** - Automatische Spracherkennung (ASR)
- **Facebook M2M100** - Mehrsprachige Übersetzung (100+ Sprachen)
- **Coqui-TTS & HuggingFace MMS-TTS** - Text-zu-Sprache-Synthese
- **Ollama (gpt-oss:20b)** - LLM-basierte Übersetzungsverfeinerung (optional)

### Infrastructure & Monitoring
- **Prometheus** - Metriken-Sammlung und Performance-Monitoring
- **Grafana** - Dashboard-Visualisierung und Alerting
- **pytest & pytest-asyncio** - Test-Framework für Unit-, Integrations-, Load- und Real-System-Tests
- **Pydantic** - Request/Response-Validierung und Type Safety

## Project Conventions

### Code Style
- **PEP-8-orientiert**; Black und isort konfigurieren 100 Zeichen, während die bestehenden Pre-commit-Hooks für Service-Code 88 Zeichen verwenden
- **Type Hints** für neue Gateway-Funktionen und Rückgabewerte; MyPy ist für `services.api_gateway.*` strikt und wird sonst schrittweise eingeführt
- **Pydantic Models** für API-Request/Response-Strukturen, wo praktikabel
- **Structured Logging** mit Emojis für bessere Lesbarkeit (🚀, ✅, ❌, ⚠️)
- **Docstrings** im Google-Style für öffentliche Funktionen und Klassen

### Architecture Patterns
- **Microservice-Architektur** mit Domain-spezifischen Services
- **API Gateway Pattern** für zentrale Request-Orchestrierung
- **Circuit Breaker Pattern** für Resilience gegen Service-Ausfälle
- **Session-based Communication** mit UUID-identifizierten Gesprächen
- **Hybrid REST/WebSocket** - REST für State-Management, WebSocket für Realtime
- **Unified Input Endpoint** - Content-Type-basierte Audio/Text-Verarbeitung

### Testing Strategy
- **Comprehensive Test Suite** für Gateway und einzelne Services
- **Unit Tests** für einzelne Komponenten und Business-Logic
- **Integration Tests** für Service-zu-Service-Kommunikation
- **Real System Tests** mit echten HTTP-Servern für Circuit Breaker
- **Mobile Optimization Tests** für adaptive Polling und Battery-Saving
- **Load Tests** für WebSocket- und Produktionslast
- **Test-Driven Development** für kritische Pipeline-Funktionen
- CI führt auf Python 3.12 einen hermetischen Test-Subset aus; Integration-, Load- und Real-System-Tests benötigen bei Bedarf eine passende lokale Umgebung

### Git Workflow
- **Feature Branches** für neue Entwicklungen
- **Main Branch** als produktiver Stand
- **Conventional Commits** für strukturierte Commit-Messages
- **Pull Request Reviews** vor Merge in Main
- **Automated Testing** in CI/CD-Pipeline
- Neue Capabilities, Breaking Changes und Architekturänderungen folgen dem OpenSpec-Workflow in `openspec/AGENTS.md`; vor der Implementierung ist eine genehmigte Proposal erforderlich

## Domain Context

### Session Management
- **Admin Sessions** - Deutschsprachige Verwaltungsmitarbeiter erstellen Sessions
- **Customer Activation** - Mehrsprachige Bürger treten über eine Session-URL bei; `customer` bezeichnet den Endnutzer, während `client` technischen Kontexten vorbehalten ist
- **Status Lifecycle** - Pending → Active → Terminated mit automatischen Timeouts
- **WebSocket Coordination** - Bidirektionale Echtzeit-Kommunikation zwischen Admin/Customer

### Multi-Language Processing
- **Language Detection** - Automatische Erkennung vs. explizite Auswahl
- **Translation Pipeline** - Deutsch ↔ 100+ Sprachen bidirektional
- **Audio Normalization** - Konsistente Lautstärke und Qualität
- **Format Support** - WAV, MP3, M4A mit automatischer Konvertierung

### Production Environment
- **Public URLs**: Frontend (`translate.smart-village.solutions`), API (`ssf.smart-village.solutions`)
- **GPU Hardware** - NVIDIA RTX 4000 SFF Ada Generation mit 20GB VRAM
- **High Availability** - Circuit Breaker, Graceful Degradation, Auto-Recovery
- **Monitoring Stack** - Prometheus/Grafana mit GPU-Metriken und Alerting

## Important Constraints

### Technical Constraints
- **GPU Memory Limits** - Shared 20GB VRAM zwischen ASR/Translation/TTS Services
- **WebSocket Protocol** - Erfordert HTTP/1.1 (nicht HTTP/2) für Upgrade-Header
- **Audio File Limits** - Max. 25MB, 0.1-120s Dauer, 16kHz/16bit/mono bevorzugt
- **Rate Limiting** - Standardmäßig maximal 50 Nachrichten pro Session alle 10 Sekunden; über Umgebungsvariablen konfigurierbar
- **Session Timeouts** - 30min Inaktivität führt zu automatischer Beendigung

### Business Constraints
- **Data Privacy** - Keine langfristige Speicherung von Audio-Daten; die produktive Compose-Konfiguration bereinigt Audio standardmäßig nach 24 Stunden
- **Language Support** - Primär Deutsch ↔ andere Sprachen (nicht Sprache A ↔ B)
- **User Types** - Klare Trennung zwischen Admin (intern) und Customer (extern)
- **Accessibility** - WCAG-konforme Benutzeroberflächen erforderlich

### Regulatory Constraints
- **GDPR Compliance** - EU-Datenschutz für Bürger-Sessions
- **Audio Retention** - Temporäre Verarbeitung und konfigurierbare, automatische Bereinigung ohne dauerhafte Aufbewahrung
- **Government Standards** - Compliance mit deutschen Verwaltungsrichtlinien

## External Dependencies

### Cloud Services
- **Let's Encrypt** - Automatische TLS-Zertifikate für HTTPS
- **Docker Hub** - Container-Images für Base-Services (Redis, Traefik, Prometheus)
- **HuggingFace Hub** - KI-Modell-Downloads (M2M100, MMS-TTS, Whisper)

### Hardware Dependencies
- **NVIDIA GPU** - CUDA-kompatible Grafikkarte für KI-Inferenz empfohlen
- **High-Memory System** - Min. 32GB RAM für parallele Modell-Ladung
- **SSD Storage** - Schneller Speicher für Modell-Caching und Temp-Files

### Network Dependencies
- **Domain Names** - `translate.smart-village.solutions`, `ssf.smart-village.solutions`
- **Port Requirements** - 80/443 für Web, 8000-8003 für lokale bzw. interne Service-Kommunikation
- **Internet Connectivity** - Für Modell-Downloads und Let's Encrypt

# Smart Speech Flow Backend

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-compose-blue.svg)](https://docs.docker.com/compose/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)

Ein containerisiertes Microservice-Backend für Echtzeit-Sprachverarbeitung und Übersetzung. Das System besteht aus vier eigenständigen Services, die über ein API-Gateway orchestriert werden und eine vollständige Pipeline von Sprache zu Sprache ermöglichen.

## ✨ Features at a Glance

- 🎤 **Automatic Speech Recognition** – Transkription mit OpenAI Whisper
- 🌍 **Multi-Language Translation** – 100+ Sprachen mit Facebook M2M100
- 🔊 **Text-to-Speech** – Natürliche Sprachsynthese mit Coqui-TTS & HuggingFace MMS
- ⚡ **GPU-Accelerated** – CUDA-Support für optimale Performance
- 🔄 **WebSocket Real-Time** – Live-Kommunikation für Admin & Customer
- 📊 **Production Monitoring** – Prometheus & Grafana Integration
- 🎛️ **LLM Refinement** – Optional mit Ollama (gpt-oss:20b)
- 🐳 **Cloud-Ready** – Vollständig containerisiert mit Docker Compose

## 🚀 Quick Start

```bash
# 1. Repository klonen
git clone https://github.com/smart-village-solutions/smart-speech-flow-backend.git
cd smart-speech-flow-backend

# 2. Services starten (Docker Compose)
docker compose up -d

# 3. Health-Check
curl http://localhost:8000/health
```

**Das war's!** Die API ist unter `http://localhost:8000` verfügbar.

### Erste API-Anfrage

```bash
# Pipeline testen: Deutsch → Englisch
curl -F "file=@examples/audio/sample.wav" \
     -F "source_lang=de" \
     -F "target_lang=en" \
     http://localhost:8000/pipeline \
     --output translated.wav
```

## 📚 Documentation

**Start here:**
- 📖 [Documentation Index](docs/README.md) – Navigation by role & topic
- 🧪 [Testing Guide](docs/testing/TESTING_GUIDE.md) – Comprehensive test overview
- 🏗️ [System Architecture](docs/architecture/SYSTEM_ARCHITECTURE.md) – Design decisions
- 🔌 [Frontend Integration](docs/guides/frontend-integration.md) – WebSocket & API usage

**For contributors:**
- 🤝 [Contributing Guide](CONTRIBUTING.md) – Get started in 3 steps
- 🗺️ [Project Roadmap](ROADMAP.md) – v1.0 features & future plans
- 📜 [Code of Conduct](CODE_OF_CONDUCT.md) – Community guidelines

## 🏗️ Architektur & Services

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Frontend      │────│ API Gateway  │────│   Traefik       │
│   (React)       │    │   (FastAPI)  │    │  (Load Balancer)│
│   Port: 5173    │    │  Port: 8000  │    │   Port: 80/443  │
└─────────────────┘    └──────────────┘    └─────────────────┘
            │
        ┌───────────────┼───────────────────────────┐
        │               │                           │
      ┌────▼────┐    ┌─────▼─────┐   ┌────▼────┐   ┌────▼────┐
      │   ASR   │    │Translation│   │   TTS   │   │ Ollama  │
      │(Whisper)│    │  (M2M100) │   │(Coqui)  │   │(Refiner)│
      │Port:8001│    │ Port:8002 │   │Port:8003│   │Port:11434│
      └─────────┘    └───────────┘   └─────────┘   └─────────┘
```

### 1. ASR Service (Speech-to-Text)
- **Port:** 8001
- **Funktion:** Automatische Spracherkennung für verschiedene Sprachen und Audioformate
- **Modelle:** Whisper, Wav2Vec, etc. (lokal geladen)
- **Endpunkte:** `/transcribe` (POST), `/health` (GET), `/metrics` (GET), `/languages` (GET)
- **Beispiel:**
   ```bash
   curl -F "file=@sample.wav" http://localhost:8001/transcribe
   ```

### 2. Translation Service
- **Port:** 8002
- **Funktion:** KI-basierte Übersetzung mit Facebooks m2m100_1.2B-Modell
- **Endpunkte:** `/translate` (POST), `/languages` (GET), `/health` (GET), `/metrics` (GET)
- **Beispiel:**
   ```bash
   curl -X POST http://localhost:8002/translate \
          -H "Content-Type: application/json" \
          -d '{"text": "Hallo Welt", "source_lang": "de", "target_lang": "en"}'
   ```

### 3. TTS Service (Text-to-Speech)
- **Port:** 8003
- **Funktion:** Sprachsynthese für viele Sprachen mit Coqui-TTS und HuggingFace MMS-TTS
- **Endpunkte:** `/synthesize` (POST), `/health` (GET), `/metrics` (GET)
- **Beispiel:**
   ```bash
   curl -X POST http://localhost:8003/synthesize \
          -H "Content-Type: application/json" \
          -d '{"text": "Hello world", "lang": "en"}' --output out.wav
   ```

### 4. API-Gateway
- **Port:** 8000
- **Funktion:** Zentrales REST-API für alle Sprachdienste
- **Endpunkte:** `/pipeline` (POST), `/upload` (POST), `/health` (GET), `/metrics` (GET)
- **Pipeline:** Orchestriert die gesamte Pipeline: ASR → Translation → TTS
- **Beispiel für End-to-End:**
   ```bash
   curl -F "file=@sample.wav" -F "source_lang=de" -F "target_lang=en" http://localhost:8000/pipeline --output output.wav
   ```

### 5. Session Store (Redis)
- **Port:** 6379 (intern via Docker-Netzwerk)
- **Funktion:** Persistente Ablage der Sessions, Nachrichten & Timeout-Metadaten
- **Besonderheiten:** AOF aktiviert, Fallback auf In-Memory-Store falls Redis nicht erreichbar
- **Konfiguration:** `REDIS_URL` & `REDIS_NAMESPACE` steuern Ziel-Instance und Namensraum

### 6. Ollama Translation Refinement (optional)
- **Port:** 11434
- **Funktion:** LLM-basierte Nachbearbeitung von Übersetzungen mit `gpt-oss:20b`
- **GPU:** Nutzt über das NVIDIA Container Toolkit die vorhandenen GPUs automatisch
- **Aktivierung:** `LLM_REFINEMENT_ENABLED=true` am API-Gateway setzen
- **Vorbereitung:** Modell einmalig laden via `docker compose exec ollama ollama pull gpt-oss:20b`

## 🔄 Pipeline-Workflow

1. **ASR:** Audiodatei wird in Text transkribiert
2. **Translation:** Transkribierter Text wird in die Zielsprache übersetzt (mit Romanisierung für TTS)
3. **(Optional) LLM-Veredelung:** Bei aktivem Flag wird der Übersetzungstext über Ollama nachbearbeitet
4. **TTS:** Übersetzter Text wird als Sprache synthetisiert (WAV)
5. **API-Gateway:** Orchestriert alle Schritte und gibt die finale WAV-Datei zurück

## 📋 Endpunkte Übersicht

| Service        | Endpunkt         | Methode | Beschreibung                       |
|----------------|------------------|---------|------------------------------------|
| ASR            | `/transcribe`    | POST    | Audiodatei → Text                  |
| ASR            | `/languages`     | GET     | Unterstützte Sprachen              |
| ASR            | `/health`        | GET     | Status, Modellinfos                |
| ASR            | `/metrics`       | GET     | Monitoring                         |
| Translation    | `/translate`     | POST    | Textübersetzung                    |
| Translation    | `/languages`     | GET     | Unterstützte Sprachen              |
| Translation    | `/health`        | GET     | Status, Modellinfos                |
| Translation    | `/metrics`       | GET     | Monitoring                         |
| TTS            | `/synthesize`    | POST    | Text → Sprache (WAV)               |
| TTS            | `/health`        | GET     | Status, Modellinfos                |
| TTS            | `/metrics`       | GET     | Monitoring                         |
| API-Gateway    | `/pipeline`      | POST    | End-to-End (ASR → Trans → TTS)     |
| API-Gateway    | `/upload`        | POST    | Upload mit HTML-Response           |
| API-Gateway    | `/health`        | GET     | Status aller Services              |
| API-Gateway    | `/metrics`       | GET     | Monitoring                         |

## 🛠️ Installation & Setup

### Prerequisites
- **Docker & Docker Compose** (v2.x recommended)
- **16GB+ RAM** (for AI models)
- **20GB disk space** (for models and containers)
- **NVIDIA GPU** (optional, for faster inference)
- **NVIDIA Container Toolkit** (for GPU support)

### GPU Setup (Optional but Recommended)

For optimal performance with NVIDIA GPU:

```bash
# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Verify GPU access
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi
```

### Local Development (without Docker)

```bash
# Python Virtual Environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Start individual services
uvicorn services/asr/app:app --port 8001 --reload
uvicorn services/translation/app:app --port 8002 --reload
uvicorn services/tts/app:app --port 8003 --reload
uvicorn services/api_gateway/app:app --port 8000 --reload
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/integration/  # Integration tests
pytest tests/test_admin_routes.py  # Admin API tests
pytest tests/test_openapi_validation.py  # OpenAPI contract tests

# Run with coverage
pytest --cov=services --cov-report=html

# Run load tests (manual only)
pytest tests/load/
```

**Test Status:** 234/242 tests passing (96.7%) – See [TEST_STATUS.md](TEST_STATUS.md)

**Learn more:** [Testing Guide](docs/testing/TESTING_GUIDE.md)


## � Monitoring & Operations

### Quick Access
- **Prometheus:** `http://prometheus-ssf.smart-village.solutions` (metrics aggregation)
- **Grafana:** `http://grafana-ssf.smart-village.solutions` (dashboards, login: `admin`/`admin`)
- **Service Metrics:** `http://localhost:8000/metrics` (each service exposes metrics)

### Dashboards
Pre-built Grafana dashboards in `monitoring/grafana/dashboards/`:
- `service-health.json` – Service status & uptime
- `pipeline-performance.json` – Latency & throughput
- `dcgm-exporter.json` – GPU monitoring (temperature, memory, utilization)

### Alerting
Prometheus alerts configured in `monitoring/alert_rules.yml`:
- **ServiceDown** – Service unreachable for 2+ minutes
- **TranslationLatencyHigh** – Translation taking >10s (p95)
- **GPUUtilisationCritical** – GPU >90% for 5+ minutes
- **GPUMemoryPressure** – GPU memory >85%

**Runbook:** See [Operations Documentation](docs/operations/) for troubleshooting procedures.

### GPU Monitoring (DCGM Exporter)

```bash
# Start monitoring stack
docker compose up -d prometheus grafana dcgm_exporter

# Check GPU metrics
curl http://localhost:9400/metrics | grep DCGM

# View in Grafana (after importing dcgm-exporter.json)
# Access: http://localhost:3000
```

**Prerequisites:** NVIDIA driver + NVIDIA Container Toolkit installed.

## 🎵 Unterstützte Audioformate

Der ASR-Service akzeptiert nicht nur WAV-Dateien, sondern auch weitere Audioformate:
- **WAV** (bevorzugt)
- **MP3**
- **OGG**
- **FLAC**
- **Weitere gängige Formate**

Die Format-Erkennung erfolgt automatisch beim Upload. Die Rückgabe erfolgt immer als WAV-Datei (synthetisierte Sprache).

**Beispiel für MP3-Upload:**
```bash
curl -F "file=@sample.mp3" -F "source_lang=de" -F "target_lang=en" http://localhost:8000/pipeline --output output.wav
```

## 🌐 Integration Frontend: Spracheingabe und Ausgabe

### 1. Spracheingabe und Datei-Upload

Das Frontend muss beim Upload einer Audiodatei die Ausgangs- und Zielsprache als Formularfelder mitsenden:

```html
<form action="/upload" method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept=".wav,.mp3,.ogg,.flac" required>
  <select name="source_lang" required>
    <option value="de">Deutsch</option>
    <option value="en">Englisch</option>
    <!-- weitere Sprachen ... -->
  </select>
  <select name="target_lang" required>
    <option value="en">Englisch</option>
    <option value="de">Deutsch</option>
    <!-- weitere Sprachen ... -->
  </select>
  <button type="submit">Senden</button>
</form>
```

**JavaScript-Alternative:**
```js
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('source_lang', sourceLangSelect.value);
formData.append('target_lang', targetLangSelect.value);

fetch('/upload', {
  method: 'POST',
  body: formData
});
```

### 2. Backend-Response: Ergebnisstruktur

Nach erfolgreichem Upload liefert das Backend eine HTML-Seite mit:
- **Transkription:** Originalsprache (z.B. Deutsch)
- **Übersetzung:** Zielsprache (z.B. Englisch)
- **Download-Link:** für die synthetisierte WAV-Datei
- **Audio-Player:** zur direkten Wiedergabe

```html
<p>Transkription: Hallo Welt</p>
<p>Übersetzung: Hello world</p>
<a href="data:audio/wav;base64,..." download="output.wav">WAV herunterladen</a>
<audio controls src="data:audio/wav;base64,..."></audio>
```

### 3. API-Endpunkt für externe Clients

Für reine API-Nutzung kann der `/pipeline`-Endpunkt genutzt werden:

```js
fetch('/pipeline', {
  method: 'POST',
  body: formData
})
.then(res => res.blob())
.then(blob => {
  // WAV-Datei speichern oder abspielen
});
```

### 4. Fehlerbehandlung

Falls die Sprachparameter fehlen oder ungültig sind, liefert das Backend eine Fehlermeldung als HTML. Das Frontend sollte diese anzeigen und den Nutzer zur Auswahl der Sprachen auffordern.

**Wichtige Hinweise für das Frontend:**
- Immer beide Sprachparameter mitsenden (`source_lang`, `target_lang`)
- Ergebnis enthält Originaltext, Übersetzung und Audio (WAV, base64)
- Fehler werden als HTML zurückgegeben
- Das Formularfeld muss `file` heißen

## 🤖 Modellübersicht

Eine ausführliche Dokumentation zu den in den Services verwendeten KI-Modellen, deren Quellen und Lizenzen findest du unter [models.md](./models.md).

### Hauptmodelle
- **ASR:** OpenAI Whisper (verschiedene Größen)
- **Translation:** Facebook M2M100 (1.2B Parameter)
- **TTS:** Coqui-TTS (europäische Sprachen), HuggingFace MMS-TTS (weitere Sprachen)

## 📊 Monitoring & Betrieb

### Prometheus-Metriken
- **Request Latenz:** Durchschnittliche Antwortzeiten pro Service
- **Fehlerrate:** HTTP-Fehler und Ausnahmen
- **GPU-Auslastung:** VRAM und Compute-Nutzung
- **Systemressourcen:** CPU, RAM, Disk I/O

**Zugriff:** Prometheus-kompatible Metriken unter `/metrics` je Service

### Grafana-Dashboard
- **Zugriff:** `http://localhost:3000`
- **Features:** Echtzeit-Metriken, Performance-Trends, Alerting
- **Konfiguration:** Siehe Ordner `monitoring/`

### Health-Checks
```bash
# Alle Services prüfen
curl http://localhost:8000/health

# Einzelne Services
curl http://localhost:8001/health  # ASR
curl http://localhost:8002/health  # Translation
curl http://localhost:8003/health  # TTS
```

## 🐛 Troubleshooting

### Common Issues

**GPU not detected:**
```bash
# Check GPU visibility
nvidia-smi

# Test Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.2.0-runtime-ubuntu22.04 nvidia-smi

# Check in container
docker compose exec asr python3 -c "import torch; print(torch.cuda.is_available())"
```

**Services not starting:**
```bash
# Check logs
docker compose logs <service_name>

# Restart services
docker compose restart

# Rebuild from scratch
docker compose down -v
docker compose up --build
```

**Performance issues:**
- Enable GPU acceleration (see GPU Setup above)
- Increase Docker memory limits in docker-compose.yml
- Use smaller models for faster inference
- Check GPU memory usage: `nvidia-smi`

### Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 400 | Invalid input | Check request format and parameters |
| 503 | Service unavailable | Wait for model loading or check resources |
| 500 | Internal error | Check logs and system resources |

**More help:** See [Operations Runbooks](docs/operations/runbooks/)

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- Development setup (3 steps)
- Code style guidelines (black, isort, flake8)
- Testing requirements
- Pull request process

**First-time contributors:** Look for issues labeled `good-first-issue`.

## � License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🗺️ What's Next?

See our [ROADMAP.md](ROADMAP.md) for:
- ✅ Completed v1.0 features
- 🚧 Planned improvements
- 🎯 Future milestones

## 👥 Contact & Support

**Smart Village Solutions**

- 📧 Email: [Contact via GitHub Issues](https://github.com/smart-village-solutions/smart-speech-flow-backend/issues)
- 🐛 Bug Reports: [GitHub Issues](https://github.com/smart-village-solutions/smart-speech-flow-backend/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/smart-village-solutions/smart-speech-flow-backend/discussions)

---

**Built with ❤️ by Smart Village Solutions** | Last updated: November 2025 | Version 1.0.0

## � WebSocket Architecture

### Singleton Pattern

Das System verwendet einen **zentralen WebSocketManager** als Singleton-Instanz:

```python
from services.api_gateway.websocket import get_websocket_manager

# FastAPI Dependency Injection
async def some_route(manager: WebSocketManager = Depends(get_websocket_manager)):
    # Manager wird automatisch injiziert
    await manager.broadcast_message_to_session(...)
```

**Vorteile:**
- Eine zentrale Instanz verwaltet alle WebSocket-Verbindungen
- Konsistente Session-Verwaltung über alle Endpunkte
- Keine Race Conditions durch mehrfache Manager-Instanzen
- Dependency Injection garantiert korrekte Initialisierung

### Message Broadcasting

Nachrichten werden **differenziert** an Admin und Customer gesendet:

```python
result = await manager.broadcast_with_differentiated_content(
    session_id="ABC12345",
    admin_message={"type": "message", "text": "Original", ...},
    customer_message={"type": "message", "text": "Translated", ...}
)

# BroadcastResult validiert Erfolg:
# - success: bool (True wenn mindestens eine Verbindung erreicht)
# - total_connections: int (Admin + Customer Verbindungen)
# - successful_sends: int (Erfolgreich zugestellt)
# - failed_sends: int (Fehlerhafte Zustellungen)
```

**Monitoring:** Prometheus-Metriken unter `/metrics`:
- `websocket_broadcast_total` - Anzahl Broadcasts pro Session
- `websocket_broadcast_success_total` - Erfolgreiche Broadcasts
- `websocket_broadcast_failure_total` - Fehlgeschlagene Broadcasts
- `websocket_broadcast_messages_delivered_total` - Zugestellte Nachrichten

### Connection Management

WebSocket-Verbindungen werden pro Session und Rolle verwaltet:

```
/ws/{session_id}/{connection_type}
```

- `connection_type`: `admin` oder `customer`
- Automatisches Heartbeat-System (30s Intervall)
- Reconnection-Handling im Frontend erforderlich

**Best Practices für Frontend:**
- WebSocket-Verbindung nach Aktivierung öffnen
- Heartbeat-Pongs implementieren
- Bei Verbindungsabbruch automatisch reconnecten
- Message-Queue für offline-Nachrichten

### Troubleshooting

**Problem:** Nachrichten kommen nicht an (0% Delivery)

**Lösung:**
1. Container-Logs prüfen: `docker logs ssf-backend_api_gateway_1`
2. Prometheus Metrics checken: `curl http://localhost:9090/api/v1/query?query=websocket_broadcast_failure_total`
3. WebSocket-Verbindung im Browser-DevTools prüfen
4. Container neu starten: `docker-compose up -d --force-recreate api_gateway`

**Problem:** "WebSocketManager ist None" Fehler

**Lösung:**
- Manager wird via Dependency Injection bereitgestellt
- `get_websocket_manager()` in FastAPI-Routes verwenden
- Keine globalen Manager-Variablen verwenden

**Problem:** Container-Restart schlägt fehl (KeyError: 'ContainerConfig')

**Lösung:**
```bash
# Workaround für Docker Compose Bug
docker-compose up -d --no-deps --force-recreate api_gateway
docker start ssf-backend_redis_1
docker start ssf-backend_ollama_1
```

## �📄 Lizenz

MIT

## 👥 Kontakt

Smart Village Solutions

---

**Letztes Update:** November 2025 | **Version:** 1.1.0

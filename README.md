# Smart Speech Flow Backend

Ein containerisiertes Microservice-Backend für Echtzeit-Sprachverarbeitung und Übersetzung. Das System besteht aus vier eigenständigen Services, die über ein API-Gateway orchestriert werden und eine vollständige Pipeline von Sprache zu Sprache ermöglichen.

## 🚀 Überblick

Smart Speech Flow ermöglicht es, gesprochene Inhalte automatisch zu transkribieren, zwischen über 100 Sprachen zu übersetzen und als natürliche Sprache auszugeben. Jeder Service ist in Python/FastAPI implementiert und kann einzeln oder als Gesamtpipeline genutzt werden.

### Hauptfunktionen
- **Automatische Spracherkennung (ASR)** mit OpenAI Whisper
- **Mehrsprachige Übersetzung** mit Facebook M2M100 (100+ Sprachen)
- **Text-zu-Sprache (TTS)** mit Coqui-TTS und HuggingFace MMS-TTS
- **GPU-beschleunigte KI-Inferenz** mit CUDA-Unterstützung
- **Echtzeit-Monitoring** mit Prometheus und Grafana
- **Vollständige Pipeline-Orchestrierung** über API-Gateway

## 🏗️ Architektur & Services

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────┐
│   Frontend      │────│ API Gateway  │────│   Traefik       │
│   (React)       │    │   (FastAPI)  │    │  (Load Balancer)│
│   Port: 5173    │    │  Port: 8000  │    │   Port: 80/443  │
└─────────────────┘    └──────────────┘    └─────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
         ┌────▼────┐    ┌─────▼─────┐   ┌────▼────┐
         │   ASR   │    │Translation│   │   TTS   │
         │(Whisper)│    │  (M2M100) │   │(Coqui)  │
         │Port:8001│    │ Port:8002 │   │Port:8003│
         └─────────┘    └───────────┘   └─────────┘
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

## 🔄 Pipeline-Workflow

1. **ASR:** Audiodatei wird in Text transkribiert
2. **Translation:** Transkribierter Text wird in die Zielsprache übersetzt (mit Romanisierung für TTS)
3. **TTS:** Übersetzter Text wird als Sprache synthetisiert (WAV)
4. **API-Gateway:** Orchestriert alle Schritte und gibt die finale WAV-Datei zurück

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

## 🛠️ Installation & Start

### Voraussetzungen
- Docker & Docker Compose
- NVIDIA GPU mit CUDA-Unterstützung (optional, aber empfohlen)
- NVIDIA Container Toolkit für GPU-Zugriff
- Mindestens 16GB RAM (für KI-Modelle)
- 20GB freier Speicherplatz

### Mit Docker Compose (empfohlen)
```bash
# Repository klonen
git clone <repository-url>
cd ssf-backend

# Services starten
docker compose up --build
```

### GPU-Setup (optional)

Für optimale Performance mit NVIDIA GPU:

```bash
# NVIDIA Container Toolkit installieren
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# GPU-Status prüfen
nvidia-smi
```

### Einzelne Services lokal starten
```bash
# Python Virtual Environment
python -m venv .venv
source .venv/bin/activate

# Services einzeln starten
uvicorn services/asr/app:app --port 8001 &
uvicorn services/translation/app:app --port 8002 &
uvicorn services/tts/app:app --port 8003 &
uvicorn services/api_gateway/app:app --port 8000 &
```

### Testen
```bash
# Alle Tests ausführen
pytest

# Einzelne Services
pytest services/asr/tests/
pytest services/translation/tests/
pytest services/tts/tests/
pytest services/api_gateway/tests/

# Mit Coverage
pytest --cov=services
```

## 📈 Monitoring & Alerting Runbook

- **Stack starten:** `docker compose up -d prometheus grafana` startet Prometheus (Port `9090`, öffentlich via `http://prometheus-ssf.smart-village.solutions`) und Grafana (Port `3000`, öffentlich via `http://grafana-ssf.smart-village.solutions`). Standard-Login: `admin` / `admin` (bitte nach dem ersten Login ändern).
- **Datenquellen:** In Grafana eine Prometheus-Datenquelle mit URL `http://prometheus:9090` anlegen (falls nicht automatisch vorhanden).
- **Dashboards importieren:** Die produktionsfertigen JSON-Dashboards liegen in `monitoring/grafana/dashboards/` (`service-health.json`, `pipeline-performance.json`). Über *Dashboards → Import* in Grafana laden.
- **Alerting:** Prometheus lädt `monitoring/alert_rules.yml` automatisch und feuert Alerts für Service-Ausfälle, erhöhte Übersetzungs-Latenzen sowie GPU-Überlast. Aktive Alarme erscheinen im Dashboard *SSF Service Health* und im Prometheus `ALERTS`-Endpoint.
- **Runbook:** Bei `ServiceDown`-Alerts zuerst `services/<service>/app.py` Logs prüfen, anschließend GPU-Auslastung im Dashboard kontrollieren. `TranslationLatencyHigh` deutet auf Pipeline-Stau hin – Skalierung über GPU-Worker oder Anfragen drosseln. `GPUUtilisationCritical`/`GPUMemoryPressure` signalisiert Ressourcengrenzen; Workload verteilen oder Modelle entladen.

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

### GPU-Probleme
```bash
# GPU-Status prüfen
nvidia-smi

# Docker GPU-Test
docker run --rm --gpus all nvidia/cuda:13.0.0-cudnn-runtime-ubuntu22.04 nvidia-smi

# In Container prüfen
docker compose exec asr python3 -c "import torch; print(torch.cuda.is_available())"
```

### Performance-Optimierung
- **GPU verwenden:** Deutlich schnellere Inferenz
- **Batch-Processing:** Mehrere Texte gleichzeitig übersetzen
- **Model-Caching:** Models werden automatisch geladen und gecacht
- **Resource Limits:** In docker-compose.yml anpassen

### Häufige Fehlercodes
| Code | Bedeutung | Lösung |
|------|-----------|--------|
| 400 | Ungültige Eingabe | Prüfe Request-Format und Parameter |
| 503 | Service nicht verfügbar | Warte auf Model-Loading oder prüfe Ressourcen |
| 500 | Interne Fehler | Prüfe Logs und Systemressourcen |

## 🔧 Development

### Code Quality
```bash
# Linting
flake8 services/
pylint services/

# Komplexitätsanalyse
radon cc services/

# Formatting
black services/
isort services/
```

### Unterstützte Sprachen
Die unterstützten Sprachen sind je Service unter `/languages` abrufbar:
```bash
curl http://localhost:8001/languages  # ASR
curl http://localhost:8002/languages  # Translation
```

## 💡 Hinweise & Tipps

- **GPU-Beschleunigung:** Container mit GPU-Support starten für bessere Performance
- **Eigene Modelle:** Können im Ordner `models/` abgelegt werden
- **Versionierung:** `.venv` und Modelle sind nicht versioniert (siehe `.gitignore`)
- **Private Modelle:** Bei gated HuggingFace-Modellen: `huggingface-cli login`
- **Sprachunterstützung:** Vollständige Liste unter `/languages`-Endpunkten
- **Audioformate:** Alle gängigen Formate werden automatisch erkannt

## 📁 Projektstruktur

```
ssf-backend/
├── services/
│   ├── api_gateway/          # Zentrale API und Pipeline-Orchestrierung
│   ├── asr/                  # Spracherkennung (Whisper)
│   ├── translation/          # Übersetzung (M2M100)
│   └── tts/                  # Text-zu-Sprache (Coqui/MMS)
├── frontend/                 # React Frontend
├── examples/                 # Audio-Beispieldateien
├── monitoring/               # Grafana-Konfiguration
├── docker-compose.yml        # Service-Orchestrierung
├── traefik.yml              # Load Balancer Config
├── models.md                # Modell-Dokumentation
└── README.md                # Diese Datei
```

## 📄 Lizenz

MIT

## 👥 Kontakt

Smart Village Solutions

---

**Letztes Update:** September 2025 | **Version:** 1.0.0

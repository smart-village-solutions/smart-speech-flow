# Smart Speech Flow Backend

Dieses Projekt ist ein modernes, containerisiertes Microservice-Backend für Echtzeit-Sprachübersetzung. Es besteht aus mehreren Services, die jeweils in eigenen Docker-Containern laufen und über eine API orchestriert werden.

## Features
- **ASR (Speech-to-Text):** Automatische Spracherkennung mit Whisper
- **Translation:** Übersetzung mit HuggingFace Transformers
- **TTS (Text-to-Speech):** Sprachsynthese mit Coqui TTS (Deutsch/Englisch)
- **API-Gateway:** Orchestriert die gesamte Pipeline und liefert direkt WAV-Audio
- **Monitoring:** Prometheus/Grafana für Health und Metriken
- **Docker-Compose:** Einfache Orchestrierung aller Services
- **Fallback-Logik:** Robuste Fehlerbehandlung und Debug-Ausgaben

## Schnellstart

1. **Voraussetzungen:**
   - Docker & Docker Compose
   - (Optional für GPU) NVIDIA-Treiber und nvidia-docker

2. **Projekt starten:**
   ```bash
   docker compose up --build
   ```

3. **Testen der Pipeline:**
   ```bash
   curl -F "file=@sample.wav" http://localhost:8000/speech-translate -o output.wav
   ```
   Das Ergebnis ist eine WAV-Datei mit der übersetzten und synthetisierten Sprache.

## Endpunkte
- `/health` – Status und GPU-Info je Service
- `/metrics` – Prometheus-Metriken
- `/transcribe` – ASR-Service
- `/translate` – Translation-Service
- `/synthesize` – TTS-Service
- `/speech-translate` – API-Gateway (End-to-End)

## Entwicklung
- Python 3.10
- FastAPI
- TTS, transformers, torch, soundfile, numpy, etc.
- Siehe `requirements.txt` je Service

## Hinweise
- `.venv` und Modelle werden nicht versioniert (siehe `.gitignore`)
- Für GPU-Nutzung: Container mit GPU-Support starten
- Für eigene Modelle: Ordner `models/` verwenden

## Lizenz
MIT

## Kontakt
Smart Village Solutions

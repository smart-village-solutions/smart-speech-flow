## Schnittstelle: Input und Output

### Input
- **/transcribe (POST)**
  - `file`: Audiodatei (WAV, MP3, OGG, FLAC, etc.)
  - `lang`: Sprache der Audiodatei (optional, z. B. `de`, `en`, `ar`, ...)
  - Übergabe als `multipart/form-data`

Beispiel:
```bash
curl -F "file=@sample.wav" -F "lang=de" http://localhost:8001/transcribe
```

### Output
- **Erfolgreiche Antwort (JSON):**
  ```json
  {
    "success": true,
    "text": "Hier spricht die Polizei.",
    "lang": "de"
  }
  ```
- **Fehlerhafte Antwort (JSON):**
  ```json
  {
    "success": false,
    "error": "Fehlermeldung"
  }
  ```

---

# ASR Service

Dieser Service bietet automatische Spracherkennung (Automatic Speech Recognition, ASR) als eigenständigen Microservice. Die Implementierung basiert auf FastAPI und unterstützt verschiedene Sprachen und Audioformate. Der Service ist für den produktiven Einsatz in einer Microservice-Architektur konzipiert und bietet Monitoring sowie Health-Checks.

## Features
- **Spracherkennung für viele Sprachen**
- **REST API mit `/transcribe`, `/health`, `/metrics` und weiteren Endpunkten**
- **Prometheus-Metriken für Monitoring**
- **Docker- und venv-ready**
- **Automatisierte Tests für alle Endpunkte und Sprachen**

## Endpunkte
### `/transcribe` (POST)
Transkribiert eine Audiodatei in Text.

### `/health` (GET)
Gibt den Status des Dienstes, unterstützte Sprachen und Modellinfos zurück.

### `/metrics` (GET)
Prometheus-kompatible Metriken für Monitoring.

### Weitere Endpunkte
- `/supported-languages` (GET): Gibt alle unterstuetzten Sprachen zurueck.

## Architektur & Funktionsweise
1. **Modellwahl:**
   - Die Spracherkennung erfolgt über lokal geladene Modelle (z. B. Whisper, Wav2Vec, etc.), je nach Konfiguration in `app.py`.
   - Die Verarbeitung erfolgt immer lokal, keine Daten werden an externe APIs gesendet.
2. **Caching:**
   - Geladene Modelle werden im Speicher gehalten, um die Performance zu optimieren.
3. **Fallback-Handling:**
   - Falls kein Modell für eine Sprache verfügbar ist, wird ein klarer Fehler mit Status 503 zurückgegeben.

## Installation & Betrieb
### Mit Docker
```bash
docker build -t asr-service .
docker run -p 8000:8000 asr-service
```

### Lokal mit venv
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

## Testen
```bash
pytest tests/
```

## Erweiterung
- Weitere Sprachen können einfach ergänzt werden, sofern ein passendes Modell verfügbar ist.
- Die Modellkonfiguration erfolgt in `app.py`.

## Hinweise
- Die unterstuetzten Sprachen sind in `/supported-languages` abrufbar.
- Bei privaten/gated Modellen ist ggf. ein HuggingFace-Token nötig (`huggingface-cli login`).

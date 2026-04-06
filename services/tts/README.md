# TTS Service

Dieser Service bietet eine robuste Text-zu-Sprache-Schnittstelle für verschiedene Sprachen und ist als eigenständiger Microservice konzipiert. Die Implementierung basiert auf FastAPI und unterstützt sowohl Coqui-TTS als auch HuggingFace MMS-TTS als Fallback.

## Input / Output
- **Input:**
  - Text (String, Pflichtfeld)
  - Sprachcode (`lang`, z. B. 'de', 'en', 'ar')
- **Output:**
  - Bei Erfolg: Audiodatei (WAV)
  - Bei Fehler: JSON mit Fehlermeldung und Fallback-Status

## Features
- **Text-to-Speech (TTS) für viele Sprachen**
- **Automatischer Fallback:** Coqui-TTS für direkt unterstützte Sprachen, HuggingFace MMS-TTS für alle weiteren
- **REST API mit `/synthesize`, `/health`, `/metrics` und `/supported-languages`**
- **Prometheus-Metriken**
- **Docker- und venv-ready**
- **Automatisierte Tests für alle Zielsprachen**

## Unterstützte Sprachen
- Coqui-TTS: Deutsch (de), Englisch (en), Türkisch (tr), Persisch (fa), Ukrainisch (uk)
- HuggingFace MMS-TTS: Arabisch (ar), Kurdisch (ku), Tigrinya (ti), Amharisch (am), Russisch (ru) und weitere, sofern ein Modell verfügbar ist

## Endpunkte
### `/synthesize` (POST)
Erzeugt eine Sprachdatei aus Text.
- **Payload:**
  ```json
  {
    "text": "Hallo Welt",
    "lang": "de"
  }
  ```
  Alternativ akzeptiert der Service auch `tts_text` statt `text`.
- **Antwort:**
  - Bei Erfolg: WAV-Datei
  - Bei Fehler: JSON mit Fehlermeldung und Fallback-Status

### `/health` (GET)
Gibt den Status des Dienstes, geladene Modelle und GPU-Infos zurück.

### `/metrics` (GET)
Prometheus-kompatible Metriken für Monitoring.

### `/supported-languages` (GET)
Gibt die verfuegbaren Sprachcodes fuer Coqui-TTS und MMS-Fallback zurueck.

## Architektur & Funktionsweise
1. **Modellwahl:**
   - Zuerst wird versucht, ein Coqui-TTS-Modell für die gewünschte Sprache zu laden.
   - Falls nicht verfügbar, wird automatisch HuggingFace MMS-TTS mit dem passenden ISO-639-3 Sprachcode verwendet.
   - Die Synthese erfolgt immer lokal, keine Daten werden an externe APIs gesendet.
2. **Caching:**
   - Geladene Modelle werden im Speicher gehalten, um die Performance zu optimieren.
3. **Fallback-Handling:**
   - Falls kein Modell verfügbar ist, wird ein klarer Fehler mit Status 503 zurückgegeben.

## Installation & Betrieb
### Mit Docker
```bash
docker build -t tts-service .
docker run -p 8000:8000 tts-service
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
- Weitere Sprachen können einfach ergänzt werden, sofern ein passendes Modell auf HuggingFace verfügbar ist.
- Die Modellkonfiguration erfolgt in `app.py`.

## Hinweise
- Für HuggingFace MMS-TTS werden die ISO-639-3 Codes verwendet (z. B. `ara` für Arabisch).
- Bei privaten/gated Modellen ist ggf. ein HuggingFace-Token nötig (`huggingface-cli login`).

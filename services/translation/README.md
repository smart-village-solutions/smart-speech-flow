# Translation Service (M2M100)

Dieser Service bietet KI-basierte Übersetzungen zwischen über 100 Sprachen mittels Facebooks m2m100_1.2B-Modell. Er ist als FastAPI-Microservice implementiert und für den produktiven Einsatz optimiert.

## Input / Output
- **Input:**
  - Text (String oder Liste von Strings)
  - Quellsprach-Code (`source_lang`, z. B. 'de')
  - Zielsprach-Code (`target_lang`, z. B. 'en')
  - Optional: Generierungsparameter
- **Output:**
  - Übersetzter Text (String oder Liste von Strings)
  - Metadaten: Modell, Gerät, Typ, Zeit, Token-Anzahl, Fehlerstatus

## Features
- Übersetzung von Texten (String oder Liste von Strings)
- Auswahl von Quell- und Zielsprache
- Unterstützung für große Texte (Chunking)
- Prometheus-Metriken (Requests, Fehler, Latenz, generierte Tokens)
- Health- und Language-Endpoints
- Konfigurierbar via Umgebungsvariablen

## Aufbau
- **app.py**: Hauptlogik, Endpunkte, Modell- und Tokenizer-Initialisierung, Fehlerbehandlung, Metriken
- **requirements.txt**: Python-Abhängigkeiten
- **tests/**: Pytest-Tests für die API
- **Dockerfile**: Container-Build für den Service

## Endpunkte
### POST /translate
Übersetzt einen Text von einer Sprache in eine andere.
- **Payload:**
  ```json
  {
    "text": "Hallo Welt",           // String oder Liste von Strings
    "source_lang": "de",           // Quellsprach-Code (ISO)
    "target_lang": "en",           // Zielsprach-Code (ISO)
    "generation": { ...optional... } // Optionale Generierungsparameter
  }
  ```
- **Response:**
  ```json
  {
    "model": "facebook/m2m100_1.2B",
    "device": "cuda:0",
    "dtype": "fp16",
    "source_lang": "de",
    "target_lang": "en",
    "count": 1,
    "elapsed_seconds": 0.2,
    "translations": "Hello world"
  }
  ```

### GET /languages
Gibt alle unterstützten Sprachcodes zurück.

### GET /health
Status und Modellinformationen.

### GET /metrics
Prometheus-kompatible Metriken.

## Konfiguration
- **MODEL_NAME**: Modellname (Standard: facebook/m2m100_1.2B)
- **DEVICE**: Gerät (cpu, cuda:0, ...)
- **PREFER_FP16**: FP16-Berechnung auf GPU (Standard: 1)
- **GEN_MAX_NEW_TOKENS**: Maximale neue Tokens pro Übersetzung
- **MAX_INPUT_TOKENS**: Maximale Input-Tokens
- **MAX_INPUT_CHARS**: Maximale Input-Zeichen
- **DENY_EMPTY**: Leere Texte ablehnen (Standard: 1)

## Starten
### Lokal
```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### Docker
```bash
docker build -t translation-service .
docker run -p 8000:8000 translation-service
```

## Testen
```bash
pytest tests/
```

## Beispiel-Request
```bash
curl -X POST "http://localhost:8000/translate" \
     -H "Content-Type: application/json" \
     -d '{"text": "Hallo Welt", "source_lang": "de", "target_lang": "en"}'
```

## Hinweise
- Der Service benötigt eine GPU für optimale Performance.
- Die unterstützten Sprachcodes findest du unter `/languages`.
- Fehler und Metriken werden an Prometheus gemeldet.

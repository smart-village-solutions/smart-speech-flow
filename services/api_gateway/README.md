# API Gateway Service

## Beschreibung

Das API Gateway ist die zentrale Schnittstelle für alle Sprachdienste im Smart Speech Flow Backend. Es orchestriert die Verarbeitung von Audio, Text und Übersetzung über die einzelnen Microservices (ASR, Translation, TTS) und bietet ein einheitliches REST-API für Endnutzer und Frontend.

## Input

- **/pipeline (POST)**
  - `file`: Audiodatei (WAV, MP3, OGG, FLAC, etc.)
  - `source_lang`: Ausgangssprache (z. B. `de`, `en`, `ar`, ...)
  - `target_lang`: Zielsprache (z. B. `en`, `de`, `tr`, ...)
  - Übergabe als `multipart/form-data`

Beispiel mit `curl`:
```bash
curl -F "file=@sample.wav" -F "source_lang=de" -F "target_lang=en" https://ssf.smart-village.solutions/pipeline
```

## Output

- **Erfolgreiche Antwort (JSON):**
  ```json
  {
    "success": true,
    "originalText": "Hier spricht die Polizei.",
    "translatedText": "Here the police speak.",
    "audioBase64": "<base64-kodierte WAV-Datei>"
  }
  ```
  - `originalText`: Transkription des Audios in der Ausgangssprache
  - `translatedText`: Übersetzung in die Zielsprache
  - `audioBase64`: Die synthetisierte Sprache als WAV-Datei (Base64-kodiert)

- **Fehlerhafte Antwort (JSON):**
  ```json
  {
    "success": false,
    "error": "Fehlermeldung"
  }
  ```

## Weitere Endpunkte

- **/health (GET):**
  - Gibt den Status der angebundenen Services als JSON zurück.
- **/metrics (GET):**
  - Prometheus-kompatible Metriken für Monitoring.
- **/** (GET):**
  - HTML-Frontend mit Upload-Formular und Health-Status.

## Typische Nutzung

Das Frontend sendet eine Audiodatei und die gewünschten Sprachen an `/pipeline`. Die Antwort enthält Transkription, Übersetzung und die synthetisierte Sprache als Audio. Fehler werden als JSON mit `success: false` und einer Fehlermeldung zurückgegeben.

---

Weitere Details zur Orchestrierung und zu den unterstützten Formaten siehe Haupt-README im Projektroot.

## Features
- **Zentrales REST-API für alle Sprachdienste**
- **Routing zu ASR, TTS und Translation Services**
- **Health- und Metrics-Endpunkte**
- **Validierung und Fehlerbehandlung**
- **Docker- und venv-ready**
- **Erweiterbar für weitere Services**

## Endpunkte
- `/pipeline` (POST): Orchestriert komplexe Sprachverarbeitungs-Pipelines (z. B. ASR → Translation → TTS)
- `/health` (GET): Status des Gateways und der angebundenen Services
- `/metrics` (GET): Prometheus-kompatible Metriken

## Architektur & Funktionsweise
1. **Routing:**
   - Der Gateway nimmt Anfragen entgegen und leitet sie an die jeweiligen Microservices weiter.
   - Die Kommunikation erfolgt über HTTP-Requests zu den internen Service-Endpunkten.
2. **Validierung:**
   - Eingaben werden geprüft und ggf. normalisiert.
3. **Fehlerbehandlung:**
   - Fehler aus den Microservices werden gesammelt und als konsistente API-Fehler zurückgegeben.
4. **Health-Checks:**
   - Der Gateway prüft regelmäßig die Erreichbarkeit und den Status der angebundenen Services.

## Installation & Betrieb
### Mit Docker
```bash
docker build -t api_gateway .
docker run -p 8000:8000 api_gateway
```

### Lokal mit venv
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

## Testen
```bash
pytest tests/
```

## Erweiterung
- Weitere Services können einfach angebunden werden.
- Die Endpunkte und Routing-Logik sind in `app.py` und `pipeline.py` konfigurierbar.

## Hinweise
- Der Gateway-Service ist für die Integration in größere Systeme und für externe Schnittstellen konzipiert.
- Monitoring und Health-Checks sind integriert.

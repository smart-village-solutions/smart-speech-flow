# Smart Speech Flow Backend

Dieses Projekt ist ein containerisiertes Microservice-Backend für Echtzeit-Sprachverarbeitung und Übersetzung. Es besteht aus vier eigenständigen Services, die über ein API-Gateway orchestriert werden. Jeder Service ist in Python/FastAPI implementiert und kann einzeln oder als Gesamtpipeline genutzt werden.

## Architektur & Services

### 1. ASR Service (Speech-to-Text)
- Automatische Spracherkennung für verschiedene Sprachen und Audioformate
- Endpunkte: `/transcribe` (POST), `/health` (GET), `/metrics` (GET), `/languages` (GET)
- Modelle: Whisper, Wav2Vec, etc. (lokal geladen)
- Beispiel:
   ```bash
   curl -F "file=@sample.wav" http://localhost:8001/transcribe
   ```

### 2. Translation Service
- KI-basierte Übersetzung mit Facebooks m2m100_1.2B-Modell
- Endpunkte: `/translate` (POST), `/languages` (GET), `/health` (GET), `/metrics` (GET)
- Beispiel:
   ```bash
   curl -X POST http://localhost:8002/translate \
          -H "Content-Type: application/json" \
          -d '{"text": "Hallo Welt", "source_lang": "de", "target_lang": "en"}'
   ```

### 3. TTS Service (Text-to-Speech)
- Sprachsynthese für viele Sprachen mit Coqui-TTS und HuggingFace MMS-TTS
- Endpunkte: `/synthesize` (POST), `/health` (GET), `/metrics` (GET)
- Beispiel:
   ```bash
   curl -X POST http://localhost:8003/synthesize \
          -H "Content-Type: application/json" \
          -d '{"text": "Hello world", "lang": "en"}' --output out.wav
   ```

### 4. API-Gateway
- Zentrales REST-API für alle Sprachdienste
- Endpunkte: `/pipeline` (POST), `/health` (GET), `/metrics` (GET)
- Orchestriert die gesamte Pipeline: ASR → Translation → TTS
- Beispiel für End-to-End:
   ```bash
   curl -F "file=@sample.wav" -F "source_lang=de" -F "target_lang=en" http://localhost:8000/pipeline --output output.wav
   ```

## Modellübersicht

Eine ausführliche Dokumentation zu den in den Services verwendeten KI-Modellen, deren Quellen und Lizenzen findest du unter [models.md](./models.md).

## Pipeline-Workflow
1. **ASR:** Audiodatei wird in Text transkribiert
2. **Translation:** Transkribierter Text wird in die Zielsprache übersetzt
3. **TTS:** Übersetzter Text wird als Sprache synthetisiert (WAV)
4. **API-Gateway:** Orchestriert alle Schritte und gibt die finale WAV-Datei zurück

## Monitoring & Betrieb
- Prometheus-kompatible Metriken unter `/metrics` je Service
- Health-Checks unter `/health` je Service
- Grafana-Dashboard für Visualisierung (siehe Ordner `monitoring/`)

## Installation & Start

### Mit Docker Compose (empfohlen)
```bash
docker compose up --build
```

### Einzelne Services lokal starten
```bash
# ASR
uvicorn services/asr/app:app --port 8001 &
# Translation
uvicorn services/translation/app:app --port 8002 &
# TTS
uvicorn services/tts/app:app --port 8003 &
# API-Gateway
uvicorn services/api-gateway/app:app --port 8000 &
```

### Testen
```bash
pytest services/asr/tests/
pytest services/translation/tests/
pytest services/tts/tests/
pytest services/api-gateway/tests/
```

## Endpunkte Übersicht

| Service        | Endpunkt         | Methode | Beschreibung                       |
|----------------|------------------|---------|------------------------------------|
| ASR            | /transcribe      | POST    | Audiodatei → Text                  |
| ASR            | /languages       | GET     | Unterstützte Sprachen              |
| ASR            | /health          | GET     | Status, Modellinfos                |
| ASR            | /metrics         | GET     | Monitoring                         |
| Translation    | /translate       | POST    | Textübersetzung                    |
| Translation    | /languages       | GET     | Unterstützte Sprachen              |
| Translation    | /health          | GET     | Status, Modellinfos                |
| Translation    | /metrics         | GET     | Monitoring                         |
| TTS            | /synthesize      | POST    | Text → Sprache (WAV)               |
| TTS            | /health          | GET     | Status, Modellinfos                |
| TTS            | /metrics         | GET     | Monitoring                         |
| API-Gateway    | /pipeline        | POST    | End-to-End (ASR → Trans → TTS)     |
| API-Gateway    | /health          | GET     | Status aller Services              |
| API-Gateway    | /metrics         | GET     | Monitoring                         |

## Integration Frontend: Spracheingabe und Ausgabe

Damit das Frontend korrekt mit dem Backend kommuniziert, sind folgende Schritte und Formate zu beachten:

### 1. Spracheingabe und Datei-Upload

Das Frontend muss beim Upload einer WAV-Datei die Ausgangs- und Zielsprache als Formularfelder mitsenden. Beispiel mit HTML-Form:

```html
<form action="/upload" method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept=".wav" required>
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

Alternativ per JavaScript (z.B. mit `fetch` und `FormData`):

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
- Transkription (Originalsprache, z.B. Deutsch)
- Übersetzung (Zielsprache, z.B. Englisch)
- Download-Link für die synthetisierte WAV-Datei
- Audio-Player zur direkten Wiedergabe

Beispiel-Ausschnitt aus der Response:

```html
<p>Transkription: Hallo Welt</p>
<p>Übersetzung: Hello world</p>
<a href="data:audio/wav;base64,..." download="output.wav">WAV herunterladen</a>
<audio controls src="data:audio/wav;base64,..."></audio>
```

### 3. API-Endpunkt für externe Clients

Alternativ kann das Frontend auch den `/pipeline`-Endpunkt nutzen (z.B. für reine API-Nutzung):

- POST-Request mit `file`, `source_lang`, `target_lang` als FormData
- Response: WAV-Datei direkt als Download

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

---

**Kurzfassung:**
- Immer beide Sprachparameter mitsenden (`source_lang`, `target_lang`)
- Ergebnis enthält Originaltext, Übersetzung und Audio (WAV, base64)
- Fehler werden als HTML zurückgegeben

## Unterstützte Audioformate

Der ASR-Service akzeptiert nicht nur WAV-Dateien, sondern auch weitere Audioformate wie MP3, OGG, FLAC und andere gängige Formate. Die Format-Erkennung erfolgt automatisch beim Upload.

**Hinweis für das Frontend:**
- Das Formularfeld muss weiterhin `file` heißen.
- Die hochgeladene Datei kann eines der unterstützten Formate besitzen.
- Die Endpunkte `/transcribe`, `/pipeline` und `/upload` funktionieren mit allen unterstützten Formaten.

Beispiel für den Upload einer MP3-Datei:
```bash
curl -F "file=@sample.mp3" -F "source_lang=de" -F "target_lang=en" http://localhost:8000/pipeline --output output.wav
```

Die Rückgabe erfolgt immer als WAV-Datei (synthetisierte Sprache).

## Hinweise & Tipps
- Für GPU-Beschleunigung: Container mit GPU-Support starten
- Eigene Modelle können im Ordner `models/` abgelegt werden
- `.venv` und Modelle sind nicht versioniert (siehe `.gitignore`)
- Bei privaten/gated Modellen ggf. HuggingFace-Token nötig (`huggingface-cli login`)
- Die unterstützten Sprachen sind je Service unter `/languages` abrufbar

## Lizenz
MIT

## Kontakt
Smart Village Solutions

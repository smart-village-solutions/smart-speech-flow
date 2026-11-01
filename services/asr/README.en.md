# ASR Service

This standalone FastAPI microservice provides automatic speech recognition (ASR). It supports multiple languages and audio formats, exposes health and monitoring endpoints, and is designed to run as part of the Smart Speech Flow microservice stack.

## Input and output

### Input

`POST /transcribe` accepts `multipart/form-data`:

- `file`: an audio file such as WAV, MP3, OGG, or FLAC
- `lang`: optional language code, for example `de`, `en`, or `ar`

```bash
# Since #221 the service is not published on the host; inside the compose
# network it listens on asr:8000.
docker compose exec api_gateway \
  curl -F "file=@examples/audio/sample.wav" -F "lang=de" http://asr:8000/transcribe
```

### Output

Successful requests return JSON:

```json
{
  "text": "This is the police speaking.",
  "fallback": false,
  "model": "whisper-large-v3-turbo",
  "model_version": "aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a",
  "input_sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
}
```

`model_version` is the SHA-256 of the checkpoint, as named in Whisper's download URL, and `input_sha256` the hash of the normalised 16 kHz WAV the model transcribed. The gateway archives both with every recorded message.

When the ASR model is unavailable, the service returns its fallback response with `fallback: true`. When `debug=true` is supplied as a form or query parameter, the response additionally contains a `debug` object. Invalid language codes return `400`.

Validation errors use FastAPI's error payload format, for example:

```json
{
  "detail": "Unsupported language code: xx"
}
```

## Endpoints

- `POST /transcribe`: transcribe an audio file to text.
- `GET /health`: service status, supported languages, and model information.
- `GET /metrics`: Prometheus-compatible metrics.
- `GET /supported-languages`: available language codes.

## Implementation notes

- The service permanently loads Whisper `large-v3-turbo` locally; audio is not sent to an external API.
- Loaded models remain in memory to improve performance.
- If the ASR model is not loaded, the endpoint returns the configured fallback response instead of failing the request.

## Running the service

### Docker

```bash
docker build -t asr-service .
docker run -p 8000:8000 asr-service
```

### Local virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

## Tests and extension

```bash
pytest tests/
```

Add a language only when a compatible model is available; configure model selection in `app.py`. Private or gated Hugging Face models may require `huggingface-cli login`.

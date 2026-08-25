# ASR Service

This standalone FastAPI microservice provides automatic speech recognition (ASR). It supports multiple languages and audio formats, exposes health and monitoring endpoints, and is designed to run as part of the Smart Speech Flow microservice stack.

## Input and output

### Input

`POST /transcribe` accepts `multipart/form-data`:

- `file`: an audio file such as WAV, MP3, OGG, or FLAC
- `lang`: optional language code, for example `de`, `en`, or `ar`

```bash
curl -F "file=@sample.wav" -F "lang=de" http://localhost:8001/transcribe
```

### Output

Successful requests return JSON:

```json
{
  "text": "This is the police speaking.",
  "fallback": false
}
```

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

- Models such as Whisper or Wav2Vec are loaded locally; audio is not sent to an external API.
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

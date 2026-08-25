# Translation Service (M2M100)

This FastAPI microservice translates text between more than 100 languages using Facebook's `m2m100_1.2B` model. It is optimized for use in the Smart Speech Flow service stack.

## Input and output

Input consists of text (a string or list of strings), a source-language code, a target-language code, and optional generation parameters. Normal responses include translated text together with model, device, timing, and item-count metadata; error and debug details are returned only in their respective responses.

## Features

- Translate one text or a list of texts.
- Select source and target languages.
- Chunk large inputs.
- Export Prometheus metrics for requests, errors, latency, and generated tokens.
- Provide health and supported-language endpoints.
- Configure model and generation limits through environment variables.

## Layout

- `app.py`: endpoint, model/tokenizer initialization, error handling, and metrics.
- `requirements.txt`: Python dependencies.
- `tests/`: API tests.
- `Dockerfile`: service image build.

## Endpoints

### `POST /translate`

```json
{
  "text": "Hello world",
  "source_lang": "en",
  "target_lang": "de",
  "generation": {}
}
```

```json
{
  "model": "facebook/m2m100_1.2B",
  "device": "cuda:0",
  "dtype": "fp16",
  "source_lang": "en",
  "target_lang": "de",
  "count": 1,
  "elapsed_seconds": 0.2,
  "translations": "Hallo Welt"
}
```

- `GET /languages`: supported language codes.
- `GET /health`: service and model status.
- `GET /metrics`: Prometheus-compatible metrics.

## Configuration

- `MODEL_NAME` (default: `facebook/m2m100_1.2B`)
- `DEVICE` (`cpu`, `cuda:0`, and so on)
- `PREFER_FP16` (GPU FP16 calculation; default `1`)
- `GEN_MAX_NEW_TOKENS`, `MAX_INPUT_TOKENS`, and `MAX_INPUT_CHARS`
- `DENY_EMPTY` (reject empty input; default `1`)

## Run and test

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
docker build -t translation-service .
docker run -p 8000:8000 translation-service
pytest tests/
```

```bash
curl -X POST "http://localhost:8000/translate" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world","source_lang":"en","target_lang":"de"}'
```

A GPU is recommended for performance. Retrieve supported language codes from `/languages`; the service exports errors and metrics to Prometheus.

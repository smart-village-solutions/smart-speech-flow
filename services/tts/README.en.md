# TTS Service

This standalone FastAPI microservice synthesizes speech for multiple languages. It uses Coqui TTS where a direct model is available and Hugging Face MMS TTS as a fallback.

## Input and output

Input contains required `text` and a language code such as `de`, `en`, or `ar`. A successful request returns a WAV file; an error response is JSON and includes the fallback status.

## Features

- Text-to-speech for multiple languages.
- Automatic fallback from Coqui TTS to Hugging Face MMS TTS.
- REST endpoints for synthesis, health, metrics, and supported languages.
- Prometheus metrics, Docker support, local virtual-environment support, and automated language tests.

## Supported languages

- Coqui TTS: German (`de`), English (`en`), Turkish (`tr`), Persian (`fa`), and Ukrainian (`uk`).
- Hugging Face MMS TTS: Arabic (`ar`), Kurdish (`ku`), Tigrinya (`ti`), Amharic (`am`), Russian (`ru`), and further languages when an appropriate model exists.

## Endpoints

### `POST /synthesize`

```json
{
  "text": "Hello world",
  "lang": "en"
}
```

`tts_text` is accepted as an alternative to `text`.

- `GET /health`: service status, loaded models, and GPU information.
- `GET /metrics`: Prometheus-compatible metrics.
- `GET /supported-languages`: language codes for Coqui TTS and the MMS fallback.

## Implementation notes

The service first loads a Coqui model for the requested language. If none is available, it uses the matching ISO-639-3 code with Hugging Face MMS TTS. Models run locally and are cached in memory. If no model is available, the service responds with `503`.

## Running and testing

```bash
docker build -t tts-service .
docker run -p 8000:8000 tts-service

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload

pytest tests/
```

Add languages only when a compatible Hugging Face model exists; configure model selection in `app.py`. MMS TTS uses ISO-639-3 codes, for example `ara` for Arabic. Private or gated models may require `huggingface-cli login`.

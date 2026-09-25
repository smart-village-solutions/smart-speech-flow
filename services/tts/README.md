# TTS Service

FastAPI microservice that turns translated text into speech. Each product
language has exactly one voice: Piper voices on the GPU for most languages,
Meta MMS for Amharic and Tigrinya, which Piper has no voice for.

## Voices

| Language | Engine | Voice |
|---|---|---|
| German (`de`) | Piper | `de_DE-thorsten-high` |
| English (`en`) | Piper | `en_US-ljspeech-high` |
| Turkish (`tr`) | Piper | `tr_TR-dfki-medium` |
| Russian (`ru`) | Piper | `ru_RU-denis-medium` |
| Ukrainian (`uk`) | Piper | `uk_UA-tetiana-high` |
| Arabic (`ar`) | Piper | `ar_JO-kareem-medium` |
| Persian (`fa`) | Piper | `fa_IR-gyro-medium` |
| Kurdish, Kurmanji (`ku`) | Piper | `ku_TR-berfin_renas-medium` |
| Amharic (`am`) | MMS | `facebook/mms-tts-amh` |
| Tigrinya (`ti`) | MMS | `facebook/mms-tts-tir` |

`voices.py` pins every file to a revision and a SHA-256 hash. The image build
downloads and verifies them (`fetch_voices.py`), so the service needs no
network access at runtime. Licences are listed in
`docs/architecture/models.md`.

## Text preparation

`speech_text.py` rewrites text before synthesis. Piper reads plain integers
through espeak-ng, so only what espeak misreads is rewritten: clock times,
money with cents, numbers with a leading zero (read digit by digit), and German
days of the month. MMS voices cannot read digits at all, so for Amharic and
Tigrinya every number is spelled out.

## Endpoints

### `POST /synthesize`

```json
{
  "text": "Your appointment is on March 15 at 9:30.",
  "lang": "en",
  "session_id": "optional, seeds the MMS voices"
}
```

Returns a WAV file with the headers `X-TTS-Model` (the voice that spoke),
`X-TTS-Language` and `X-TTS-Fallback` (always `false`; there is no fallback
engine). `tts_text` is accepted and ignored: voices read their own script.

| Status | Meaning |
|---|---|
| 400 | Empty text, unknown language, or text with nothing the voice can pronounce |
| 503 | The voice for this language failed to load at startup |
| 500 | Synthesis failed |

- `GET /health`: per-language voice state (`engine`, `voice`, `loaded`, `device`, `error`), `status: degraded` when any voice failed to load.
- `GET /metrics`: Prometheus metrics.
- `GET /supported-languages`: the language codes in `voices.py`.

## Running

All voices load onto the GPU at startup. A voice that does not get the CUDA
execution provider fails to load rather than running on the CPU unnoticed.
Set `TTS_DEVICE=cpu` to run the image on a machine without a GPU.

```bash
docker build -f services/tts/Dockerfile -t tts-service .
docker run --gpus all -p 8000:8000 tts-service
docker run -e TTS_DEVICE=cpu -p 8000:8000 tts-service   # no GPU
```

Tests run from the repository root without any model installed:

```bash
PYTHONPATH=. pytest services/tts/tests
```

## Changing a voice

Edit the entry in `voices.py` with the new revision and the SHA-256 of each
file, then rebuild the image. `piper-tts` is pinned separately in
`requirements-piper.txt` and installed with `--no-deps`, because it requires the
CPU build of onnxruntime, which would overwrite `onnxruntime-gpu`.

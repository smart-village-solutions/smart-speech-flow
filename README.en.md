# Smart Speech Flow Backend

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-compose-blue.svg)](https://docs.docker.com/compose/)

Smart Speech Flow is a containerized microservice backend for real-time speech processing and translation. It orchestrates a speech-to-speech pipeline consisting of automatic speech recognition (ASR), translation, text-to-speech (TTS), session management, and optional LLM refinement.

## Quick start

```bash
git clone https://github.com/smart-village-solutions/smart-speech-flow.git
cd smart-speech-flow
docker compose up -d traefik redis ollama api_gateway asr translation tts frontend
curl http://localhost:8000/health
```

The gateway is available at `http://localhost:8000`. The compose file also defines `frontend-archive`, whose build context is the sibling directory `../ssf-frontend`. Obtain that repository before running the unrestricted `docker compose up -d` command.

## Development prerequisites

- Docker Engine and Docker Compose v2
- Python 3.12 or newer for local development
- At least 16 GB RAM and approximately 20 GB free disk space for models and containers
- NVIDIA GPU and NVIDIA Container Toolkit are optional, but recommended for inference performance

Install local development dependencies and run the hermetic test suite:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

The dependency sources are `requirements*.in` and `services/*/requirements.in`. Regenerate lock files with `./scripts/compile_requirements.sh` and validate them with `./scripts/check_dependencies.sh`.

## Services

| Service | Development port | Responsibility |
| --- | --- | --- |
| API Gateway | 8000 | REST/WebSocket entry point and pipeline orchestration |
| ASR | 8001 | Audio transcription |
| Translation | 8002 | M2M100 text translation |
| TTS | 8003 | Speech synthesis |
| Redis | internal | Session and message persistence |
| Ollama | internal | Optional translation refinement |

The gateway is the public integration boundary. Clients should use the session and messaging endpoints under `/api/*`; `/pipeline` and `/upload` remain low-level/legacy endpoints.

## Session workflow

1. An administrator creates a session: `POST /api/admin/session/create`.
2. A customer activates it: `POST /api/customer/session/activate`.
3. Both parties send text or audio through `POST /api/session/{session_id}/message`.
4. Clients read message history through `GET /api/session/{session_id}/messages`.
5. Real-time clients connect to `WS /ws/{session_id}/{client_type}`.

For concrete REST and WebSocket payloads, use [the English developer guide](docs/DEVELOPER_GUIDE.en.md).

## Example pipeline request

```bash
curl -F "file=@examples/audio/sample.wav" \
  -F "source_lang=de" \
  -F "target_lang=en" \
  http://localhost:8000/pipeline \
  --output translated.wav
```

## Configuration

Copy `.env.example` to `.env` and adjust it for your environment. Do not commit `.env`; it is ignored by Git. Common development settings include Redis connection details, CORS origins, model refinement flags, audio-retention limits, rate limits, and local Grafana credentials.

`LLM_REFINEMENT_ENABLED=true` enables the optional Ollama step. Pull its model once after starting the stack:

```bash
docker compose exec ollama ollama pull gpt-oss:20b
```

## Quality and contribution workflow

Create a feature branch, add or update tests with each behavior change, run the relevant checks, and open a pull request. Use Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, and `chore:`.

```bash
pre-commit install
./scripts/quality-check.sh
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete contribution process and [English code-quality standards](docs/testing/code-quality.en.md) for the tooling and CI expectations.

## English technical documentation

- [Developer guide](docs/DEVELOPER_GUIDE.en.md)
- [ASR service](services/asr/README.en.md)
- [Translation service](services/translation/README.en.md)
- [TTS service](services/tts/README.en.md)
- [Code-quality standards](docs/testing/code-quality.en.md)
- [Documentation index](docs/README.md)

## License

This project is licensed under the [MIT License](LICENSE).

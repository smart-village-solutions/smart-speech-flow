# Fix SonarCloud Open Issues

## Summary

Eliminate the currently open SonarCloud findings across the repository without intentionally changing product behavior.

## Why

The repository currently has open SonarCloud issues across the API gateway, WebSocket fallback stack, translation/TTS services, frontend code, and Dockerfiles. The remaining findings include security issues, FastAPI typing/documentation gaps, reliability concerns around cancellation and async file handling, and maintainability problems in the main runtime hotspots.

## What Changes

- Fix security and blocker findings first in API gateway upload, validation, routing, and runtime bootstrap code.
- Standardize FastAPI dependency annotations and error-response documentation in affected routers.
- Remove unsafe logging of user-controlled content and avoid reflecting unsanitized user input in HTML responses.
- Refactor or simplify hotspot functions until the remaining backend and frontend Sonar findings are eliminated.
- Update Dockerfiles and supporting code quality hotspots so the final SonarCloud scan reports zero open issues.

## Impact

- Affected code: `services/api_gateway`, `services/asr`, `services/tts`, `services/translation`, `services/frontend`, service Dockerfiles
- Affected quality systems: SonarCloud, local quality checks, CI quality pipeline
- Current baseline: 332 open issues, with the largest hotspots in `services/api_gateway/routes/session.py`, `services/api_gateway/websocket_polling_routes.py`, `services/api_gateway/pipeline_logic.py`, `services/api_gateway/websocket_monitoring_routes.py`, `services/api_gateway/websocket_fallback.py`, and `services/api_gateway/websocket.py`


# Smart Speech Flow – ToDo Board

## ✅ Fertiggestellte Meilensteine (Phasen 0–5)

| Phase | Fokus | Ergebnisse | Verifikation |
| --- | --- | --- | --- |
| 0 | Qualität & Tooling | Vollständige Test-Suite, dokumentierte Coverage | `PYTHONPATH=. pytest tests -q` (TESTS.md) |
| 1 | Session Management | Single-Session-Policy, Admin-API, WebSocket-Lifecycle | `tests/test_session_manager.py`, `tests/test_admin_routes.py`, `tests/test_websocket_manager.py` |
| 2 | Unified Input | Vereinheitlichte Message-API, Audio/Text-Validation, optimierte Pipelines | `tests/test_unified_message_endpoint.py`, `tests/test_audio_validation.py`, `tests/test_text_pipeline.py` |
| 3 | User Experience | Differenziertes Broadcasting, Timeout-Handling, Mobile-Optimierung | `tests/test_mobile_optimization.py`, `tests/test_session_timeout.py` |
| 4 | Resilience | Circuit Breaker, Graceful Degradation, erweitertes Input-Hardening | `tests/test_circuit_breaker_integration.py`, `tests/test_rate_limiting.py` |
| 5 | Monitoring | Health-APIs, Session KPIs, Pipeline- und Resource-Metriken | `tests/test_admin_routes.py::TestMetrics`, Services `*/tests/test_health.py` |

Alle ToDos der Phasen 0–5 sind abgeschlossen und in `Version2.md` bzw. `SYSTEM_ARCHITECTURE.md` dokumentiert.

## 🔄 Phase 6 – Production Hardening (offen)

- [x] **ToDo 6.1: GPU Resource Management**
  Aufbauend auf den Health-Daten ein aktives GPU-Resource- und Placement-Management implementieren.
  - Acceptance Criteria: GPU-Auslastung beeinflusst Autoscaling-Signale; Limits und Graceful Degradation berücksichtigen GPU-Verfügbarkeit; Dokumentation für Ops vorhanden.
  - Owner: Platform / AI Infra

- [x] **ToDo 6.2: Alerting & Dashboard Finalisierung**
  Prometheus/Grafana-Stack um praxistaugliche Dashboards und Alerts ergänzen (SLA, Fehlerquote, Pipeline-Latenzen).
  - Acceptance Criteria: Mindestens zwei produktionsrelevante Dashboards; Alert-Regeln für Service-Ausfälle, Latenz, Ressourcenknappheit; README-Abschnitt mit Zugriff & Runbook.
  - Owner: Observability

- [x] **ToDo 6.3: Session Persistence & Failover**
  Sessions dauerhaft in Redis ablegen, um Neustarts zu überstehen und horizontales Scaling zu ermöglichen.
  - *Analyse*: Redis-Variante und Persistence-Modus festlegen (AOF + Snapshot), Security/Secrets klären.
  - *Setup*: Redis als Compose-Service ergänzen, Health-Checks & Monitoring einbinden, Local/Prod-Konfig via ENV.
  - *Implementierung*: `SessionManager` auf Redis CRUD umstellen (Sessions, Messages, Timeouts) inkl. Migration der Audio-Referenzen.
  - *Tests*: Unit-/Integrationstests für Redis-Backend, Smoke-Test mit bestehender API (`tests/test_session_manager.py`, `tests/test_unified_message_endpoint.py`).
  - *Rollout*: Blue/Green-Plan erstellen, Fallback auf in-memory prüfen, Runbook in `SYSTEM_ARCHITECTURE.md` ergänzen.

## 🚀 Phase 7 – Quality Enhancements (neu)

- [x] **ToDo 7.1: LLM-basierte Übersetzungs-Verfeinerung**
  Übersetzungen vor dem TTS-Schritt mit einem lokalen LLM nachschärfen, um natürlichere Antworten zu erzielen.
  - *Analyse*: Ollama (`gpt-oss:20b`) integriert, GPU-Bedarf validiert, Prompt für Konversations-Tuning definiert.
  - *Implementierung*: `TranslationRefiner` zwischen Translation und TTS aktiv, Standard über ENV abschaltbar (`LLM_REFINEMENT_ENABLED`, Modell/Timeout konfigurierbar); Retry-Logik & Timeout-Handling ergänzt.
  - *Tests*: Pipeline-Unit- und Integrationstests (`services/api_gateway/tests/test_pipeline.py`, `pytest` Komplettlauf) decken aktivierten und deaktivierten Modus ab.
  - *Ops*: Ollama-Service in `docker-compose.yml` samt GPU-Setup, README/SYSTEM_ARCHITECTURE aktualisiert, Prometheus-Metriken für Requests/Latenzen verfügbar.

## 🧪 Regression-Checkliste

- `PYTHONPATH=. pytest tests -q`
- Spezifische Service-Suites bei Änderungen an ASR/Translation/TTS: `pytest services/<service>/tests`
- Smoke-Test für Admin/API-Gateway: `pytest tests/test_admin_routes.py tests/test_unified_message_endpoint.py`

## 📎 Referenzen

- `Version2.md` – Funktionsumfang Release 2
- `SYSTEM_ARCHITECTURE.md` – Architekturübersicht
- `TESTS.md` – Teststrategie und Coverage

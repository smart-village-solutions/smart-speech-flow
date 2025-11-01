
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

- [ ] **ToDo 6.1: GPU Resource Management**
  Aufbauend auf den Health-Daten ein aktives GPU-Resource- und Placement-Management implementieren.
  - Acceptance Criteria: GPU-Auslastung beeinflusst Autoscaling-Signale; Limits und Graceful Degradation berücksichtigen GPU-Verfügbarkeit; Dokumentation für Ops vorhanden.
  - Owner: Platform / AI Infra

- [ ] **ToDo 6.2: Alerting & Dashboard Finalisierung**
  Prometheus/Grafana-Stack um praxistaugliche Dashboards und Alerts ergänzen (SLA, Fehlerquote, Pipeline-Latenzen).
  - Acceptance Criteria: Mindestens zwei produktionsrelevante Dashboards; Alert-Regeln für Service-Ausfälle, Latenz, Ressourcenknappheit; README-Abschnitt mit Zugriff & Runbook.
  - Owner: Observability

- [ ] **ToDo 6.3: Performance & Load Validation**
  Automatisierte Lasttests für Audio- und Text-Pipelines einrichten, um Skalierungs- und Timeout-Thresholds zu verifizieren.
  - Acceptance Criteria: Reproduzierbare Load-Test-Skripte (z. B. Locust/K6); dokumentierte Zielwerte; Regression-Check im CI.
  - Owner: QA / Performance

## 🧪 Regression-Checkliste

- `PYTHONPATH=. pytest tests -q`
- Spezifische Service-Suites bei Änderungen an ASR/Translation/TTS: `pytest services/<service>/tests`
- Smoke-Test für Admin/API-Gateway: `pytest tests/test_admin_routes.py tests/test_unified_message_endpoint.py`

## 📎 Referenzen

- `Version2.md` – Funktionsumfang Release 2
- `SYSTEM_ARCHITECTURE.md` – Architekturübersicht
- `TESTS.md` – Teststrategie und Coverage

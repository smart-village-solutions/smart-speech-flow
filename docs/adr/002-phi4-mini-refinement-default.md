# ADR 002: Phi-4 Mini als Standard für Übersetzungsveredelung

**Status:** Accepted (provisional)
**Date:** 2026-07-21
**Decision Makers:** Backend Team
**Stakeholders:** Product, Operations, Nutzerforschung

## Context

Die optionale Veredelung der maschinellen Übersetzung lief bisher mit
`gpt-oss:20b` über Ollama. Sie liegt synchron im Verarbeitungspfad und muss
innerhalb von vier Sekunden antworten. Ein kontrollierter Benchmark mit dem
festen Text- und Audio-Goldenset verglich `gpt-oss:20b`, `phi4-mini` und einen
kurzen Explorationslauf mit `qwen3:4b`.

Die Benchmarkdaten sind unter `benchmark-results/phi-refinement/` abgelegt.
Die Qualitätsbewertung durch sprachkundige Personen wird bewusst in einen
späteren A/B-Test mit Nutzerfeedback verschoben.

## Decision

`phi4-mini` wird als primäres Refinement-Modell eingesetzt.

Die Laufzeitkonfiguration lautet:

```dotenv
LLM_REFINEMENT_ENABLED=true
LLM_REFINEMENT_MODE=primary_only
LLM_REFINEMENT_PRIMARY_MODEL=phi4-mini
LLM_REFINEMENT_TIMEOUT=4.0
LLM_REFINEMENT_MAX_RETRIES=1
LLM_REFINEMENT_THINK=false
```

Veredelung bleibt über `LLM_REFINEMENT_MODE=disabled` ohne Codeänderung
abschaltbar. Dies ist die Vergleichsvariante für den geplanten A/B-Test.

## Evidence

### Text-Pipeline

| Metrik | gpt-oss:20b | phi4-mini |
| --- | ---: | ---: |
| Refinement Median | 4.004 ms | 561 ms |
| Refinement p95 | 4.005 ms | 842 ms |
| Refinement-Fehler/Timeouts | 45,3 % | 0 % |

### Audio-Pipeline

| Metrik | gpt-oss:20b | phi4-mini |
| --- | ---: | ---: |
| Refinement Median | 4.004 ms | 572 ms |
| Refinement p95 | 4.005 ms | 1.012 ms |
| Audio-Pipeline Median | 4.671 ms | 1.270 ms |
| Refinement-Fehler/Timeouts | 48,1 % | 0 % |

`qwen3:4b` erreichte im kurzen Textlauf unter dem Vier-Sekunden-Limit keine
erfolgreiche Veredelung und wird nicht weiter verfolgt.

## Consequences

### Positive

- Die Refinement-Latenz sinkt im Median um rund 86 %.
- Phi hält das Vier-Sekunden-Budget zuverlässig ein.
- Die Text- und Audio-Pipeline werden deutlich kürzer.
- Ein Modellwechsel oder das Abschalten bleibt reine Konfiguration.

### Risks

- Die Latenzmessung beweist keine bessere Übersetzungsqualität.
- Stichproben zeigen, dass Phi gelegentlich unpassende oder fehlerhafte
  Umformulierungen erzeugen kann.
- Nutzerfeedback ist daher Voraussetzung für eine dauerhafte Produktentscheidung.

## Validation and Rollback

Der nächste Test vergleicht Nutzergruppen mit `primary_only` und `disabled`.
Erfasst werden Akzeptanz der Übersetzung, Korrekturen und offensichtliche
Bedeutungsverluste.

Bei Qualitätsproblemen erfolgt der Rollback ohne Deployment:

```dotenv
LLM_REFINEMENT_MODE=disabled
```

Danach wird das API-Gateway neu erstellt:

```bash
docker compose up -d --no-deps --force-recreate api_gateway
```

## Related Documents

- [OpenSpec Change](../../openspec/changes/add-phi-refinement-benchmarking/)
- [Benchmark reports](../../benchmark-results/phi-refinement/)
- [User Testing Strategy](../testing/USER_TESTING_STRATEGY.md)

---

**Review Date:** Nach Abschluss des Nutzer-A/B-Tests

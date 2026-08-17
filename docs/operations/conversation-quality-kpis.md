# KPI-Katalog für Gesprächsqualität

**Status:** Arbeitsgrundlage für Implementierung und Dashboarding
**Geltungsbereich:** SSF-Gespräche mit Text- und/oder Audio-Nachrichten; ASR, Übersetzung, TTS, Zustellung und Client-Erlebnis
**Ziel:** Qualitätsprobleme früh erkennen, reproduzierbar einordnen und Verbesserungen messbar belegen – ohne Gesprächsinhalte zur Standard-Telemetrie zu machen.

## 1. Verbindliche Messgrundsätze

1. **Ein Ereignis, eine Wahrheit:** Ein Qualitätsereignis erhält eine eindeutige `event_id`, einen UTC-Zeitpunkt und eine Schema-Version. Wiederholte Übertragungen müssen über `event_id` dedupliziert werden.
2. **Serverzeit für Service- und Zustellzeiten:** Clientzeiten dürfen nur für lokale Interaktionen verwendet werden. Latenzen zwischen Client und Server werden mit beiden Zeitstempeln und einer Uhrdrift-Kennzeichnung ausgewertet.
3. **Nur abgeschlossene Nenner:** Eine Nachricht zählt erst als verarbeitet, wenn ihr Terminalstatus bekannt ist: `delivered`, `failed`, `cancelled` oder `expired`.
4. **Fehler sind klassifiziert:** Jede nicht erfolgreiche Stufe erhält genau eine `error_class` und optional einen stabilen `error_code`; Freitextfehler sind kein KPI-Label.
5. **Quantile statt nur Mittelwerte:** Latenzen werden mindestens als Anzahl, p50, p95, p99 und Maximum berichtet. Mittelwerte sind nur Ergänzung.
6. **Keine hochkardinalen Prometheus-Labels:** `session_id`, `message_id`, `user_id`, rohe Browser-Versionen, IP-Adressen und Fehlermeldungen gehören nicht in Metrik-Labels. Sie dürfen nur in zeitlich begrenzte, zugriffsgeschützte Ereignisdaten.
7. **Vergleichbarkeit sichern:** Jeder Messpunkt enthält die tatsächlich verwendete `release_version`, `pipeline_version`, Modell-/Provider-Versionen und Konfiguration, soweit technisch verfügbar.

## 2. Datenschutz- und Datenminimierung

Die Standard-Telemetrie speichert **keine** Audioinhalte, Transkripte, Übersetzungen, Namen, Telefonnummern, IP-Adressen, vollständigen User-Agent-String oder präzise Standortdaten. Das entspricht der Produktvorgabe, Gesprächsinhalte ohne ausdrückliche Aktivierung nicht dauerhaft zu speichern; Originalaudio wird bereits nach 24 Stunden gelöscht.

| Datenart | Zulässig für Standard-KPIs | Vorgabe |
| --- | --- | --- |
| Pseudonyme Gesprächs-/Nachrichten-ID | Ja | Rotierende, nicht erratbare ID; kein direktes Personenmerkmal |
| Inhalt von Audio, Transkript, Übersetzung | Nein, außer bei wirksamer Einwilligung für den konkreten Zweck | Dann ausschließlich im getrennten Inhalts-Speicher gemäß Abschnitt 2.1; nie als Metrik-Label |
| Audioeigenschaften | Ja | Nur technische Merkmale wie Dauer, Größe, Codec und Sample-Rate |
| Sprache | Ja | BCP-47-/ISO-Code, keine freie Eingabe |
| Client | Ja | Browser-Familie, Hauptversion, OS-Familie, Gerätetyp; grobe Werte mit kleiner Kardinalität |
| Netzwerk | Ja | Netzklasse und Messwerte, aber keine IP, SSID, exakte Geoposition oder Netzbetreiberkennung |
| Feedback-Freitext | Nur Opt-in | Separat speichern, PII-Filter und kurze Aufbewahrung; niemals als Metrik-Label |

Empfohlene Fristen: Rohereignisse 30 Tage, pseudonymisierte Tagesaggregate 13 Monate, Fehlerdiagnostik höchstens 7 Tage, Opt-in-Inhalte nach vereinbartem Zweck und deutlich kürzer als allgemeine Analysedaten. Fristen, Rechtsgrundlage, Mandantentrennung, Löschlauf und Zugriffsrollen müssen vor Produktivbetrieb durch Datenschutzverantwortliche freigegeben werden.

### 2.1 Einwilligung für Inhaltsdaten

Die Einwilligung in die Speicherung von Inhaltsdaten ist **optional, granular und pro Person**. Ohne wirksame Einwilligung bleibt die Inhaltsablage deaktiviert; die technische Qualitätsmetrik wird dennoch pseudonymisiert erfasst. Die Einwilligung darf weder vorausgewählt sein noch die Nutzung der Kernfunktion verhindern, wenn die Inhaltsablage dafür nicht erforderlich ist. Sie muss nachweisbar, verständlich, zweckgebunden und widerrufbar sein. Das folgt insbesondere aus den Grundsätzen der Zweckbindung und Datenminimierung sowie den Anforderungen an nachweisbare, klare Einwilligung nach Art. 5 und 7 DSGVO. [DSGVO, EUR-Lex](https://eur-lex.europa.eu/legal-content/DE-EN-FR/TXT/?uri=CELEX%3A32016R0679)

Es werden getrennte Entscheidungen je Zweck eingeholt; mindestens `quality_improvement`, `support_diagnostics` und `model_evaluation`. Zusätzlich wird die Inhaltskategorie gewählt: `text` (Eingabe, ASR und Übersetzung), `input_audio` und `output_audio`. Eine Zustimmung für Support berechtigt nicht automatisch zur Nutzung für Modellverbesserung; eine Textfreigabe auch nicht automatisch zur Speicherung von Audio. Die konkrete Rechtsgrundlage, die Informationspflichten sowie besondere Anforderungen für Minderjährige oder besondere Kategorien personenbezogener Daten müssen vor Einführung durch die zuständige Datenschutzstelle bestätigt werden.

| Datensatz | Zusätzliches Einwilligungsfeld | Zulässige Werte / Regel |
| --- | --- | --- |
| `session_quality` | `admin_content_consent_state`, `customer_content_consent_state` | `granted`, `denied`, `withdrawn`, `not_asked`; Status je Gesprächspartner zum Sessionstart und bei Änderung aktualisieren |
| `session_quality` | `content_consent_purposes`, `content_consent_categories`, `content_consent_policy_version`, `content_consent_last_changed_at_utc` | Listen der Zwecke/Kategorien, Version des Einwilligungstexts und Zeitpunkt; niemals den Einwilligungstext selbst doppelt speichern |
| `translation_quality` | `sender_content_consent_state_at_acceptance`, `content_storage_decision_by_category`, `content_storage_purposes`, `content_storage_categories` | Unveränderlicher Snapshot beim Akzeptieren der Nachricht; je Kategorie `allowed`, `denied`, `withdrawn` oder `not_applicable` |
| `translation_quality` | `content_record_id_hash`, `content_retention_expires_at_utc`, `content_deleted_at_utc` | Nur für mindestens eine erlaubte Kategorie; opake Referenz auf den getrennten Inhalts-Speicher und nachweisbare Löschung |

#### Getrennter Inhalts-Speicher

Wenn `content_storage_decision_by_category` mindestens eine Kategorie mit `allowed` enthält, dürfen die in der nachfolgenden Tabelle ausgewählten Inhalte gespeichert werden. Sie werden **nicht** in `session_quality`, `translation_quality`, Logs, Prometheus oder Feedback-Events geschrieben, sondern verschlüsselt und mandantengetrennt in einem Inhalts-Speicher. Der Zugriff erfordert Zweck, Rolle und Auditlog.

| Inhalt | Feld im Inhalts-Speicher | Bedingung |
| --- | --- | --- |
| Texteingabe bzw. ASR-Ergebnis | `source_text` | Zustimmung des Senders für den gewählten Zweck zum Annahmezeitpunkt |
| Übersetzung | `translated_text` | wie oben |
| TTS-spezifische Textvariante | `tts_text` | wie oben; nur wenn technisch erzeugt |
| Eingangs-Audio | `input_audio` | Kategorie `input_audio` und gewählter Zweck; bestehende 24-Stunden-Frist gilt als Obergrenze, sofern nichts Strengeres vereinbart ist |
| TTS-Ausgabeaudio | `output_audio` | nur wenn für den gewählten Zweck notwendig |

Beim Widerruf werden ab diesem Zeitpunkt keine neuen Inhalte gespeichert. Bereits auf Basis dieser Einwilligung gespeicherte Inhaltsdaten werden über `content_record_id_hash` identifiziert und gemäß dokumentierter Löschregel unverzüglich zur Löschung vorgemerkt; Ausnahmen dürfen nur auf einer separat geprüften Rechtsgrundlage beruhen. Das Einwilligungsprotokoll selbst enthält nur die für den Nachweis nötigen Metadaten und wird getrennt von den Inhalten geführt.

## 3. Datenmodell: eine Zeile pro Session, eine Zeile pro Translation

SSF speichert für Qualitätsanalysen genau zwei fachliche Datensätze: **`session_quality`** (eine Zeile je Gespräch) und **`translation_quality`** (eine Zeile je zu übersetzender Nachricht). Technische Zwischenereignisse dürfen kurzzeitig zur Befüllung dieser Zeilen dienen, werden aber nicht als dritte dauerhafte Analysedatenquelle benötigt. `translation_quality` referenziert immer genau eine `session_quality`-Zeile.

Nicht verfügbare Werte werden als `null` gespeichert, nicht mit erfundenen Platzhalterwerten. Zeitdauern sind ganzzahlige Millisekunden (`*_ms`), Größen Bytes (`*_bytes`), Zeitpunkte RFC 3339 in UTC.

### 3.1 Daten pro Session (`session_quality`)

Der Datensatz wird bei Aktivierung angelegt und bei Ende finalisiert. Zähler und Maximalwerte werden während der Session aktualisiert.

| Feld | Typ / Beispiel | Erfassungszeitpunkt / Zweck |
| --- | --- | --- |
| `session_id_hash` | rotierendes HMAC-Pseudonym | Primärschlüssel; keine Klartext-Session-ID |
| `tenant_id_hash` | HMAC-Pseudonym | Mandantenaggregation und Mandantentrennung |
| `schema_version` | `1` | Kompatible Weiterentwicklung |
| `admin_content_consent_state`, `customer_content_consent_state`, `content_consent_purposes`, `content_consent_categories`, `content_consent_policy_version`, `content_consent_last_changed_at_utc` | Status / Listen / Version / UTC-Zeitpunkt | Nachweisbarer, zweckgebundener Einwilligungsstatus; keine Inhaltsdaten |
| `started_at_utc`, `activated_at_utc`, `ended_at_utc` | RFC 3339 | Lebenszyklus und Dauer |
| `activation_path`, `activation_duration_ms` | Kategorie / Integer | Erfolg und Reibung beim Start |
| `session_outcome`, `end_reason` | `completed`, `abandoned`, `failed`, `timed_out` / normierte Kategorie | Eindeutiger Abschluss und Abbruchanalyse |
| `active_duration_ms` | Integer | Ende minus Aktivierung, Pausen eingeschlossen |
| `admin_connected`, `customer_connected` | Boolean | Voraussetzung für vollständige Gespräche |
| `message_count_total`, `message_count_admin_to_customer`, `message_count_customer_to_admin` | Integer | Nutzungsumfang und Einseitigkeit |
| `translation_count`, `delivered_count`, `failed_count`, `cancelled_count`, `partial_count` | Integer | Gesprächserfolg aus Translation-Datensätzen aggregiert |
| `first_delivery_at_utc`, `last_delivery_at_utc` | RFC 3339 | Zeit bis zur ersten Nutzung und Gesprächsspanne |
| `websocket_connect_attempts`, `websocket_disconnects_unexpected`, `heartbeat_timeouts`, `reconnect_attempts`, `reconnects_successful` | Integer | Verbindungsqualität |
| `fallback_used`, `fallback_count`, `fallback_reason_last`, `fallback_attempted`, `fallback_succeeded` | Boolean / Integer / Kategorie / Boolean / Boolean | Resilienz und Fallback-Nutzung |
| `failed_stage_last`, `failure_count_by_class`, `first_failure_at_utc`, `last_failure_at_utc`, `terminal_error_class`, `terminal_error_code` | Stufe / JSON-Zähler / Zeitpunkte / Kategorien | Nur bei Fehlern oder Timeouts; keine Fehlermeldung im Freitext |
| `transport_primary`, `transport_final` | `websocket`, `polling`, `http` | Transportvergleich |
| `client_platform_admin`, `client_platform_customer` | normierte Kategorie | Clientvergleich |
| `browser_family_*`, `browser_major_*`, `os_family_*`, `device_class_*` | normierte Kategorie | Kompatibilität; `*` steht für beide Rollen |
| `network_quality_initial_*`, `network_quality_worst_*` | `good`, `slow`, `offline`, `unknown` | Einordnung der Verbindung ohne IP-Adresse |
| `release_version`, `pipeline_version` | Versionskennung | Regressionsanalyse |
| `subjective_understanding_rating`, `subjective_speed_rating`, `subjective_usability_rating`, `subjective_trust_rating`, `session_feedback_category`, `feedback_prompt_version`, `feedback_submitted_at_utc` | 1–5 / Kategorie / Version / UTC-Zeitpunkt | ausschließlich freiwilliges, versioniertes Feedback nach Gesprächsende |
| `sampled` | Boolean | korrekte Hochrechnung |

#### Session-Ergebnisdaten

| Fall | Zusätzlich zu erfassende Daten | Zweck |
| --- | --- | --- |
| Immer bei Session-Ende | `session_outcome` (`completed`, `abandoned`, `failed`, `timed_out`), `end_reason`, `active_duration_ms`, alle Nachrichten- und Verbindungszähler | Einheitlicher Terminalstatus und belastbarer KPI-Nenner |
| Erfolgsfall (`session_outcome=completed`) | `first_delivery_at_utc`, `last_delivery_at_utc`, `delivered_count`, Richtungszähler, `transport_final`, `fallback_used`, optionales Session-Feedback | Belegt, dass die Unterhaltung nutzbar war und wie sie abgeschlossen wurde |
| Fehlerfall (`session_outcome=failed` oder `timed_out`) | `failed_stage_last`, `failure_count_by_class`, `first_failure_at_utc`, `last_failure_at_utc`, `end_reason`, `fallback_attempted`, `fallback_succeeded`, `terminal_error_class`, `terminal_error_code` | Ursache, Häufigkeit und Wirkung des Fehlers; keine Fehlermeldung im Freitext |

### 3.2 Daten pro Translation/Nachricht (`translation_quality`)

Eine Zeile entsteht, sobald eine Nachricht zur Verarbeitung akzeptiert wird, und wird erst bei einem Terminalstatus final. Sie umfasst bei Audio auch ASR und TTS, damit die gesamte Ende-zu-Ende-Qualität einer Übersetzung zugeordnet bleibt. Das Feld `translation_id_hash` ist technisch eine Nachrichten-/Verarbeitungs-ID; es enthält keine Inhalte.

| Feld | Typ / Beispiel | Erfassungszeitpunkt / Zweck |
| --- | --- | --- |
| `translation_id_hash` | rotierendes HMAC-Pseudonym | Primärschlüssel und Deduplizierung |
| `session_id_hash` | HMAC-Pseudonym | Fremdschlüssel auf `session_quality` |
| `tenant_id_hash`, `schema_version` | Pseudonym / Integer | Isolation und Schemaversion |
| `sender_content_consent_state_at_acceptance`, `content_storage_decision_by_category`, `content_storage_purposes`, `content_storage_categories` | Status / Kategorie→Entscheidung / Listen | Unveränderliche Entscheidung pro Nachricht, Zweck und Kategorie |
| `content_record_id_hash`, `content_retention_expires_at_utc`, `content_deleted_at_utc` | opake Referenz / UTC-Zeitpunkte | Nur bei erlaubter Inhaltsablage; Referenz und Löschstatus, nie der Inhalt selbst |
| `created_at_utc`, `accepted_at_utc`, `terminal_at_utc` | RFC 3339 | Zeitliche Reihenfolge und Terminalstatus |
| `message_sequence`, `message_direction` | Integer / Richtung | Reihenfolge- und Richtungsanalyse |
| `input_mode` | `audio` / `text` | Pfadvergleich |
| `source_language`, `target_language` | BCP-47-/ISO-Code | Sprachpaar; keine freie Eingabe |
| `input_length_bucket` | `0-20`, `21-80`, `81-200`, `201+` | Längenanalyse ohne Textinhalt |
| `recording_duration_ms`, `input_bytes`, `audio_format`, `sample_rate_hz`, `channels` | technische Werte | nur für Audio; Aufnahme- und Formatqualität |
| `bit_depth`, `processed_input_bytes`, `audio_validation_outcome`, `audio_validation_duration_ms`, `audio_validation_error_code`, `audio_normalization_applied`, `audio_spec_conversion_applied` | technische Werte / Status / Integer / Kategorie / Boolean | Audio-Validierung und Vorverarbeitung ohne Audiodaten |
| `microphone_permission_outcome`, `recording_outcome`, `conversion_outcome` | `success`, `failure`, `not_applicable` | Client-Audiopfad |
| `text_validation_outcome`, `text_validation_duration_ms`, `text_validation_error_code`, `content_filter_outcome` | Status / Integer / Kategorie / Kategorie | Text-Validierung und Filterung ohne Text oder Filtergrund im Freitext |
| `upload_duration_ms`, `upload_retry_count`, `upload_outcome` | Integer / Status | Uploadqualität |
| `pipeline_started_at_utc`, `pipeline_completed_at_utc`, `pipeline_total_duration_ms`, `runtime_cpu_percent`, `runtime_ram_percent` | Zeitpunkte / Integer / Prozent | Gesamtlaufzeit und Ressourcen-Korrelation; keine Prozess-/Host-ID |
| `asr_started_at_utc`, `asr_completed_at_utc`, `asr_duration_ms`, `asr_outcome`, `asr_http_status`, `asr_provider`, `asr_model_version` | Zeitpunkte / Integer / Status / HTTP-Code / Version | ASR-Qualität bei Audio |
| `asr_result_empty`, `asr_corrected_before_send`, `asr_repeated_within_60s` | Boolean | datensparsame ASR-Proxys |
| `translation_started_at_utc`, `translation_completed_at_utc`, `translation_duration_ms`, `translation_outcome`, `translation_http_status`, `translation_provider`, `translation_model_version` | Zeitpunkte / Integer / Status / HTTP-Code / Version | Übersetzungsqualität |
| `translation_tts_variant_provided` | Boolean | Es wurde eine gesonderte TTS-Variante geliefert; deren Text wird nicht gespeichert |
| `refinement_enabled`, `refinement_outcome`, `refinement_started_at_utc`, `refinement_completed_at_utc`, `refinement_duration_ms`, `refinement_changed`, `refinement_model_version`, `refinement_candidate_model_version`, `refinement_candidate_outcome` | Boolean / Status / Zeitpunkte / Integer / Version | Optionales LLM-Refinement und Vergleich ohne Eingabe-/Ausgabetext |
| `tts_started_at_utc`, `tts_completed_at_utc`, `tts_duration_ms`, `tts_outcome`, `tts_http_status`, `tts_provider`, `tts_model_version`, `voice_id`, `tts_output_mime_type`, `tts_output_bytes` | Zeitpunkte / Integer / Status / HTTP-Code / Version / MIME / Integer | Audioausgabe; Stimme als normierte technische ID |
| `asr_model_config_hash`, `translation_model_config_hash`, `tts_model_config_hash`, `refinement_model_config_hash`, `model_deployment_id` | Hash / unveränderliche Kennung | Modellkonfiguration, Prompt-/Glossar-/Decoder-Parameter und Deployment eindeutig vergleichen, ohne Inhalte zu speichern |
| `asr_model_attempt_chain`, `translation_model_attempt_chain`, `tts_model_attempt_chain`, `refinement_model_attempt_chain` | geordnete, begrenzte Liste aus Modellkennung, Konfigurationshash, Ergebnis und Dauer | Primär- und Fallbackmodelle korrekt zurechnen; keine Payloads oder Fehlertexte |
| `experiment_id`, `experiment_arm`, `model_assignment_unit` | Kennung / Kategorie / `session` oder `translation` | Kontrollierte Modellvergleiche und A/B-Tests; tatsächlich verwendetes Modell bleibt zusätzlich maßgeblich |
| `delivery_attempt_count`, `delivery_outcome`, `delivery_latency_ms`, `delivery_transport`, `fallback_used` | Integer / Status / Dauer / Kategorie | Zustellqualität |
| `playback_started`, `playback_completed`, `playback_position_ms`, `output_duration_ms`, `playback_error_class` | Boolean / Integer / Kategorie | Wiedergabequalität, falls clientseitig bestätigbar |
| `terminal_outcome` | `delivered`, `failed`, `cancelled`, `partial`, `expired` | eindeutiger finaler Nenner |
| `completed_stages`, `missing_or_failed_stage` | Liste normierter Stufen | Nur bei Teilerfolg; erreichte und fehlende Pipeline-Stufen |
| `cancel_stage`, `cancel_reason`, `cancelled_at_utc`, `error_class`, `error_code`, `failed_stage`, `failure_at_utc` | normierte Kategorien / UTC-Zeitpunkt | Abbruchursache bzw. Fehlerursache und -zeitpunkt ohne Freitextfehler |
| `attempt_count`, `retry_count`, `timeout_ms_configured`, `circuit_breaker_state`, `fallback_attempted`, `fallback_succeeded`, `client_visible_error_category` | Integer / Integer / Integer / Kategorie / Boolean / Boolean / Kategorie | Fehler- und Recovery-Kontext; nur bei Fehler-/Fallbackpfaden |
| `feedback_rating`, `feedback_type`, `issue_category`, `feedback_stage`, `feedback_question_id`, `feedback_prompt_version` | freiwillig / normiert | kontextbezogenes, versioniertes Nutzerfeedback |
| `release_version`, `pipeline_version`, `client_platform`, `browser_family`, `browser_major`, `os_family`, `device_class`, `network_quality` | normierte Kategorien | Regressions- und Kompatibilitätsanalyse |

#### Abgleich mit den aktuell erzeugten Pipeline-Metadaten

Die implementierte Pipeline erzeugt bereits `pipeline_started_at`, `pipeline_completed_at`, `total_duration_ms`, je Stufe Start-/Endzeit, Dauer, Modell, Ergebnis/Fehler sowie für die Audio-Validierung Format-, Größen-, Normalisierungs- und Konvertierungsdaten. Bei aktivem Refinement entstehen zusätzlich Aktivierung, Dauer, Änderungsflag und primärer/Kandidaten-Modellstatus; außerdem werden CPU- und RAM-Auslastung erfasst.

Diese technischen Werte sind mit den oben ergänzten Feldern nun vollständig als **zulässige Qualitätsmetadaten** abgebildet. Nicht übernommen werden dagegen die derzeit ebenfalls in `debug_info` bzw. `pipeline_metadata` vorhandenen Inhalte: Eingabetext, ASR-Text, Übersetzungstext, `tts_text`, Audio-URLs, Audio-Bytes, rohe Fehlertexte, `error_details` und `refinement_comparison` mit Inhaltsbezug. Für sie gilt weiterhin das Opt-in- und Löschkonzept aus Abschnitt 2.

### 3.3 Modellzuordnung und Vergleichbarkeit

Eine Modellversion allein reicht für einen belastbaren Vergleich nicht aus. Jede Translation erhält deshalb die tatsächlich verwendeten Modellversionen **und** Konfigurations-Hashes je Stufe, die Deployment-ID sowie – falls aktiv – `experiment_id` und `experiment_arm`. Ändert sich Modell, Prompt, Glossar, Decoder-/Temperaturparameter, Provider-Routing oder Serving-Deployment, entsteht eine neue Vergleichseinheit.

### 3.4 Translation-Ergebnisdaten

| Fall | Zusätzlich zu erfassende Daten | Zweck |
| --- | --- | --- |
| Immer bei Terminalstatus | `terminal_outcome`, `created_at_utc`, `accepted_at_utc`, `terminal_at_utc`, `message_sequence`, `message_direction`, `input_mode`, Sprachpaar, Release- und Pipeline-Version | Jeder Auftrag ist eindeutig, zeitlich einordenbar und in den richtigen Nenner aufgenommen |
| Erfolgsfall (`terminal_outcome=delivered`) | `asr_outcome=success` bzw. `not_applicable`, `translation_outcome=success`, `tts_outcome=success` bzw. `not_applicable`, `delivery_outcome=success`, sämtliche Stufen- und `delivery_latency_ms`, `delivery_transport`, `fallback_used`, Wiedergabestatus soweit verfügbar | Ermöglicht Latenz-, Erfolgs- und Clientqualitäts-KPIs ohne Inhalte |
| Teil-Erfolgsfall (`terminal_outcome=partial`) | `completed_stages`, `missing_or_failed_stage`, `delivery_outcome`, `fallback_used`, Felder des Fehlerfalls | Trennt verwertbare Teilergebnisse sauber von vollständigem Erfolg |
| Fehlerfall (`terminal_outcome=failed` oder `expired`) | `failed_stage`, `error_class`, `error_code`, `failure_at_utc`, `attempt_count`, `retry_count`, `timeout_ms_configured`, `circuit_breaker_state`, `fallback_attempted`, `fallback_succeeded`, `client_visible_error_category`, `terminal_outcome` | Root-Cause- und Recovery-Analyse; keine rohen Fehlertexte, Request-Payloads oder Inhalte |
| Nutzerabbruch (`terminal_outcome=cancelled`) | `cancel_stage`, `cancel_reason` (`user_action`, `session_end`, `client_unavailable`, `unknown`), `cancelled_at_utc`, bis dahin abgeschlossene Stufen | Nutzerverhalten von technischen Fehlern trennen |

Bei einem erfolgreichen Terminalstatus müssen `error_class`, `error_code`, `failed_stage` und `client_visible_error_category` leer sein. Bei einem technischen Fehler müssen `failed_stage`, `error_class` und `failure_at_utc` gefüllt sein; `error_code` ist Pflicht, sobald der verursachende Dienst einen stabilen Code liefert.

### 3.5 Fehlerklassifikation und Fehlerdaten

`error_class` ist genau einer dieser Werte: `client_permission`, `client_media`, `client_conversion`, `validation`, `upload_network`, `gateway`, `asr`, `translation`, `tts`, `storage`, `delivery`, `websocket`, `polling`, `timeout`, `rate_limit`, `authentication`, `unknown`.

`outcome` ist `success`, `failure`, `partial` oder `cancelled`. Bei `success` müssen `error_class` und `error_code` leer sein. Bei `failure` müssen beide – soweit bekannt – vorhanden sein.

## 4. Der KPI-Katalog nach Themenbereich

Die folgenden KPIs sind nach ihrem fachlichen Zweck gruppiert. Die Datenmodelle aus Abschnitt 3 legen fest, welche Daten jeweils erhoben werden.

### A. Gespräch, Nutzung und Session (`session_quality`)

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| U1 | Aktivierungs-Erfolgsrate | `Anzahl conversation_activated / Anzahl Aktivierungsversuche` | Mandant, Client, Aktivierungspfad |
| U2 | Gesprächsabschlussrate | `Gespräche mit mindestens 1 delivered-Nachricht je Richtung / aktivierte Gespräche mit zwei verbundenen Seiten` | Sprachpaar, Eingabemodus |
| U3 | Einseitige Gespräche | `Gespräche mit delivered-Nachrichten nur in einer Richtung / aktivierte Gespräche` | Endgrund, Clientseite |
| U4 | Nachrichten pro Gespräch | Verteilung von `message_count` aller beendeten Gespräche | Mandant, Sprachpaar |
| U5 | Aktive Gesprächsdauer | p50/p95 von `active_duration_ms`; Endzeit minus Aktivierung, Pausen eingeschlossen | Endgrund, Client |
| U6 | Vorzeitige Abbruchrate | `Gespräche mit end_reason=abandoned und ohne delivered-Nachricht / aktivierte Gespräche` | Schritt, an dem zuletzt Aktivität lag |
| U7 | Wiederkehrquote | Anteil pseudonymisierter Akteure/Mandanten mit weiterer Aktivierung innerhalb von 7/30 Tagen | nur falls dafür zulässiges, rotierbares Pseudonym existiert |

### B. Eingabe, Verarbeitung und Ausgabe (`translation_quality`)

#### End-to-End-Qualität und Zustellung

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| Q1 | End-to-End-Zustelllatenz | `message_delivered.occurred_at - message_created.client/server reference`; p50/p95/p99, nur erfolgreiche Nachrichten | Text/Audio, Sprachpaar, Transport |
| Q2 | Pipeline-Latenz | `ASR-Ende bzw. Texteingang bis TTS-/Übersetzungsende`; p50/p95/p99 | Stufe, Provider, Modell, Sprache |
| Q3 | Zustellerfolgsrate | `delivered / (delivered + terminal failed)`; `cancelled` separat ausweisen | Transport, Richtung, Fallback |
| Q4 | Zustellzeitüberschreitung | `delivered Nachrichten mit delivery_latency_ms > SLO / delivered Nachrichten` | SLO pro Text/Audio dokumentieren |
| Q5 | Teilverarbeitungsrate | `Nachrichten mit outcome=partial / terminale Nachrichten` | fehlende Stufe, Ursache |
| Q6 | Duplikat-Zustellrate | `Nachrichten mit >1 Empfängerbestätigung / Nachrichten mit >=1 Bestätigung` | Transport, Clientversion |
| Q7 | Reihenfolgefehler | `Gesprächspaare, bei denen Empfänger-Reihenfolge von Sender-Sequenz abweicht / Gespräche mit >=2 Zustellungen` | Transport, Richtung |
| Q8 | Fallback-Erfolgsrate | `via polling delivered / Nachrichten, die auf polling umgestellt wurden` | Fallbackgrund, Client |

#### ASR-Qualität (Audio zu Text)

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| A1 | ASR-Erfolgsrate | `ASR success / alle gestarteten ASR-Aufträge` | Sprache, Modell, Audioformat |
| A2 | ASR-Latenz | p50/p95/p99 von ASR-`duration_ms` | Sprache, Audiolängenkorb, Modell |
| A3 | Realtime-Faktor | `ASR duration_ms / recording_duration_ms`; p50/p95 | Sprache, Modell |
| A4 | Nutzerkorrekturrate | `Audio-Nachrichten mit expliziter Textkorrektur vor Versand / Audio-Nachrichten mit ASR-Ergebnis` | Sprache, Audiolängenkorb |
| A5 | Wiederaufnahme-/Wiederholrate | `Neue Audioaufnahme innerhalb 60 s nach ASR-Ergebnis ohne Versand / ASR-Ergebnisse` | Sprache, Client, Fehlerklasse |
| A6 | Leere-Ergebnisrate | `ASR-success mit leerem/nur-Whitespace Ergebnis / ASR-success` | Audio-Dauerkorb, Sprache |
| A7 | ASR-Feedbackrate negativ | `ASR-feedback rating 1–2 oder issue_category=transcription_incorrect / abgegebene ASR-Bewertungen` | Sprache, Modell |
| A8 | Referenz-Fehlerquote | WER/CER auf **separatem, eingewilligtem und annotiertem** Evaluationskorpus; nicht aus Produktionsinhalten schätzen | Sprache, Domäne, Modell |

Ohne Referenztranskript sind A4–A7 lediglich **Proxys**, keine Wortfehlerrate. Dieses Limit muss im Dashboard sichtbar sein.

#### Übersetzungsqualität

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| T1 | Übersetzungs-Erfolgsrate | `translation success / gestartete Übersetzungen` | Sprachpaar, Provider, Modell |
| T2 | Übersetzungslatenz | p50/p95/p99 von Übersetzungs-`duration_ms` | Sprachpaar, Modell |
| T3 | Negative Übersetzungsbewertung | `rating 1–2 oder issue_category=translation_incorrect / abgegebene Übersetzungsbewertungen` | Sprachpaar, Modellversion |
| T4 | Verständlichkeitsbewertung | Anteil Bewertungen 4–5 sowie Mittelwert; Rücklaufquote immer daneben ausweisen | Sprachpaar, Richtung |
| T5 | Neuversand nach Übersetzung | `Nachrichten mit erneuter Bearbeitung oder neuer Nachricht gleicher Richtung innerhalb 60 s / Übersetzungen` | Sprachpaar, Eingabemodus |
| T6 | Sprachrichtungsfehler | `Ergebnisse mit vom Nutzer gemeldeter falscher Ziel-/Quellsprache / Übersetzungen` | Sprachpaar, Clientversion |
| T7 | Sicherheitskritisches Feedback | Anzahl und Rate von `issue_category=meaning_changed`, `offensive`, `sensitive_context` | Sprachpaar; nur aggregiert und rollenbeschränkt |
| T8 | Referenzqualität | COMET/BLEU plus menschliche MQM-Bewertung auf separatem, freigegebenem Gold-Korpus | Sprachpaar, Modell, Domäne |

#### TTS- und Wiedergabequalität

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| S1 | TTS-Erfolgsrate | `TTS success / gestartete TTS-Aufträge` | Zielsprache, Stimme, Modell |
| S2 | TTS-Latenz | p50/p95/p99 von TTS-`duration_ms` | Textlängenkorb, Zielsprache |
| S3 | Wiedergabestart-Erfolgsrate | `playback action=started / Nachrichten mit bereitgestelltem TTS-Audio` | Browser, OS, Audioformat |
| S4 | Wiedergabeabschlussrate | `playback action=completed / playback action=started` | Browser, Länge |
| S5 | Frühabbruchrate | `Wiedergaben mit action=stopped und playback_position_ms < 80 % output_duration_ms / gestartete Wiedergaben` | Browser, Sprache |
| S6 | Wiederholrate | `Nachrichten mit >=2 Wiedergabestarts / Nachrichten mit >=1 Wiedergabestart` | Sprache, Client |
| S7 | Audio-Feedbackrate negativ | negative TTS-/Audio-Bewertungen geteilt durch abgegebene Audio-Bewertungen | Stimme, Zielsprache |

Ein Wiedergabeabbruch ist kein Qualitätsfehler ohne Nutzerfeedback; er kann auch ein normales Gesprächsmuster sein.

#### Client, Audioaufnahme und Upload

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| C1 | Mikrofonberechtigungs-Erfolgsrate | `permission granted / permission requested` | Browser-Familie, OS |
| C2 | Aufnahme-Erfolgsrate | `recording_finished / recording_started` | Browser, Audioformat |
| C3 | Konvertierungs-Erfolgsrate | `conversion success / conversion started` | Quellcodec, Browser |
| C4 | Upload-Erfolgsrate | `message_upload_completed / Uploadversuche` | Größenkorb, Netzwerkklasse, Client |
| C5 | Upload-Latenz | p50/p95/p99 von `upload_duration_ms` | Größenkorb, Netzwerkklasse |
| C6 | Upload-Durchsatz | `input_bytes / upload_duration_ms * 1000`; Verteilung, keine Einzelwerte | Größenkorb, Netzwerkklasse |
| C7 | Nutzerabbruch während Verarbeitung | `message_cancelled vor terminalem Pipelineergebnis / gestartete Verarbeitungen` | `cancel_stage`, Latenzkorb |
| C8 | Browser-Kompatibilitätsfehler | `client_media + client_conversion Fehler / Aufnahmeversuche` | Browser-Familie und Hauptversion |

### C. Modellspezifische KPIs und Modellentscheidung

Diese KPIs werden immer pro **tatsächlich verwendeter Modellvergleichseinheit** ausgewertet: `provider + model_version + model_config_hash + model_deployment_id`. Bei A/B-Tests kommt `experiment_id + experiment_arm` hinzu. Über Sprachpaare oder Eingabemodi darf nicht ungewichtet aggregiert werden.

| ID | Modell-KPI | Exakte Definition / Formel | Geltung |
| --- | --- | --- | --- |
| M1 | ASR-Referenzfehler | WER und CER auf einem eingefrorenen, repräsentativen Gold-Korpus; Konfidenzintervall je Sprache | ASR-Modelle |
| M2 | ASR-Produktionsproxy | Korrektur-, Wiederholungs- und Leere-Ergebnisrate (A4–A7), jeweils pro Modellvergleichseinheit | ASR-Modelle; kein Ersatz für M1 |
| M3 | Übersetzungs-Referenzqualität | COMET plus menschliche MQM-Bewertung auf demselben Gold-Korpus und denselben Bewertungsrichtlinien | Übersetzungsmodelle |
| M4 | Bedeutungsverlust-Rate | `Feedback issue_category=meaning_changed / Übersetzungen mit Feedback`; Rücklaufquote separat berichten | Übersetzungsmodelle |
| M5 | TTS-Hörqualität | Mittelwert und Anteil 4–5 einer freiwilligen 1–5-Frage zu Verständlichkeit/Natürlichkeit auf einem kontrollierten Hörtest | TTS-Modelle und Stimmen |
| M6 | Erfolgsrate | `success / gestartete Stufenaufrufe` | je ASR-, Übersetzungs-, Refinement- und TTS-Modell |
| M7 | Latenz und Realtime-Faktor | p50/p95/p99 der Stufendauer; bei ASR zusätzlich A3 | je Modell, Sprache und Längenkorb |
| M8 | End-to-End-Nutzen | Q1, Q3, F2, F7 und F8 je Modellarm; nur vergleichbare Sessions | vollständige Modellkonfiguration |
| M9 | Ressourcen-/Kosteneffizienz | CPU-/RAM-Auslastung, Queue-Wartezeit und – sofern verlässlich verfügbar – Kosten pro erfolgreicher Translation | Modell, Deployment, Längenkorb |
| M10 | Regression-Rate | Anteil Kennzahlen, die gegenüber der freigegebenen Baseline außerhalb der vorher definierten Toleranz liegen | Modell-/Konfigurationswechsel |

#### Regeln für Modellvergleiche

1. **Experiment-Einheit:** Für ein Gespräch wird ein Modellarm fest zugewiesen (`model_assignment_unit=session`), damit beide Gesprächsseiten und Nachrichten konsistent bleiben. Eine Zuweisung je Translation ist nur für isolierte, klar gekennzeichnete Tests zulässig.
2. **Stratifizieren:** Modelle nur innerhalb desselben Sprachpaars, Eingabemodus, Längenbereich, Client-Kontexts und Testzeitraums vergleichen. Ein Gesamtwert wird aus diesen Gruppen gewichtet gebildet und zeigt die Gewichte.
3. **Gleiche Grundlage:** Gold-Korpus, Prompt-/Glossarversion, Bewertungsrichtlinie, SLO und Traffic-Split vor dem Test einfrieren. Der Gold-Korpus darf nicht zugleich Trainingsmaterial sein.
4. **Guardrails vor Gewinner:** Ein Modell gewinnt nicht allein durch eine bessere Durchschnittsbewertung. Es darf weder die Fehlerquote, p95-Latenz, Bedeutungsverlust-Rate noch eine definierte Sicherheitsmetrik über die freigegebene Grenze verschlechtern.
5. **Keine voreilige Entscheidung:** Berichten: `n`, Konfidenzintervall, Testzeitraum, Ausschlüsse, Rücklaufquote und tatsächliche Fallback-Quote. Ohne ausreichende Fallzahl lautet die Entscheidung `inconclusive`, nicht „gleich gut“.
6. **Fallback korrekt zurechnen:** Scheitert ein Kandidatenmodell und ein anderes Modell liefert das Ergebnis, zählt der Fehlschlag für den Kandidaten und der Erfolg zusätzlich für das tatsächlich ausliefernde Modell; beide IDs bleiben im Datensatz erhalten.

### D. Verbindung, Resilienz und Betrieb

Die Verbindungs-KPIs R1–R5 stammen aus `session_quality`; die Pipeline- und Kapazitäts-KPIs R6–R10 aus `translation_quality` und der Betriebsmetriken je Dienst. Der Join erfolgt ausschließlich über Zeitfenster, Versionen und pseudonymisierte IDs.

#### Zuverlässigkeit, Recovery und Plattformbetrieb

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| R1 | Verbindungs-Erfolgsrate | `erfolgreich geöffnete WebSockets / Verbindungsversuche` | Client, Netzwerkklasse |
| R2 | Unerwartete Disconnect-Rate | `Disconnects mit reason≠normal_end / aktive Verbindungen` | Grund, Client, Transport |
| R3 | Reconnect-Erfolgsrate | `Reconnect mit erfolgreicher Verbindung binnen 60 s / Reconnectversuche` | Client, Grund |
| R4 | Heartbeat-Timeout-Rate | `Heartbeat-Timeouts / Verbindungsminuten` | Client, Netzwerkklasse |
| R5 | Fallback-Quote | `Nachrichten/Gespräche mit fallback_used=true / Nachrichten/Gespräche gesamt` | Fallbackgrund, Client |
| R6 | Servicefehlerquote | `failure pro Pipeline-Stufe / gestartete Aufträge der Stufe` | Stufe, Fehlerklasse, Provider |
| R7 | Timeout-Quote | `timeout failures / gestartete Aufträge` | Stufe, Konfiguration |
| R8 | Retry-Rate | `Aufträge mit retry_count>0 / gestartete Aufträge` und Verteilung der Wiederholungen | Stufe, Fehlerklasse |
| R9 | Kapazitätsindikator | Queue-Wartezeit, Queue-Tiefe und Sättigung je Dienst; p95 und Maximum | Dienst, Instanzpool |
| R10 | SLO-Erfüllung | Anteil gültiger Messungen, die das je KPI definierte SLO einhalten | SLO-ID, Release |

### E. Nutzerfeedback und Support

| ID | KPI | Exakte Definition / Formel | Aufschlüsselung |
| --- | --- | --- | --- |
| F1 | Feedback-Rücklaufquote | `Nachrichten/Gespräche mit Feedback / Feedbackeinladungen` | Einladungszeitpunkt, Client |
| F2 | Wahrgenommene Verständlichkeit | Anteil SQ1-Bewertungen 4–5 und Mittelwert; „kann ich nicht beurteilen“ separat | Sprachpaar, Eingabemodus |
| F3 | Wahrgenommene Bedienbarkeit | Anteil SQ3-Bewertungen 4–5 und Mittelwert | Client, Gesprächslänge |
| F4 | Problemrate | `Feedback mit issue_category / abgegebenes Feedback` | Kategorie, Pipeline-Stufe |
| F5 | Supportkontakt-Rate | `Gespräche mit verknüpftem Supportfall / beendete Gespräche` | Kategorie, Mandant – nur bei berechtigter Verknüpfung |
| F6 | Reproduzierbarkeit | `Supportfälle mit korrelierbarer, ausreichender Telemetrie / Supportfälle` | Fehlerklasse, Client |
| F7 | Wahrgenommene Geschwindigkeit | Anteil SQ2-Bewertungen 4–5 und Mittelwert | End-to-End-Latenzkorb, Sprachpaar |
| F8 | Vertrauen in SSF | Anteil SQ4-Bewertungen 4–5 und Mittelwert; nur Sessions, in denen SQ4 ausgespielt wurde | Sprachpaar, Fehler-/Latenzkorb |

#### Abschlussfragebogen: subjektive Bewertung mit technischem Bezug

Der Fragebogen erscheint nur nach einer beendeten Session mit mindestens einer zugestellten Nachricht. Er ist freiwillig, überspringbar und für beide Rollen getrennt. Es werden maximal **drei Kernfragen** und **eine rotierende Vertiefungsfrage** angezeigt; eine Skala hat stets fünf gleich gerichtete Antwortwerte. Nicht beantwortet, übersprungen und „kann ich nicht beurteilen“ sind getrennte Zustände und zählen nicht als negative Bewertung.

| ID | Frage im UI | Antwortskala | Gespeichertes Session-Feld | Technischer Bezug für die Auswertung |
| --- | --- | --- | --- | --- |
| SQ1 | „Wie gut konnten Sie Ihr Gegenüber in diesem Gespräch verstehen?“ | 1 `gar nicht` · 2 `eher schlecht` · 3 `teils/teils` · 4 `gut` · 5 `sehr gut` · `kann ich nicht beurteilen` | `subjective_understanding_rating` | Sprachpaar, ASR-Korrektur-/Wiederholrate, leere ASR-Ergebnisse, Übersetzungsfeedback, Wiedergabewiederholungen, Zustellerfolg |
| SQ2 | „Wie zufrieden waren Sie mit der Geschwindigkeit des Gesprächs?“ | 1 `sehr unzufrieden` · 2 `unzufrieden` · 3 `neutral` · 4 `zufrieden` · 5 `sehr zufrieden` | `subjective_speed_rating` | End-to-End-Latenz sowie ASR-, Übersetzungs-, TTS-, Upload- und Zustelllatenz; Fallback und Netzwerkklasse |
| SQ3 | „Wie einfach war es, SSF in diesem Gespräch zu nutzen?“ | 1 `sehr schwierig` · 2 `schwierig` · 3 `weder noch` · 4 `einfach` · 5 `sehr einfach` | `subjective_usability_rating` | Aktivierungsdauer, Berechtigungs-/Aufnahmefehler, Abbrüche, Reconnects, Fallback, Nutzerabbrüche und Client-/Browserdaten |
| SQ4 | „Wie sehr würden Sie sich bei einem wichtigen Gespräch auf SSF verlassen?“ | 1 `gar nicht` · 2 `eher nicht` · 3 `teilweise` · 4 `weitgehend` · 5 `vollständig` · `kann ich nicht beurteilen` | `subjective_trust_rating` | Kombination aus Verständlichkeit, Latenz, Fehlern, Wiederholungen, Verbindungsstabilität und Sprachpaar; als Wahrnehmung, nicht als objektive Genauigkeit auswerten |

**Ausspielung:** SQ1–SQ3 sind der Kern. SQ4 wird bei maximal 25 % der Sessions oder in einer definierten Forschungsphase gezeigt, um Antwortmüdigkeit zu vermeiden. Bei weniger als zwei zugestellten Nachrichten wird SQ1 durch „War das Ergebnis der übersetzten Nachricht für Sie verständlich?“ ersetzt und auf die letzte `translation_id_hash` bezogen.

Nach einer Bewertung von 1 oder 2 kann optional genau eine Folgefrage erscheinen:

> „Was war hauptsächlich das Problem?“

Mehrfachauswahl: `transcription`, `translation`, `audio_playback`, `speed`, `connection`, `usability`, `other`, `not_sure`. Zusätzlich darf der Nutzer optional eine der letzten drei Nachrichten auswählen. Gespeichert wird nur deren `translation_id_hash`, nicht deren Text. Ein Freitextfeld wird nur nach ausdrücklicher Inhalts-/Supporteinwilligung angezeigt und in den getrennten Inhalts-Speicher geschrieben.

#### Regeln für die technische Verknüpfung

1. Jede Antwort erhält `session_id_hash`, Rolle, `feedback_question_id`, `feedback_prompt_version`, `submitted_at_utc` und optional `translation_id_hash`. Dadurch ist sie mit den technischen Daten verknüpfbar, ohne Gesprächsinhalte zu benötigen.
2. Die Auswertung vergleicht nur Antworten mit gleichlautender Frage und gleicher Skalenrichtung. Änderungen an Wortlaut, Skala oder Ausspielregel erhöhen `feedback_prompt_version`.
3. Für jede Auswertung werden `n`, Rücklaufquote, Überspringrate und Anteil „kann ich nicht beurteilen“ ausgewiesen. Ein niedriger Wert bei geringer Rücklaufquote ist kein belastbarer Qualitätsbeleg.
4. Korrelation ist keine Ursache: Eine schlechte Geschwindigkeitsbewertung kann mit hoher End-to-End-Latenz zusammenhängen, beweist aber nicht, dass diese allein die Ursache war. Auffälligkeiten werden mit Session- und Translationdaten sowie Nutzertests überprüft.
5. Negative Bewertungen lösen keine automatische Speicherung von Gesprächsinhalten aus. Die Einwilligungsentscheidung aus Abschnitt 2.1 gilt unverändert.

### F. Ergänzende Messpunkte nach Themenbereich

Diese Liste ergänzt den Katalog um weitere identifizierte Messpunkte. Sie enthält sowohl bereits abgedeckte KPIs als auch mögliche Verfeinerungen und ist nach ihrem fachlichen Bereich gruppiert. Vor einer Implementierung müssen Zweck, Datenquelle, Datenschutzprüfung, Erfassungsaufwand und Mindestfallzahl je Messpunkt entschieden werden.

| Bereich | KPI-Kandidaten | Primäre Erfassungsebene | Datenschutz-/Auswertungshinweis |
| --- | --- | --- | --- |
| Gesprächsfluss | Zeit bis zur ersten erfolgreichen Übersetzung; Zeit zwischen Gesprächsbeiträgen; Unterbrechungen/Overlaps; Anzahl Klärungs- bzw. Reparatursequenzen; Gesprächspausen; Wechsel Audio↔Text; Anteil Gespräche mit nur einer Nachricht; Rückkehr nach Unterbrechung | Session, Translation | Reihenfolge und Zeitstempel genügen; keine Inhalte erforderlich |
| Aufgabenwirkung | Aufgabe laut Nutzer erledigt; Gespräch ohne menschliche Hilfe abgeschlossen; benötigte externe Hilfe; Follow-up-Kontakt nach Gespräch; Zeit bis zur fachlichen Entscheidung/Erledigung | Session, optional externe Fachanwendung | Nur einsetzen, wenn der Nutzungskontext dies rechtfertigt; keine fachlichen Inhalte in SSF-Telemetrie |
| Verständlichkeit | Nutzer markiert „verstanden“/„nicht verstanden“; Anzahl expliziter Rückfragen; Nachricht erneut abgespielt; Übersetzung kopiert/geteilt; Nachricht vor Versand stark bearbeitet; Abweichung zwischen ASR und bearbeitetem Text | Translation, Session | Textabweichung nur bei Einwilligung; sonst Korrektur-/Bearbeitungsflag als Proxy |
| Fachliche Übersetzungsqualität | Terminologiefehler; Zahlen-/Datums-/Währungsfehler; Namensfehler; Negationsfehler; falsche Höflichkeitsform; falsches Register; ausgelassene Information; hinzugefügte Information; Bedeutungsverlust; potenziell schädliche Übersetzung | Translation, Gold-Korpus, freiwilliges Feedback | In Produktion nur strukturierte Meldung; belastbare Bewertung über freigegebenen Gold-Korpus und menschliche Annotation |
| Kontextqualität | Glossar verfügbar/genutzt; Glossar-Trefferquote; Glossar-Override durch Modell; Wissenskontext verfügbar/genutzt; Ergebnisqualität mit/ohne Kontext; Kontextabruf-Latenz; Kontextabruf-Fehler | Translation, Release/Modell | Kontextkennung und Version speichern, nicht den abgerufenen Inhalt ohne Einwilligung |
| ASR und Audio | Stilleanteil; geschätztes Signal-Rausch-Verhältnis; Clipping-Indikator; Lautstärke-/Normalisierungsbedarf; VAD-Fehler; nicht unterstütztes Audioformat; Sprachdetektion stimmt/nicht stimmt; Dialekt-/Akzentproblem | Translation, Modell | Dialekt/Akzent nur bei freiwilliger Angabe, niemals aus Verhalten oder Audio ableiten |
| TTS | Zeit bis hörbarer Start; Audio-Dauer im Verhältnis zum Text; TTS-Abbruch; Lautstärkeproblem; Ausspracheproblem; Natürlichkeitsbewertung; Verständlichkeitsbewertung; Stimme gewechselt; Wiedergabe über externes Gerät fehlgeschlagen | Translation, Modell, Client | Geräteprobleme nur als technische Kategorie erfassen |
| UX und Onboarding | Zeit bis zur ersten erfolgreichen Session; Abbruch je Onboarding-Schritt; Verständnis von Statusmeldungen; Fehlermeldung gesehen/verstanden; Selbstheilung ohne Support; Nutzung von Hilfe/FAQ; Wiederaufnahme einer abgebrochenen Session | Session, Client | „Verstanden“ nur freiwillig abfragen; keine Interaktionsinhalte speichern |
| Barrierefreiheit | Bedienung per Tastatur; Screenreader-Status; Fokusverlust; Kontrast-/Zoom-Konfiguration; Untertitel-/Textmodus-Nutzung; Erfolgsquote je Eingabemethode; benötigte UI-Anpassungen | Session, Client | Screenreader und Bedürfnisse ausschließlich freiwillig und aggregiert erfassen |
| Netzwerk und Geräte | Round-trip-time; Jitter; Paketverlust soweit verfügbar; Wechsel der Netzklasse; Hintergrund-/Foreground-Wechsel; Akku-/Energiesparmodus; Speicher-/CPU-Druck im Client; Gerätekategorie; Bluetooth-Audio-Probleme | Session, Client | Keine IP-Adresse, SSID, exakte Position oder Netzbetreiberkennung speichern |
| Resilienz | Zeit bis Recovery; Anteil automatisch statt manuell behobener Fehler; Datenverlust bei Disconnect; erfolgreiche Fortsetzung nach Reconnect; Wiederherstellung der Nachrichtenreihenfolge; Circuit-Breaker-Auslösung; Circuit-Breaker-Erholungsdauer | Session, Translation, Betrieb | Datenverlust nur als Zähler/Status, nie als verlorener Inhalt |
| Betrieb und Kapazität | Queue-Wartezeit; GPU-/CPU-Sekunden je erfolgreicher Translation; Speicherverbrauch; Modellladezeit; Cache-Hit-Rate; Batch-Größe; Autoscaling-Latenz; Kapazitätsreserve; Kosten pro erfolgreichem Gespräch; Kosten pro Sprachpaar | Betrieb, Translation, Modell | Kosten nur mit definierter Kostenallokation vergleichen |
| Nachhaltigkeit | Energie je Translation; GPU-Auslastung pro erfolgreicher Ausgabe; geschätzte CO₂-Intensität je Deployment-Region; Verhältnis verworfener zu erfolgreicher Verarbeitung | Betrieb, Modell, Release | Schätzmethode, Region und Emissionsfaktor versionieren |
| Sicherheit und Datenschutz | Einwilligungsrate je Zweck; Widerrufe; Zeit bis Löschung; Löschfehler; Zugriff auf Inhalts-Speicher; unzulässige Zugriffsversuche; Ablauf von Aufbewahrungsfristen; Anteil Telemetrie ohne Inhaltsdaten; PII-Erkennung in Freitextfeedback | Mandant, Betrieb, Einwilligungsprotokoll | Zugriff und Löschung auditieren; PII-Funde nicht selbst als Inhalt in Metriken speichern |
| Fairness und Abdeckung | Erfolgs-, Latenz- und Feedbackunterschiede nach Sprachpaar, Schriftart, Audioformat und freiwillig angegebenem Nutzungskontext; unbekannte/unterrepräsentierte Sprachpaare; Mindeststichprobe je Gruppe | Modell, Release, Mandant | Keine sensiblen Eigenschaften aus Verhalten inferieren; kleine Gruppen unterdrücken |
| Modellbetrieb | Routing-Entscheidung; Modell-Fallback; Prompt-/Glossar-/Konfigurationsversion; Modell-Drift gegenüber Gold-Korpus; Qualitätsregression nach Deployment; Qualitäts-Kosten-Latenz-Pareto; Anteil `inconclusive`-Experimente | Translation, Modell, Release | Tatsächlich verwendetes Modell und Fallback-Kette getrennt ausweisen |
| Experimentqualität | Traffic-Split erreicht; Randomisierung korrekt; Cross-over zwischen Testarmen; Stichprobengröße; Abbruchbias; Feedback-Rücklaufbias; Guardrail-Verletzungen; Zeit bis zur Entscheidung | Experiment, Modell, Release | Testeinheit und Ausschlussregeln vor Start festlegen |
| Support und Incident Management | Time to detect; Time to acknowledge; Time to mitigate; Time to resolve; Wiederauftretensrate; Anteil Incidents mit ausreichender Telemetrie; Anteil Supportfälle mit erfolgreicher Reproduktion; Qualität der Nutzerkommunikation während Störungen | Betrieb, Supportfall | Supportfälle nur über pseudonymisierte Referenz verknüpfen |
| Mandanten- und Produktgesundheit | aktive Mandanten; wiederkehrende Nutzung; Nutzungsintensität; Sprachpaar-Abdeckung; Kontingentnutzung; Überschreitungen; Anteil Sessions mit Mehrwertsignal; Supportlast pro Mandant | Mandant, Produktbetrieb | Nur aggregiert; keine problematischen Mandanten- oder Person-Ranglisten |

Zusätzliche Felder, die aus einem Kandidaten entstehen, werden dem passenden Datensatz (`session_quality`, `translation_quality`, Modell-/Release- oder Betriebsmetrik) zugeordnet. Sie dürfen keine hochkardinalen Prometheus-Labels und keine Inhaltsdaten ohne die Einwilligungslogik aus Abschnitt 2.1 erzeugen.

## 5. Feste Dimensionen und Schutz vor Fehlinterpretation

Jeder KPI soll – sofern die Fallzahl ausreichend ist – nach `time_window`, `tenant_id_hash`, `release_version`, `pipeline_version`, `message_direction`, `input_mode`, `source_language`, `target_language`, `transport`, `client_platform`, `browser_family`, `browser_major`, `os_family`, `device_class`, `network_quality`, `provider`, `model_version`, `error_class` und `fallback_used` filterbar sein.

Kleine Gruppen dürfen nicht angezeigt werden: Standard ist `n >= 20`, bei besonders sensiblen Dimensionen `n >= 50`. Im Dashboard stehen immer Zähler (`n`), Zeitraum, Filter, Datenvollständigkeit und Stichprobenquote neben dem Prozentwert. Keine Rangliste von Mandanten oder Sprachen ohne Mindestfallzahl und Konfidenzintervall.

## 6. Qualitäts-SLOs und Alarmierung

Die konkreten Grenzwerte werden nach einer zwei- bis vierwöchigen Baseline beschlossen. Bis dahin gelten keine aus Mittelwerten abgeleiteten Produktversprechen. Pro KPI sind zu hinterlegen: Owner, Messfenster, Ziel, Warnschwelle, kritische Schwelle, Ausschlüsse und Runbook.

Als Startstruktur:

| SLO | Messgröße | Auswertung | Alarmbedingung |
| --- | --- | --- | --- |
| SLO-E2E | Q1 End-to-End p95 | 15-Minuten- und 24-Stunden-Fenster | Budgetverbrauch, nicht ein einzelner Ausreißer |
| SLO-DELIVERY | Q3 Zustellerfolgsrate | rollierende 15 Minuten | Unterschreitung bei ausreichendem `n` |
| SLO-PIPELINE | R6 je Pipeline-Stufe | rollierende 15 Minuten | Fehlerquote über kritischer Schwelle |
| SLO-CONNECT | R1/R4 | rollierende 15 Minuten | Connect- oder Heartbeat-Regressionssignal |
| SLO-QUALITY | A7/T3/F2 | Tages- und Wochenfenster | Signifikanter Anstieg gegenüber Baseline, nicht nur kleiner Rücklauf |

## 7. Abnahmekriterien für die Telemetrie

- Jede erfolgreiche und fehlgeschlagene Nachricht lässt sich ohne Inhaltsdaten entlang von Aufnahme/Text → Upload → ASR → Übersetzung → TTS → Zustellung rekonstruieren.
- Für alle Quotienten sind Zähler, Nenner, Terminalzustände und Ausschlüsse im Dashboard sichtbar.
- Ein Modell-, Provider- oder Releasewechsel kann für mindestens 30 Tage vor/nach dem Wechsel verglichen werden.
- Ein Fehler-Peak lässt sich über `error_class`, Pipeline-Stufe, Client und Release auf eine handhabbare Ursache eingrenzen.
- Rohereignisse und Aggregate werden fristgerecht mandantengetrennt gelöscht; ein Löschtest läuft automatisiert.
- Prometheus-Metriken enthalten keine personenbezogenen oder hochkardinalen Labels.
- Qualitätsbehauptungen zu ASR und Übersetzung werden nur mit Gold-Korpus-Metriken oder klar als Nutzerproxy gekennzeichnet veröffentlicht.

## 8. Nicht als KPI speichern

Nicht in Standardmetriken aufnehmen: vollständige Gesprächsinhalte, Roh-/Output-Audio, Textvorschauen, IP-Adressen, exakte Standortdaten, Cookie-/Werbe-IDs, vollständige User-Agent-Strings, freie Fehlermeldungen, E-Mail-Adressen, Namen, personenbezogene Rollenbezeichnungen und IDs als Metrik-Labels.

Für zeitlich begrenztes Debugging dürfen diese Daten nur nach dokumentierter Freigabe, mit Zweckbindung, Zugriffskontrolle, Auditlog und automatischer Löschung verwendet werden.

## Verwandte Dokumente

- [Audio Recording Monitoring](../guides/audio-recording-monitoring.md)
- [WebSocket Architecture](../architecture/websocket-architecture.md)
- [Customer Journey und Datenschutz](../architecture/customer-journey.md)
- [Deployment Security](../deployment/SECURITY.md)

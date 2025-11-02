# Testübersicht

Diese Datei fasst alle automatisierten Tests im Verzeichnis `tests/` zusammen und beschreibt, welchen Aspekt des Systems jeder Test abdeckt. Die Gruppierung folgt der Struktur der Testdateien und -klassen.

## `tests/test_session_manager.py`

Tests für den In-Memory-/Redis-kompatiblen `SessionManager`, einschließlich paralleler Sessions, Statusverwaltung und WebSocket-Koordination.

### `TestSessionCreationAndLifecycle`
- **test_create_admin_session_creates_new_session** – Stellt sicher, dass eine neue Admin-Session erzeugt wird, eine kurze UUID erhält und im Pending-Status landet.
- **test_multiple_sessions_remain_active** – Verifiziert, dass mehrere Admin-Sessions parallel bestehen bleiben können.
- **test_terminate_all_active_sessions** – Validiert, dass `terminate_all_active_sessions` alle offenen Sessions schließt und den Terminationsgrund konsistent setzt.
- **test_session_activation_flow** – Deckt den Übergang von Pending nach Active ab, sobald ein Kunde beitritt und seine Sprache setzt.
- **test_websocket_termination_notifications** – Überprüft, dass bei Session-Termination WebSocket-Clients eine `session_terminated`-Nachricht erhalten und sauber geschlossen werden.

### `TestSessionStateManagement`
- **test_session_state_transitions** – Testet den vollständigen Lebenszyklus einer Session (Pending → Active → Terminated).
- **test_get_active_session_lookup** – Prüft, dass die jüngste aktive Session oder eine spezifische ID korrekt zurückgegeben wird.

### `TestWebSocketManagement`
- **test_websocket_connection_lifecycle** – Verifiziert das Hinzufügen und Entfernen von WebSocket-Verbindungen inklusive Status-Flags an der Session.
- **test_websocket_cleanup_on_termination** – Prüft, dass beim Beenden einer Session die gespeicherten WebSocket-Verbindungen entfernt werden.

- **test_no_memory_leaks_on_session_switch** – Simuliert wiederholte Session-Wechsel und stellt sicher, dass mehrere Sessions ohne Speicherlecks bestehen können.
- **test_session_history_limiting** – Bestätigt, dass `get_session_history` die Ergebnisliste korrekt auf das gewünschte Limit beschränkt.

## `tests/test_admin_routes.py`

API-Tests für die Admin-Endpunkte der Session-Verwaltung.

### `TestAdminSessionCreation`
- **test_create_admin_session_success** – Prüft den erfolgreichen POST auf `/api/admin/session/create` inkl. Response-Inhalt.
- **test_create_admin_session_failure** – Erwartet HTTP 500, wenn die Session-Erstellung intern eine Exception wirft.
- **test_create_admin_session_no_session_returned** – Validiert den Fehlerfall, wenn nach erfolgreicher Erstellung kein Session-Objekt gefunden wird.

### `TestCurrentSessionRetrieval`
- **test_get_current_session_success** – Stellt sicher, dass Informationen zur aktiven Session geliefert werden.
- **test_get_current_session_with_specific_id** – Validiert, dass eine gewünschte Session-ID via Query-Parameter geladen wird.
- **test_get_current_session_not_found** – Erwartet Status 404, wenn keine aktive Session existiert.

### `TestSessionTermination`
- **test_terminate_session_success** – Überprüft das erfolgreiche Beenden einer Session inklusive Aufrufparameter.
- **test_terminate_session_not_found** – Erwartet 404, wenn eine Session-ID unbekannt ist.
- **test_terminate_already_terminated_session** – Deckt den Fall ab, dass eine bereits terminierte Session erneut beendet wird.

### `TestSessionHistory`
- **test_get_session_history_success** – Prüft, dass die History-Route terminierte Sessions und alle aktiven Sessions liefert.
- **test_get_session_history_with_custom_limit** – Validiert das optionale `limit`-Query-Argument.

### `TestSessionStatus`
- **test_get_session_status_success** – Liefert Statusinformationen zu einer Session.
- **test_get_session_status_not_found** – Erwartet 404 für unbekannte IDs.

### `TestErrorHandling`
- **test_unexpected_error_handling** – Testet, dass interne Fehler als HTTP 500 kommuniziert werden.

### `TestClientURLGeneration`
- **test_client_url_generation** – Überprüft, dass die Client-URL auf Basis der Deployment-Konfiguration korrekt generiert wird.

## `tests/test_websocket_manager.py`

Unit- und Integrationstests für den `WebSocketManager`, einschließlich Heartbeat, Broadcasting und Session-Interaktion.

### `TestWebSocketManager`
- **test_websocket_connection_creation** – Stellt sicher, dass neue Verbindungen registriert werden und ein ACK erhalten.
- **test_session_based_connection_pools** – Prüft die saubere Trennung der Connection-Pools pro Session.
- **test_graceful_disconnect** – Validiert den geordneten Abbau einer Verbindung inklusive Disconnect-Message.
- **test_session_termination_graceful_disconnect** – Stellt sicher, dass alle Verbindungen einer Session beim Termination-Event geschlossen werden.
- **test_heartbeat_system_start_stop** – Startet und stoppt das Heartbeat-Monitoring.
- **test_heartbeat_ping_pong** – Testet Ping/Pong-Handling und Timestamp-Aktualisierung.
- **test_heartbeat_timeout_detection** – Überprüft Timeouts und deren Auswirkungen auf Verbindungsstate und Statistik.
- **test_polling_fallback_activation** – Validiert den Fallback für Clients ohne WebSocket.
- **test_broadcast_to_session** – Testet Broadcasts an alle Teilnehmer einer Session.
- **test_differentiated_broadcasting** – Prüft, dass Sender und Empfänger unterschiedliche Inhalte erhalten können.
- **test_connection_stats_monitoring** – Bewertet die aggregierten Monitoring-Metriken.
- **test_connection_lifecycle_is_alive** – Testet die `is_alive`-Logik für Verbindungen.
- **test_exponential_backoff_calculation** – Überprüft das Reconnect-Backoff.
- **test_error_handling_dead_connections** – Stellt sicher, dass fehlerhafte Verbindungen korrekt markiert werden.
- **test_client_join_leave_notifications** – Testet Join/Leave-Events für Teilnehmer.

### `TestWebSocketIntegration`
- **test_integration_with_session_manager** – Sicherstellt, dass Verbindungen auch im `SessionManager` reflektiert werden.
- **test_session_termination_via_session_manager** – Prüft, dass das Beenden über den `SessionManager` WebSockets schließt.
- **test_parallel_sessions_keep_existing_connections** – Stellt sicher, dass parallele Sessions bestehende WebSocket-Verbindungen nicht trennen.

## `tests/test_unified_message_endpoint.py`

Umfassende Tests für den Unified Message Endpoint sowie die zugehörigen Pydantic-Modelle.

### `TestPydanticModels`
- **test_text_message_request_valid** – Verifiziert, dass valide Requests akzeptiert werden.
- **test_text_message_request_validation_errors** – Deckt verschiedene Eingabe-Fehler (leer, zu lang, nur Whitespace) ab.
- **test_message_response_model** – Prüft das Serienverhalten des Erfolgs-Responsemodells.
- **test_error_response_model** – Testet das Fehler-Responsemodell.

### `TestContentTypeDetection`
- **test_json_content_type_detection** – Erwartet, dass JSON-Requests die Textpipeline triggern.
- **test_multipart_content_type_detection** – Prüft, dass Multipart-Formdaten die Audiopipeline starten.
- **test_unsupported_content_type** – Validiert den HTTP-Fehler bei nicht unterstützten Content-Types.

### `TestTextPipeline`
- **test_text_pipeline_success** – Testet erfolgreichen Textdurchlauf inkl. Übersetzung und TTS.
- **test_text_pipeline_invalid_json** – Erwartet einen 400er bei kaputter JSON-Payload.
- **test_text_pipeline_unsupported_language** – Prüft, dass nicht unterstützte Sprachen abgelehnt werden.

### `TestAudioPipeline`
- **test_audio_pipeline_success** – Deckt den erfolgreichen Audio-Pipeline-Fluss ab.
- **test_audio_pipeline_missing_fields** – Validiert, dass Pflichtfelder im Formular verlangt werden.
- **test_audio_pipeline_invalid_file** – Sichert den Fehlerfall für ungültige Dateiobjekte ab.
- **test_audio_pipeline_processing_error** – Erwartet einen 500er, wenn die Pipeline intern scheitert.

### `TestSessionValidation`
- **test_session_not_found** – Prüft den 404-Fall für unbekannte Sessions.
- **test_session_not_active** – Erwartet einen Fehler, wenn die Session nicht aktiv ist.

### `TestSessionMessageCreation`
- **test_create_session_message** – Stellt sicher, dass Nachrichten persistiert und mit Audio-B64 versehen werden.

### `TestAudioEndpoint`
- **test_get_message_audio_success** – Prüft das Ausliefern gespeicherter WAV-Daten.
- **test_get_message_audio_not_found** – Erwartet 404 bei unbekannter Message-ID.

### `TestEndToEndIntegration`
- **test_text_message_end_to_end** – End-to-End-Test vom JSON-Input bis zur gespeicherten Nachricht inklusive TTS-Ergebnis.

## `tests/test_audio_validation.py`

Einzeltests rund um Audio-Validierung, Normalisierung, Performance und Pipeline-Integration.

### `TestAudioValidation`
- **test_valid_audio_16khz_16bit_mono** – Verifiziert, dass gültige WAV-Dateien akzeptiert werden.
- **test_file_too_large_rejection** – Prüft die Größenbegrenzung.
- **test_wrong_sample_rate_rejection** – Erwartet einen Fehler bei falscher Samplingrate.
- **test_wrong_bit_depth_rejection** – Lehnt unpassende Bit-Tiefen ab.
- **test_stereo_rejection** – Erzwingt Mono-Audio.
- **test_duration_too_short_rejection** – Stellt das Mindestdauer-Limit sicher.
- **test_duration_too_long_rejection** – Validiert das Maximaldauer-Limit.
- **test_invalid_wav_format_rejection** – Fängt nicht-WAV Eingaben ab.
- **test_empty_file_rejection** – Testet den Fehler für leere Dateien.

### `TestAudioNormalization`
- **test_audio_normalization_applied** – Prüft, dass leise Signale bei Bedarf normalisiert werden.
- **test_audio_normalization_disabled** – Erwartet keine Normalisierung, wenn deaktiviert.
- **test_normalize_audio_function** – Testet die Hilfsfunktion `normalize_audio` auf gültige Ausgaben.
- **test_normalize_audio_error_handling** – Sicher, dass Fehlerfall das Original zurückgibt.

### `TestAudioValidationPerformance`
- **test_validation_time_tracking** – Überprüft das Timing der Validierung.
- **test_performance_with_large_valid_file** – Stellt Performancegrenzen bei nahezu maximaler Länge sicher.

### `TestProcessWavIntegration`
- **test_process_wav_with_validation_enabled** – Integriert Audio-Validierung in den kompletten Pipeline-Lauf.
- **test_process_wav_with_validation_failure** – Erwartet Abbruch, wenn Validation scheitert.
- **test_process_wav_validation_disabled** – Prüft den Pfad ohne Validierung.

### `TestAudioValidationEdgeCases`
- **test_exactly_minimum_duration** – Stellt sicher, dass die minimale Dauer akzeptiert wird.
- **test_exactly_maximum_duration** – Prüft die obere Grenze.
- **test_audio_specs_configuration** – Dokumentiert die Standard-Spezifikationen.
- **test_validation_result_dataclass** – Testet die Dataclass für Validierungsergebnisse.

## `tests/test_text_pipeline.py`

Tests für Textvalidierung, Normalisierung, Spam-/Hate-Speech-Erkennung und die textbasierte Pipeline.

### `TestTextValidation`
- **test_valid_text_acceptance** – Validiert die Erfolgsbedingungen.
- **test_text_too_short_rejection** – Prüft das Mindestlängen-Limit.
- **test_text_too_long_rejection** – Erzwingt das Maximallimit.
- **test_exactly_maximum_length** – Sicher, dass 500 Zeichen akzeptiert werden.
- **test_unicode_text_acceptance** – Bestätigt Unicode-Unterstützung.
- **test_invalid_type_rejection** – Fehlerfall für Nicht-String-Eingaben.

### `TestTextNormalization`
- **test_whitespace_normalization** – Entfernt Mehrfach-Whitespace.
- **test_unicode_normalization** – Normalisiert diakritische Zeichen.
- **test_empty_text_normalization** – Gibt leere Strings zurück, wenn Inhalt fehlt.

### `TestSpamDetection`
- **test_normal_text_not_spam** – Positives Szenario.
- **test_repetitive_text_spam** – Erfasst Wiederholungen als Spam.
- **test_excessive_caps_spam** – Erkennt übermäßige Großschreibung.
- **test_character_repetition_spam** – Prüft stark wiederholte Zeichen.
- **test_short_caps_not_spam** – Stellt sicher, dass kurze Großschreibung erlaubt ist.

### `TestHarmfulContentDetection`
- **test_normal_text_not_harmful** – Baseline für harmlose Inhalte.
- **test_hate_speech_detection** – Erfasst Hassrede.
- **test_violence_detection** – Markiert Gewaltanleitungen.
- **test_self_harm_detection** – Erkennt Selbstgefährdung.

### `TestContentFiltering`
- **test_spam_text_rejection** – Sperrt Spam bei aktiviertem Filter.
- **test_harmful_content_rejection** – Sperrt schädliche Inhalte.
- **test_content_filtering_disabled** – Zeigt, dass Filter optional ist.

### `TestTextPipelinePerformance`
- **test_text_pipeline_skips_asr** – Verifiziert, dass die Textpipeline den ASR-Schritt überspringt.
- **test_text_pipeline_performance** – Misst die Laufzeit der Pipeline mit Mock-Services.
- **test_text_validation_failure_stops_pipeline** – Stellt Early-Exit bei Validierungsfehlern sicher.

### `TestTextPipelineIntegration`
- **test_text_pipeline_with_validation_enabled** – Kompletter Erfolgspfad mit Validierung.
- **test_text_pipeline_validation_disabled** – Pfad ohne Validierungsschritt.

## Weitere Skripte im Projektwurzelverzeichnis

Im Repository-Wurzelverzeichnis liegen zusätzliche, manuell startbare Skripte (z. B. `test_audio_validation_integration.py`, `test_invalid_audio_validation.py`), die nicht Teil der automatisierten Suite sind, aber ähnliche Szenarien adressieren.

## `tests/integration_test_audio_validation.py`

Integrationstests, die das Live-API-Gateway über HTTP ansprechen (werden automatisch übersprungen, wenn der Dienst nicht läuft).

- **test_session_audio_valid_input** – Sendet gültige Audio-Daten und erwartet eine erfolgreiche Verarbeitung.
- **test_session_audio_invalid_sample_rate** – Prüft Fehlerverhalten bei falscher Samplingrate.
- **test_session_audio_too_long** – Testet Ablehnung zu langer Audios.
- **test_session_audio_stereo_rejection** – Stellt sicher, dass nur Mono akzeptiert wird.
- **test_api_gateway_health_check** – Überprüft, ob der Gateway erreichbar ist (optional).
- **test_session_text_still_works** – Regressionstest, dass Text-Verarbeitung trotz Audio-Validierung funktioniert.

---

> **Hinweis:** Die Datei wird manuell gepflegt. Bei neuen Tests bitte einen Eintrag ergänzen, damit die Übersicht aktuell bleibt.

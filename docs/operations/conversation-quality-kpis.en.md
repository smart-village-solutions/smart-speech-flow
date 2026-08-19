# Conversation Quality KPI Catalogue

**Status:** Working basis for implementation and dashboarding
**Scope:** SSF conversations with text and/or audio messages; ASR, translation, TTS, delivery, and client experience
**Goal:** Detect quality issues early, classify them reproducibly, and measure improvements without making conversation content part of standard telemetry.

## 1. Measurement Principles

1. **One event, one truth:** Every quality event has a unique `event_id`, UTC timestamp, and schema version; repeated delivery is deduplicated by `event_id`.
2. **Use server time for service and delivery latency:** Client timestamps are only used for local interaction; cross-client latency includes a clock-drift indicator.
3. **Use terminal outcomes as denominators:** A message is counted only after `delivered`, `failed`, `cancelled`, `partial`, or `expired` is known.
4. **Classify every failure:** Each failed stage has exactly one `error_class` and, where available, a stable `error_code`; free-form error text is never a metric label.
5. **Use quantiles, not only averages:** Latency is reported as count, p50, p95, p99, and maximum; averages are supplementary.
6. **Avoid high-cardinality metric labels:** Never use session, message, or user IDs, raw browser versions, IP addresses, or error messages as Prometheus labels.
7. **Preserve comparability:** Record the effective release, pipeline, provider, model, configuration, and deployment version for each measurement.

## 2. Privacy, Consent, and Content Storage

Standard telemetry does **not** store audio, transcripts, translations, names, phone numbers, IP addresses, full user-agent strings, or precise locations. Original input audio follows the existing 24-hour deletion policy.

| Data type | Allowed in standard KPIs | Rule |
| --- | --- | --- |
| Pseudonymous conversation/message ID | Yes | Rotating, non-guessable ID; not a direct personal identifier |
| Audio, transcript, or translation content | Only with valid consent for the specific purpose | Store only in the separate content store; never as a metric label |
| Audio properties | Yes | Duration, size, codec, sample rate, channels, and validation results |
| Language | Yes | Normalized BCP-47/ISO code only |
| Client context | Yes | Browser family/major version, OS family, device class |
| Network | Yes | Network quality and technical measurements; never IP, SSID, exact location, or carrier identity |
| Free-text feedback | Only with opt-in | Separate store, PII filtering, short retention; never a metric label |

Suggested retention: raw events for 30 days, pseudonymous daily aggregates for 13 months, diagnostic data for no more than 7 days, and opted-in content only for the documented purpose and a shorter period. Retention, legal basis, tenant isolation, deletion jobs, and access roles require privacy review before production use.

### 2.1 Consent for Content Data

Content storage is optional, granular, and per person. Without valid consent, content storage is disabled while pseudonymous technical quality data may still be collected. Consent must be clear, demonstrable, purpose-bound, and withdrawable; it must not be preselected or unnecessarily required for core service use. This reflects the GDPR principles of purpose limitation and data minimisation and the conditions for consent in Articles 5 and 7. [GDPR, EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679)

Collect separate decisions for at least `quality_improvement`, `support_diagnostics`, and `model_evaluation`, and separately for `text` (source, ASR, and translated text), `input_audio`, and `output_audio`. Consent for support does not automatically permit model evaluation; consent for text does not automatically permit audio storage.

| Record | Consent fields | Rule |
| --- | --- | --- |
| `session_quality` | `admin_content_consent`, `customer_content_consent` | Role-keyed records containing `state_by_purpose_and_category`, `policy_version`, and `last_changed_at_utc`; each purpose/category decision is `granted`, `denied`, `withdrawn`, or `not_asked` |
| `translation_quality` | `sender_role`, `sender_content_consent_at_acceptance` | Immutable role-keyed snapshot containing the applicable purpose/category decisions and policy version at message acceptance; each category is `allowed`, `denied`, `withdrawn`, or `not_applicable` |
| `translation_quality` | `content_record_id_hash`, `content_retention_expires_at_utc`, `content_deleted_at_utc` | Only where at least one category is allowed; opaque reference and deletion evidence |

#### Separate Content Store

Where a category is allowed, store content in a tenant-isolated, encrypted content store with purpose-, role-, and audit-controlled access. Do not write it to `session_quality`, `translation_quality`, logs, Prometheus, or feedback events.

| Content | Content-store field | Condition |
| --- | --- | --- |
| Source text or ASR result | `source_text` | Sender consent for the selected purpose at acceptance |
| Translation | `translated_text` | Same condition |
| TTS-specific text variant | `tts_text` | Same condition; only when generated |
| Input audio | `input_audio` | `input_audio` category and purpose; 24 hours remains the maximum unless a stricter rule applies |
| TTS output audio | `output_audio` | Only where necessary for the selected purpose |

After withdrawal, no new content is stored. Content previously stored under that consent is identified through `content_record_id_hash` and queued for deletion under the documented deletion rule. The consent ledger contains only evidence metadata and is separate from content.

## 3. Data Model

SSF uses two durable quality records: **`session_quality`**, one row per conversation, and **`translation_quality`**, one row per processed message. Short-lived technical events may populate them but are not a third permanent analytical source. Unavailable values are `null`; durations are integer milliseconds (`*_ms`), sizes are bytes (`*_bytes`), and timestamps are RFC 3339 UTC values.

### 3.1 Session Data (`session_quality`)

| Field group | Fields |
| --- | --- |
| Identity and consent | `session_id_hash`, `tenant_id_hash`, `schema_version`, all session consent fields from section 2.1 |
| Lifecycle | `started_at_utc`, `activated_at_utc`, `ended_at_utc`, `activation_path`, `activation_duration_ms`, `session_outcome`, `end_reason`, `active_duration_ms` |
| Conversation result | `admin_connected`, `customer_connected`, `message_count`, directional message counters, `translation_count`, `delivered_count`, `failed_count`, `cancelled_count`, `partial_count`, `expired_count`, `first_delivery_at_utc`, `last_delivery_at_utc` |
| Connectivity and fallback | WebSocket attempts/disconnects, heartbeat timeouts, reconnect attempts/successes, `fallback_used`, `fallback_count`, `fallback_reason_last`, `fallback_attempted`, `fallback_succeeded`, `transport_primary`, `transport_final` |
| Failure summary | `failed_stage_last`, `failure_count_by_class`, `first_failure_at_utc`, `last_failure_at_utc`, `terminal_error_class`, `terminal_error_code` |
| Client and release | Admin/customer platform, browser family/major version, OS family, device class, initial/worst network quality, `release_version`, `pipeline_version` |
| Subjective feedback | `subjective_understanding_rating`, `subjective_speed_rating`, `subjective_usability_rating`, `subjective_trust_rating`, `session_feedback_category`, `feedback_prompt_version`, `feedback_submitted_at_utc` |
| Sampling | `sampled` |

At session end, always write the terminal outcome and all counters. Successful sessions record delivery and transport details. Failed or timed-out sessions additionally record failure stage, class, code, time range, and fallback result, without raw error text.

### 3.2 Translation/Message Data (`translation_quality`)

| Field group | Fields |
| --- | --- |
| Identity, consent, and timing | `translation_id_hash`, `session_id_hash`, `tenant_id_hash`, `schema_version`, all translation consent/content-reference fields, `created_at_utc`, `accepted_at_utc`, `terminal_at_utc` |
| Message context | `message_sequence`, `message_direction`, `input_mode`, `source_language`, `target_language`, `input_length_bucket` |
| Audio input and validation | Recording duration/size/format/sample rate/channels/bit depth, processed size, validation outcome/duration/error code, normalization and conversion flags, microphone/recording/conversion outcome |
| Text validation | `text_validation_outcome`, `text_validation_duration_ms`, `text_validation_error_code`, `content_filter_outcome` |
| Pipeline context | Pipeline start/completion/total duration, runtime CPU/RAM percentage, upload duration/retries/outcome |
| ASR | Start/completion/duration/outcome/HTTP status/provider/model version, empty-result, correction, and repeat flags |
| Translation | Start/completion/duration/outcome/HTTP status/provider/model version and `translation_tts_variant_provided` |
| Refinement | Enabled/outcome/start/completion/duration/changed/model/candidate model/candidate outcome |
| TTS | Start/completion/duration/outcome/HTTP status/provider/model/voice/output MIME type/output size |
| Delivery and playback | `delivery_started_at_utc`, `delivery_acknowledged_at_utc`, delivery attempts/outcome/latency/transport/fallback, playback start/completion/position/output duration/error class |
| Terminal state | `terminal_outcome`, completed/missing stages, cancel stage/reason/time, error class/code/failed stage/failure time, attempts/retries/timeout/circuit breaker/fallback/client-visible error category |
| Feedback and client | Feedback rating/type/category/stage/question/prompt version; release, pipeline, platform, browser, OS, device, network quality |

`terminal_outcome` is `delivered`, `failed`, `cancelled`, `partial`, or `expired`. Successful records leave failure fields empty. `failed` and `expired` records require `failed_stage`, `error_class`, and `failure_at_utc`; stable service error codes are required where available. Partial records preserve completed and missing stages. Cancelled records preserve the cancel reason and completed stages so that user actions are not confused with technical failures.

### 3.3 Model Assignment and Comparability

Record the actual model and configuration for every stage: `asr_model_config_hash`, `translation_model_config_hash`, `tts_model_config_hash`, `refinement_model_config_hash`, `model_deployment_id`, `experiment_id`, `experiment_arm`, and `model_assignment_unit`. Store bounded ASR, translation, TTS, and refinement attempt chains containing model identifier, configuration hash, outcome, and duration. A changed model, prompt, glossary, decoder parameter, provider route, or deployment is a new comparison unit.

The current pipeline metadata also produces start/end times, total duration, stage duration/model/outcome, audio validation and preprocessing details, refinement status, and CPU/RAM values; all are represented above. Do not copy content-bearing `debug_info` values into standard telemetry: source/ASR/translated/TTS text, audio URLs/bytes, raw error messages, error details, and content-bearing refinement comparisons remain subject to section 2.1.

### 3.4 Error Classification

Use exactly one of: `client_permission`, `client_media`, `client_conversion`, `validation`, `upload_network`, `gateway`, `asr`, `translation`, `tts`, `storage`, `delivery`, `websocket`, `polling`, `timeout`, `rate_limit`, `authentication`, or `unknown`.

## 4. KPI Catalogue by Topic

### A. Conversation, Use, and Session

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| U1 | Activation success rate | `conversation_activated events / activation attempts` | Tenant, client, activation path |
| U2 | Conversation completion rate | `conversations with at least one delivered message in each direction / activated conversations with two connected parties` | Language pair, input mode |
| U3 | One-sided conversations | `conversations with delivered messages in one direction only / activated conversations` | End reason, client side |
| U4 | Messages per conversation | Distribution of `message_count` for all ended conversations | Tenant, language pair |
| U5 | Active conversation duration | p50/p95 of `active_duration_ms`; end time minus activation, including pauses | End reason, client |
| U6 | Early abandonment rate | `conversations with end_reason=abandoned and no delivered message / activated conversations` | Last active step |
| U7 | Return rate | Share of pseudonymous actors/tenants with another activation within 7/30 days | Only where a permitted rotating pseudonym exists |

### B. Input, Processing, and Output

#### End-to-End Delivery

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| Q1 | End-to-end delivery latency | `delivery_acknowledged_at_utc - accepted_at_utc`, using gateway server time for both fields; count, p50/p95/p99, and maximum for delivered messages. Optional client-perceived latency is a separate diagnostic metric and must include clock-drift adjustment | Text/audio, language pair, transport |
| Q2 | Pipeline latency | ASR completion or text acceptance to translation/TTS completion; count, p50/p95/p99, and maximum | Stage, provider, model, language |
| Q3 | Delivery success rate | `delivered / (delivered + failed + expired)`. `cancelled` and `partial` are excluded and must be reported beside it with counts and rates | Transport, direction, fallback |
| Q4 | Delivery SLO breach rate | `delivered messages with delivery_latency_ms > SLO / delivered messages` | Document SLO separately for text/audio |
| Q5 | Partial-processing rate | `terminal_outcome=partial / all terminal outcomes` | Missing stage, cause |
| Q6 | Duplicate delivery rate | `messages with more than one recipient acknowledgement / messages with at least one acknowledgement` | Transport, client version |
| Q7 | Ordering error rate | `conversation-direction pairs whose recipient order differs from sender sequence / conversations with at least two deliveries` | Transport, direction |
| Q8 | Fallback success rate | `messages delivered via polling / messages switched to polling` | Fallback reason, client |

#### ASR Quality

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| A1 | ASR success rate | `successful ASR jobs / started ASR jobs` | Language, model, audio format |
| A2 | ASR latency | Count, p50/p95/p99, and maximum of ASR `duration_ms` | Language, audio-length bucket, model |
| A3 | Real-time factor | `ASR duration_ms / recording_duration_ms`; count, p50/p95/p99, and maximum | Language, model |
| A4 | User correction rate | `audio messages explicitly corrected before sending / audio messages with an ASR result` | Language, audio-length bucket |
| A5 | Re-record/repeat rate | `new recording within 60 seconds of an unsent ASR result / ASR results` | Language, client, error class |
| A6 | Empty-result rate | `successful ASR results that are empty or whitespace-only / successful ASR results` | Audio-duration bucket, language |
| A7 | Negative ASR feedback rate | `ASR ratings 1–2 or issue_category=transcription_incorrect / submitted ASR ratings` | Language, model |
| A8 | Reference error rate | WER/CER on a separate consented and annotated evaluation corpus; never inferred from production content | Language, domain, model |

Without a reference transcript, A4–A7 are production proxies, not word error rate. Dashboards must display this limitation.

#### Translation Quality

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| T1 | Translation success rate | `successful translations / started translations` | Language pair, provider, model |
| T2 | Translation latency | Count, p50/p95/p99, and maximum of translation `duration_ms` | Language pair, model |
| T3 | Negative translation rating | `ratings 1–2 or issue_category=translation_incorrect / submitted translation ratings` | Language pair, model version |
| T4 | Understandability rating | Share of ratings 4–5 and mean; always display response rate | Language pair, direction |
| T5 | Resend after translation | `messages edited or followed by a same-direction message within 60 seconds / translations` | Language pair, input mode |
| T6 | Language-direction error | `results reported with the wrong source or target language / translations` | Language pair, client version |
| T7 | Safety-critical feedback | Count and rate of `issue_category=meaning_changed`, `offensive`, or `sensitive_context` | Language pair; aggregated and role-restricted only |
| T8 | Reference quality | COMET/BLEU plus human MQM on a separate approved gold corpus | Language pair, model, domain |

#### TTS and Playback Quality

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| S1 | TTS success rate | `successful TTS jobs / started TTS jobs` | Target language, voice, model |
| S2 | TTS latency | Count, p50/p95/p99, and maximum of TTS `duration_ms` | Text-length bucket, target language |
| S3 | Playback-start success rate | `playback started / messages with available TTS audio` | Browser, OS, audio format |
| S4 | Playback completion rate | `playback completed / playback started` | Browser, length |
| S5 | Early-stop rate | `playbacks stopped before 80% of output_duration_ms / started playbacks` | Browser, language |
| S6 | Replay rate | `messages with at least two playback starts / messages with at least one playback start` | Language, client |
| S7 | Negative audio feedback rate | `negative TTS/audio ratings / submitted audio ratings` | Voice, target language |

A stopped playback is not a quality failure without user feedback; it may be normal conversation behavior.

#### Client, Audio Recording, and Upload

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| C1 | Microphone-permission success rate | `permission granted / permission requested` | Browser family, OS |
| C2 | Recording success rate | `recording_finished / recording_started` | Browser, audio format |
| C3 | Conversion success rate | `successful conversions / started conversions` | Source codec, browser |
| C4 | Upload success rate | `message_upload_completed / upload attempts` | Size bucket, network class, client |
| C5 | Upload latency | Count, p50/p95/p99, and maximum of `upload_duration_ms` | Size bucket, network class |
| C6 | Upload throughput | `input_bytes / upload_duration_ms * 1000`; distribution, never individual values | Size bucket, network class |
| C7 | User cancellation during processing | `messages cancelled before a terminal pipeline result / started processing jobs` | Cancel stage, latency bucket |
| C8 | Browser compatibility error rate | `client_media plus client_conversion failures / recording attempts` | Browser family and major version |

### C. Model-Specific KPIs and Experiments

Evaluate each model comparison unit as `provider + model_version + model_config_hash + model_deployment_id`, plus experiment ID and arm where applicable. Never aggregate language pairs or input modes without documented weights.

| ID | Model KPI | Definition |
| --- | --- | --- |
| M1 | ASR reference error | WER/CER with confidence intervals on a frozen representative gold corpus |
| M2 | ASR production proxy | A4–A7 by comparison unit; not a replacement for M1 |
| M3 | Translation reference quality | COMET and human MQM using the same corpus and rubric |
| M4 | Meaning-loss rate | Meaning-changed feedback / translations with feedback; report response rate |
| M5 | TTS listening quality | Mean and 4–5 share of a controlled voluntary intelligibility/naturalness test |
| M6 | Stage success rate | Successful stage calls / started stage calls |
| M7 | Latency and real-time factor | Count, p50/p95/p99, and maximum by model, language, and length bucket |
| M8 | End-to-end benefit | Q1, Q3, F2, F7, and F8 for comparable model arms |
| M9 | Resource/cost efficiency | CPU/RAM, queue time, and reliable cost per successful translation |
| M10 | Regression rate | Metrics outside the defined baseline tolerance after a model/configuration change |

Assign a model arm consistently per session unless an isolated per-translation experiment is explicitly intended. Freeze corpus, prompt/glossary version, rubric, SLO, and traffic split before a comparison. A winner must not regress failure rate, p95 latency, meaning-loss rate, or defined safety guardrails. Report `n`, confidence interval, exclusions, feedback response rate, fallback rate, and `inconclusive` where evidence is insufficient. Attribute fallback failures to the attempted model and success to the actually delivering model.

### D. Connectivity, Resilience, and Operations

| ID | KPI | Exact definition / formula | Breakdown |
| --- | --- | --- | --- |
| R1 | Connection success rate | `successfully opened WebSockets / connection attempts` | Client, network class |
| R2 | Unexpected disconnect rate | `disconnects with reason other than normal_end / active connections` | Reason, client, transport |
| R3 | Reconnect success rate | `reconnects completed within 60 seconds / reconnect attempts` | Client, reason |
| R4 | Heartbeat timeout rate | `heartbeat timeouts / connection minutes` | Client, network class |
| R5 | Fallback rate | `messages or conversations with fallback_used=true / total messages or conversations`; report levels separately | Fallback reason, client |
| R6 | Service failure rate | `stage failures / started jobs for that stage` | Stage, error class, provider |
| R7 | Timeout rate | `timeout failures / started jobs` | Stage, configuration |
| R8 | Retry rate | `jobs with retry_count > 0 / started jobs`, plus retry-count distribution | Stage, error class |
| R9 | Capacity indicator | Queue wait, queue depth, and saturation per service; count, p50/p95/p99, and maximum where duration-based | Service, instance pool |
| R10 | SLO compliance | `valid measurements meeting the KPI's documented SLO / valid measurements in the SLO window` | SLO ID, release |

### E. User Feedback and Support

| ID | KPI | Definition |
| --- | --- | --- |
| F1 | Feedback response rate | Sessions/messages with feedback / feedback invitations |
| F2 | Perceived understandability | 4–5 share and mean of SQ1; report “cannot assess” separately |
| F3 | Perceived usability | 4–5 share and mean of SQ3 |
| F4 | Problem rate | Feedback containing an issue category / submitted feedback |
| F5 | Support-contact rate | Conversations linked to an authorised support case / ended conversations |
| F6 | Reproducibility | Support cases with sufficient correlated telemetry / support cases |
| F7 | Perceived speed | 4–5 share and mean of SQ2 |
| F8 | Trust in SSF | 4–5 share and mean of SQ4 where SQ4 was shown |

Show a voluntary, skippable end-of-conversation survey only after a session with at least one delivered message. Ask no more than three core questions and one rotating question, keeping a five-point scale in a single direction:

| ID | UI question | Technical correlation |
| --- | --- | --- |
| SQ1 | “How well could you understand the other person in this conversation?” | Language pair, ASR correction/repeats/empty results, translation feedback, replay, delivery success |
| SQ2 | “How satisfied were you with the speed of the conversation?” | End-to-end, ASR, translation, TTS, upload, and delivery latency; fallback/network quality |
| SQ3 | “How easy was it to use SSF in this conversation?” | Activation duration, permission/recording failures, reconnects, fallback, cancellation, client context |
| SQ4 | “How much would you rely on SSF for an important conversation?” | Understanding, latency, errors, repeats, connection stability, and language pair; perception, not objective accuracy |

SQ1–SQ3 are the core questions. Show SQ4 in at most 25% of sessions or a defined study. Ratings 1–2 may trigger one optional multi-select question: `transcription`, `translation`, `audio_playback`, `speed`, `connection`, `usability`, `other`, or `not_sure`. The user may reference one of the last three messages by `translation_id_hash`; do not store text. A free-text field requires separate content/support consent.

## 5. Supplementary Measurements by Topic

The following measurements extend the catalogue. Before implementation, define purpose, source, privacy review, collection effort, and minimum sample size.

| Topic | Candidate measurements | Primary level |
| --- | --- | --- |
| Conversation flow | Time to first translation, inter-turn time, overlaps, repair sequences, pauses, audio/text switches, one-message conversations, return after interruption | Session, translation |
| Task outcome | User-reported task completion, completion without human help, external help, follow-up contact, time to decision | Session, authorised domain system |
| Comprehension | Understood/not-understood signals, explicit questions, replay, copy/share, major edits, ASR-to-edited-text difference | Translation, session |
| Translation quality | Terminology, numbers/dates/currency, names, negation, politeness/register, omission/addition, meaning loss, harmful translation | Translation, gold corpus, feedback |
| Context quality | Glossary/context available/used, glossary hit/override, quality with/without context, retrieval latency/failure | Translation, release/model |
| Audio/ASR | Silence ratio, estimated SNR, clipping, normalization need, VAD errors, unsupported format, language-detection correctness, voluntarily reported dialect/accent issue | Translation, model |
| TTS | Time to audible start, audio-duration ratio, loudness/pronunciation issues, naturalness/intelligibility, voice changes, external-device failures | Translation, model, client |
| Onboarding/UX | Time to first successful session, drop-off per step, status/error understanding, self-recovery, help use, resumed sessions | Session, client |
| Accessibility | Keyboard use, voluntarily reported screen-reader use, focus loss, contrast/zoom, subtitle/text mode, outcome by input method | Session, client |
| Network/device | RTT, jitter, packet loss where available, network changes, foreground/background, battery-saving mode, client memory/CPU pressure, Bluetooth issues | Session, client |
| Resilience | Recovery time, automatic/manual recovery, disconnect data-loss counter, continuation, ordering recovery, circuit-breaker recovery | Session, translation, operations |
| Capacity/cost | Queue wait, GPU/CPU seconds, memory, model load, cache hits, batch size, autoscaling, capacity reserve, cost per success and language pair | Operations, translation, model |
| Sustainability | Energy per translation, GPU utilisation per success, estimated regional CO2 intensity, discarded-to-successful work ratio | Operations, model, release |
| Security/privacy | Consent and withdrawal rate, deletion latency/failure, content-store access/denials, retention expiry, telemetry without content, PII detection in feedback | Tenant, operations, consent ledger |
| Fairness/coverage | Success, latency, and feedback differences by language pair, script, format, and volunteered context; underrepresented languages and group sample thresholds | Model, release, tenant |
| Model operation | Routing, fallbacks, prompt/glossary/configuration version, drift from gold corpus, deployment regression, quality-cost-latency Pareto, inconclusive experiments | Translation, model, release |
| Experiment quality | Traffic split, randomisation, arm crossover, sample size, dropout/response bias, guardrail breaches, decision time | Experiment, model, release |
| Support/incidents | Detect/acknowledge/mitigate/resolve time, recurrence, telemetry sufficiency, successful reproduction, user communication quality | Operations, support case |
| Tenant/product health | Active/repeat use, use intensity, language coverage, quota use/exceedance, session value signal, support load | Tenant, product operations |

## 6. Analysis Rules, SLOs, and Acceptance Criteria

Filter KPIs, where sample size permits, by time window, tenant, release, pipeline, direction, input mode, language pair, transport, client/platform/browser/OS/device, network quality, provider/model/version, error class, and fallback. Suppress small groups: default `n >= 20`, and `n >= 50` for sensitive dimensions. Always show count, time window, filters, data completeness, and sample rate next to percentages; avoid rankings without adequate sample size and confidence intervals.

Each SLO documents owner, window, target, warning/critical threshold, exclusions, and runbook. Initial SLO groups are end-to-end latency (Q1), delivery success (Q3), pipeline failure (R6), connectivity (R1/R4), and perceived quality (A7/T3/F2). Establish thresholds from a two-to-four-week baseline rather than mean values alone.

Telemetry is acceptable when every successful or failed message can be reconstructed without content across input, upload, ASR, translation, refinement, TTS, and delivery; all ratio numerators, denominators, terminal states, and exclusions are visible; releases/models can be compared; error peaks can be narrowed by stage/class/client/release; retention and tenant-isolated deletion are tested; no personal/high-cardinality metric labels exist; and claims about ASR/translation quality use gold-corpus metrics or are explicitly marked as user proxies.

## 7. Never Store as Standard KPI Data

Do not store full conversation content, raw/input/output audio, text previews, IP addresses, exact locations, advertising/cookie IDs, full user-agent strings, free-form error messages, email addresses, names, personal role labels, or personal identifiers as standard KPI data or labels. Time-limited debugging use requires documented approval, purpose limitation, access control, audit logging, and automatic deletion.

## Related Documents

- [Audio Recording Monitoring](../guides/audio-recording-monitoring.md)
- [WebSocket Architecture](../architecture/websocket-architecture.md)
- [Customer Journey and Privacy](../architecture/customer-journey.md)
- [Deployment Security](../deployment/SECURITY.md)

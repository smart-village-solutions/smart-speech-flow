## 1. Consent state machine

- [ ] 1.1 Add the optional consent field to the session activation request.
- [ ] 1.2 Resolve consent when a pending session is activated, from a live
  Studio read taken through the raw runtime fetcher, not through
  `RuntimePolicyGate.authorize` — the gate increments the discarded-content
  counter on every refusal, and no content write occurs at activation.
- [ ] 1.3 Map the outcome: `disabled` to `policy_disabled`, `ask` with an
  affirmative answer to `granted`, `ask` otherwise to `declined`, a failed read
  to `pending`.
- [ ] 1.4 Refuse activation on a tenant-availability conflict, creating no
  session state.
- [ ] 1.5 Leave consent untouched on a repeated activation of an already-active
  session, including the language-change path at `routes/customer.py:190`, and
  perform no runtime read there.
- [ ] 1.6 Tests for every resolution path and for both repeat-activation paths,
  watched failing first.

## 2. Recording the authorization outcome

- [ ] 2.1 Record each write's authorization outcome against its artefact:
  the message record, the original audio and the synthesized audio, which are
  three separate reads and may disagree.
- [ ] 2.2 Keep the outcome out of participant-facing payloads.
  `SessionMessage.to_dict` is both the Redis payload and the body returned by
  `conversation_service.messages`, so the public shape must not gain the field.
- [ ] 2.3 Restore records written before this change as refused, so legacy
  in-flight content is not retained without an authorization.
- [ ] 2.4 Tests for serialization, for the public response shape, and for the
  legacy default.

## 3. Gate wiring

- [ ] 3.1 Derive a correlation ID in the audio and text input paths, which have
  none today.
- [ ] 3.2 Authorize the original-audio write and record its outcome.
- [ ] 3.3 Authorize the synthesized-audio write and record its outcome.
- [ ] 3.4 Authorize the message-record write and record its outcome.
- [ ] 3.5 Keep the legacy positional call path working for the existing test
  fake; a new required parameter must not break it.
- [ ] 3.6 Bind the gate and its metrics in the application lifespan, against the
  application's Prometheus registry. Catch `StudioRuntimeFlowError` and leave
  the gate unbound rather than failing startup — Studio credentials are absent
  in local development and CI, and an unbound gate already refuses everything.
- [ ] 3.7 Add `STUDIO_RUNTIME_CONFIGURATION_TIMEOUT_SECONDS` with a default of
  5.0, and pass it into the runtime client, which today never receives a
  timeout and silently keeps its constructor default. Do not make it required.
- [ ] 3.8 Bind a permissive gate in the shared test fixtures; let the dedicated
  gate suites override it.
- [ ] 3.9 Tests for the mode-flip criterion, every failure path, one read per
  write, and gateway startup with no Studio configuration.

## 4. Keeping the live path clear

- [ ] 4.1 Keep all three writes where they are, ahead of the participant-visible
  result. They cannot move: `original_audio_available` feeds pipeline metadata
  before the message is built, and `translated_audio_available` gates `audio_url`
  in both the HTTP response and the broadcast.
- [ ] 4.2 Move only the policy reads and the recording of their outcomes behind
  the broadcast, so no read is awaited on the participant-visible path.
  Sequence this as its own commit so it can be reverted alone.
- [ ] 4.3 Test that the participant-visible result is produced without awaiting
  any policy read.
- [ ] 4.4 Test that a declined session still receives translated text, playable
  audio, in-session history, audio replay and reconnection.

## 5. Removal and retention

- [ ] 5.1 Remove refused audio and drop refused messages at session termination,
  leaving authorized content intact.
- [ ] 5.2 Remove refused content for sessions that are never terminated, bounded
  by maximum session lifetime and independent of the retention setting.
- [ ] 5.3 Apply one configurable retention period, default 24 hours, to
  authorized audio and authorized message text, with automatic deletion
  disableable for the tester environment.
- [ ] 5.4 Add expiry for stored message text, which has none today: session
  records are written with no TTL and no sweep, so transcripts and translations
  currently persist indefinitely.
- [ ] 5.5 Tests for termination, abandoned sessions, both retention modes, and
  text expiry.

## 6. Frontend

- [ ] 6.1 Carry the guest's answer on the existing activation request in
  `SessionRepository.activate`. Do not add a second call to the activation
  endpoint: the consent screen already calls `consent.record` and then
  `session.activate`, so a sink posting to the same endpoint would activate
  twice and the consent-less second call would overwrite the answer.
- [ ] 6.2 Remove the stub consent sink and its port once the answer travels with
  activation.
- [ ] 6.3 Leave the consent screen visually unchanged, including when storage is
  disabled.
- [ ] 6.4 Tests that exactly one activation request is sent and that it carries
  the answer in both states.

## 7. Safety and proof

- [ ] 7.1 Assert no conversation content appears in refusal logs, error details
  or audit records.
- [ ] 7.2 Add the isolation check forbidding persistence-authorizing code from
  reading frozen session configuration. Place it under `tests/`, because
  `pytest.ini` sets `testpaths = tests` and a check under `services/*/tests/`
  would never run in CI. Prove it by reintroducing the reference and watching
  it fail.
- [ ] 7.3 Assert a policy read for one tenant never authorizes another tenant's
  write.
- [ ] 7.4 Run the project's own gates and record the state they ran against.

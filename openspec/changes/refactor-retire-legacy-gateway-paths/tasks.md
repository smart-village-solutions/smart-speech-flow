## 1. Compose clean clone (PR 1)
- [x] 1.1 Remove `frontend-archive` from `docker-compose.yml` and its lock row
- [x] 1.2 Guard: every default build context is inside the repository
- [x] 1.3 Production Compose render unchanged; fresh-clone `docker compose build` evidence recorded

## 2. Legacy routes (PR 2)
- [x] 2.1 Delete `/pipeline`, `/upload`, `GET /` and the legacy-only audio-validation branch
- [x] 2.2 Remove import-time `logging.basicConfig`
- [x] 2.3 Delete scripts, tools and docs that target unregistered routes
- [x] 2.4 Consumer search recorded; contract, tenant-matrix and realtime suites green

## 3. One pipeline tail (PR 3)
- [x] 3.1 Characterization tests for both modes
- [x] 3.2 Shared translation → refinement → TTS tail; drift resolved
- [x] 3.3 Shared message completion; table-driven session-language validation
- [x] 3.4 Empty transcript answers 422 `NO_SPEECH_RECOGNIZED`; frontend message
- [x] 3.5 Translation service stops computing `tts_text`

## 4. Exception policy (PR 4)
- [ ] 4.1 Unhandled-error middleware inside CORS
- [ ] 4.2 Reshape-only handlers removed; the rest narrowed
- [ ] 4.3 ASR, TTS and loop-guard defects fixed
- [ ] 4.4 Broad-handler inventory guard

## 5. Module split (PR 5)
- [ ] 5.1 Split modules under the 800-line budget; module-size guard
- [ ] 5.2 WebSocket frame dispatch table

## 6. Release
- [ ] 6.1 Deployed; legacy routes return 404 in production; release check passes

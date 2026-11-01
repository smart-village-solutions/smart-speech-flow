import { useCallback, useState, type Dispatch, type MutableRefObject } from 'react';
import { useServices } from '@/app/providers/services';
import { randomId } from '@/core/ids';
import type { RecordingAsk } from '@/domain/recording/recordingSession.types';
import type { RecordingAction } from './recording.slice';
import { adminRecordingErrorKey } from './recordingErrors';

/**
 * The request dialog reviews the employee release for each section. On a
 * first request it also collects the guest's name and ID check (spec §6). A refusal stays in
 * the dialog; each attempt is a new request.
 */
export function useFirstRequest(
  sessionId: string,
  dispatch: Dispatch<RecordingAction>,
  requestIdRef: MutableRefObject<string | null>,
  refreshRelease: () => Promise<unknown>
) {
  const { recordingSession } = useServices();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One request at a time: a second click would only meet RECORDING_BUSY.
  const [releaseUnavailable, setReleaseUnavailable] = useState(false);
  const [sending, setSending] = useState(false);

  const submit = useCallback(
    async (ask: RecordingAsk) => {
      const id = randomId();
      requestIdRef.current = id;
      setSending(true);
      try {
        const status = await recordingSession.request(sessionId, id, ask);
        setOpen(false);
        dispatch({ type: 'recording/state', status });
      } catch (refused) {
        const key = adminRecordingErrorKey(refused);
        setError(key);
        if (key === 'admin.recording.error.STAFF_RELEASE_TEXT_MISMATCH') {
          try {
            await refreshRelease();
          } catch {
            setReleaseUnavailable(true);
            setError('admin.recording.error.RECORDING_POLICY_UNAVAILABLE');
          }
        }
      } finally {
        setSending(false);
      }
    },
    [dispatch, recordingSession, requestIdRef, sessionId, refreshRelease]
  );

  const show = useCallback(() => {
    setError(null);
    setReleaseUnavailable(false);
    setOpen(true);
  }, []);
  const hide = useCallback(() => setOpen(false), []);

  return { open, error, sending: sending || releaseUnavailable, show, hide, submit };
}

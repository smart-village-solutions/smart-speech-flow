import { useCallback, useState, type Dispatch, type MutableRefObject } from 'react';
import { useServices } from '@/app/providers/services';
import { randomId } from '@/core/ids';
import type { RecordingAsk } from '@/domain/recording/recordingSession.types';
import type { RecordingAction } from './recording.slice';
import { adminRecordingErrorKey } from './recordingErrors';

/**
 * The dialog before a conversation's first request, where the employee may
 * type the guest's name and tick the ID check (spec §6). A refusal stays in
 * the dialog; each attempt is a new request.
 */
export function useFirstRequest(
  sessionId: string,
  dispatch: Dispatch<RecordingAction>,
  requestIdRef: MutableRefObject<string | null>
) {
  const { recordingSession } = useServices();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One request at a time: a second click would only meet RECORDING_BUSY.
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
        setError(adminRecordingErrorKey(refused));
      } finally {
        setSending(false);
      }
    },
    [dispatch, recordingSession, requestIdRef, sessionId]
  );

  const show = useCallback(() => {
    setError(null);
    setOpen(true);
  }, []);
  const hide = useCallback(() => setOpen(false), []);

  return { open, error, sending, show, hide, submit };
}

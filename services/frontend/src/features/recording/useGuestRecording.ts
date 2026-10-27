import { useCallback, useState, type Dispatch } from 'react';
import { useServices } from '@/app/providers/services';
import type { RecordingStatus } from '@/domain/recording/recordingSession.types';
import type { RecordingAction, RecordingSlice } from './recording.slice';

type GuestDispatch = Dispatch<RecordingAction | { type: 'error/raised'; errorKey: string }>;

/** The guest's side: answering the question, and stopping at any time. */
export function useGuestRecording(
  sessionId: string,
  slice: RecordingSlice,
  dispatch: GuestDispatch
) {
  const { recordingSession } = useServices();
  const requestId = slice.request?.requestId ?? null;
  // The request a failed answer belonged to; the dialog shows the failure only for it.
  const [failedRequest, setFailedRequest] = useState<string | null>(null);

  const run = useCallback(
    async (change: () => Promise<RecordingStatus>) => {
      try {
        dispatch({ type: 'recording/state', status: await change() });
      } catch {
        dispatch({ type: 'error/raised', errorKey: 'recording.error' });
      }
    },
    [dispatch]
  );

  const answer = useCallback(
    async (consent: boolean) => {
      if (requestId === null) {
        return;
      }
      try {
        const status = await recordingSession.answer(sessionId, requestId, consent);
        setFailedRequest(null);
        dispatch({ type: 'recording/state', status });
      } catch {
        // The question stays open; the pill would sit behind the dialog's scrim.
        setFailedRequest(requestId);
      }
    },
    [dispatch, recordingSession, requestId, sessionId]
  );

  const stop = useCallback(
    () => void run(() => recordingSession.stop(sessionId, 'customer')),
    [recordingSession, run, sessionId]
  );

  return { answer, stop, answerFailed: requestId !== null && failedRequest === requestId };
}

import { useCallback, useState, type Dispatch } from 'react';
import { useServices } from '@/app/providers/services';
import type { ConsentEvidence, RecordingStatus } from '@/domain/recording/recordingSession.types';
import type { RecordingAction, RecordingSlice } from './recording.slice';
import { guestAnswerErrorKey } from './recordingErrors';

type GuestDispatch = Dispatch<RecordingAction | { type: 'error/raised'; errorKey: string }>;

interface Refusal {
  requestId: string;
  errorKey: string;
}

/** The guest's side: answering the question, and stopping at any time. */
export function useGuestRecording(
  sessionId: string,
  slice: RecordingSlice,
  dispatch: GuestDispatch
) {
  const { recordingSession } = useServices();
  const requestId = slice.request?.requestId ?? null;
  // The last refused answer; the dialog shows it only for its own request.
  const [refusal, setRefusal] = useState<Refusal | null>(null);

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

  /** Resolves to the refusal's i18n key, or null once the answer was taken. */
  const answer = useCallback(
    async (consent: boolean, evidence?: ConsentEvidence): Promise<string | null> => {
      if (requestId === null) {
        return null;
      }
      try {
        const status = await recordingSession.answer(sessionId, requestId, consent, evidence);
        setRefusal(null);
        dispatch({ type: 'recording/state', status });
        return null;
      } catch (error) {
        // The question stays open; the pill would sit behind the dialog's scrim.
        const errorKey = guestAnswerErrorKey(error);
        setRefusal({ requestId, errorKey });
        return errorKey;
      }
    },
    [dispatch, recordingSession, requestId, sessionId]
  );

  const stop = useCallback(
    () => void run(() => recordingSession.stop(sessionId, 'customer')),
    [recordingSession, run, sessionId]
  );

  const answerError = refusal !== null && refusal.requestId === requestId ? refusal.errorKey : null;
  return { answer, stop, answerError };
}

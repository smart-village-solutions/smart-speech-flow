import { useCallback, useEffect, useRef, useState, type Dispatch } from 'react';
import { useServices } from '@/app/providers/services';
import { randomId } from '@/core/ids';
import type {
  ConsentKind,
  PolicyLevel,
  RecordingStatus,
} from '@/domain/recording/recordingSession.types';
import type { RecordingAction, RecordingSlice } from './recording.slice';
import type { BandAction } from './recordingBand';
import { adminRecordingErrorKey } from './recordingErrors';
import { useFirstRequest } from './useFirstRequest';

interface NextRequest {
  kind: ConsentKind;
  idCheck: PolicyLevel | null;
}

type AdminDispatch = Dispatch<RecordingAction | { type: 'error/raised'; errorKey: string }>;

/**
 * The employee's side: whether they may ask, and the band's actions. The
 * availability is read again whenever recording is off, since a refusal or a
 * stop is when it may have changed.
 */
export function useAdminRecording(
  sessionId: string,
  slice: RecordingSlice,
  dispatch: AdminDispatch
) {
  const { recordingSession } = useServices();
  const [canRequest, setCanRequest] = useState(false);
  const [next, setNext] = useState<NextRequest>({ kind: 'first', idCheck: null });
  // The open request's id, needed to cancel it; read back after a reload.
  const requestId = useRef<string | null>(null);
  const first = useFirstRequest(sessionId, dispatch, requestId);
  const { phase } = slice.status;

  useEffect(() => {
    if (phase !== 'off' && phase !== 'asking') {
      return;
    }
    let cancelled = false;
    recordingSession
      .adminView(sessionId)
      .then((view) => {
        if (cancelled) return;
        setCanRequest(view.canRequest);
        setNext({ kind: view.nextConsentKind, idCheck: view.idCheck });
        requestId.current = view.request?.requestId ?? requestId.current;
        dispatch({ type: 'recording/state', status: view.status });
      })
      .catch(() => {
        // Recording unavailable on this gateway: no band, nothing to offer.
        if (!cancelled) setCanRequest(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dispatch, phase, recordingSession, sessionId]);

  const run = useCallback(
    async (change: () => Promise<RecordingStatus>) => {
      try {
        dispatch({ type: 'recording/state', status: await change() });
      } catch (error) {
        dispatch({ type: 'error/raised', errorKey: adminRecordingErrorKey(error) });
      }
    },
    [dispatch]
  );

  const onAction = useCallback(
    (action: BandAction) => {
      if (action === 'request' && next.kind === 'first') {
        first.show();
      } else if (action === 'request') {
        const id = randomId();
        requestId.current = id;
        void run(() => recordingSession.request(sessionId, id));
      } else if (action === 'cancel' && requestId.current !== null) {
        const id = requestId.current;
        void run(() => recordingSession.cancel(sessionId, id));
      } else if (action === 'stop') {
        void run(() => recordingSession.stop(sessionId, 'admin'));
      }
    },
    [first, next.kind, recordingSession, run, sessionId]
  );

  return { canRequest, onAction, firstRequest: { ...first, idCheck: next.idCheck } };
}

import type { Dispatch } from 'react';
import type { ConsentEvidence } from '@/domain/recording/recordingSession.types';
import type { RecordingAction, RecordingSlice } from './recording.slice';
import { GuestRecordingQuestion } from './GuestRecordingQuestion';
import { RecordingIndicator } from './RecordingIndicator';
import { TEXT_CHANGED_KEY } from './recordingErrors';
import type { RecordingBandState } from './useRecordingBand';
import { useConsentText } from './useConsentText';
import { useGuestRecording } from './useGuestRecording';
import { usePlaybackReports } from './usePlaybackReports';
import { useReadAloud } from './useReadAloud';

interface GuestRecordingProps {
  sessionId: string;
  slice: RecordingSlice;
  dispatch: Dispatch<RecordingAction | { type: 'error/raised'; errorKey: string }>;
  band: RecordingBandState;
  /** The guest's language; a change fetches the text in the new one. */
  language: string | null;
}

/** Everything the guest sees of recording: the band, the frame and the question. */
export function GuestRecording({
  sessionId,
  slice,
  dispatch,
  band,
  language,
}: Readonly<GuestRecordingProps>) {
  const { answer, stop, answerError } = useGuestRecording(sessionId, slice, dispatch);
  usePlaybackReports(sessionId, 'customer', band.view?.variant === 'live');
  const request = slice.status.phase === 'asking' ? slice.request : null;
  const text = useConsentText(sessionId, request?.requestId ?? null, language);
  // Here, not in the dialog: a closed question must still stop its reading.
  const voice = useReadAloud(sessionId, request?.requestId ?? null, text.consent?.hash ?? null);

  const onAnswer = async (consent: boolean, evidence?: ConsentEvidence) => {
    // The text changed under the guest: show them the new one before they answer again.
    if ((await answer(consent, evidence)) === TEXT_CHANGED_KEY) text.reload();
  };

  return (
    <>
      <RecordingIndicator band={band} onAction={stop} />
      <GuestRecordingQuestion
        key={request?.requestId ?? 'none'}
        request={request}
        consent={text.consent}
        textFailed={text.failed}
        voice={voice}
        error={answerError}
        onAnswer={(consent, evidence) => void onAnswer(consent, evidence)}
      />
    </>
  );
}

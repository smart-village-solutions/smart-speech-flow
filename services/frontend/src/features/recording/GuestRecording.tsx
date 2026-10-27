import type { Dispatch } from 'react';
import type { RecordingAction, RecordingSlice } from './recording.slice';
import { GuestRecordingQuestion } from './GuestRecordingQuestion';
import { RecordingIndicator } from './RecordingIndicator';
import type { RecordingBandState } from './useRecordingBand';
import { useGuestRecording } from './useGuestRecording';

interface GuestRecordingProps {
  sessionId: string;
  slice: RecordingSlice;
  dispatch: Dispatch<RecordingAction | { type: 'error/raised'; errorKey: string }>;
  band: RecordingBandState;
}

/** Everything the guest sees of recording: the band, the frame and the question. */
export function GuestRecording({
  sessionId,
  slice,
  dispatch,
  band,
}: Readonly<GuestRecordingProps>) {
  const { answer, stop, answerFailed } = useGuestRecording(sessionId, slice, dispatch);
  const request = slice.status.phase === 'asking' ? slice.request : null;

  return (
    <>
      <RecordingIndicator band={band} onAction={stop} />
      <GuestRecordingQuestion
        request={request}
        failed={answerFailed}
        onAnswer={(consent) => void answer(consent)}
      />
    </>
  );
}

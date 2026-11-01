import type { RecordingRequest, RecordingStatus } from '@/domain/recording/recordingSession.types';

/** The conversation's recording state, driven only by the gateway's frames (spec §15). */
export interface RecordingSlice {
  status: RecordingStatus;
  /** The guest's open question; only the guest receives one. */
  request: RecordingRequest | null;
  /** When the last `recording_ping` arrived, in epoch ms. */
  pingAt: number | null;
}

export type RecordingAction =
  | { type: 'recording/state'; status: RecordingStatus }
  | { type: 'recording/request'; request: RecordingRequest }
  | { type: 'recording/ping'; at: number };

export const initialRecording: RecordingSlice = {
  status: { phase: 'off', reason: null, windowId: null, stateVersion: 0, since: null },
  request: null,
  pingAt: null,
};

export function isRecordingAction(action: { type: string }): action is RecordingAction {
  return action.type.startsWith('recording/');
}

export function recordingReducer(slice: RecordingSlice, action: RecordingAction): RecordingSlice {
  switch (action.type) {
    case 'recording/state':
      // A route's answer and the frame describe the same change; whichever is
      // older must not undo the newer one.
      if (action.status.stateVersion < slice.status.stateVersion) {
        return slice;
      }
      return {
        ...slice,
        status: action.status,
        request: action.status.phase === 'asking' ? slice.request : null,
      };

    case 'recording/request':
      return { ...slice, request: action.request };

    case 'recording/ping':
      return { ...slice, pingAt: action.at };
  }
}

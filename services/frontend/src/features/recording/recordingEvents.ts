import type { Dispatch } from 'react';
import type { RealtimeEvent, RealtimeTransport } from '@/core/realtime/realtime.port';
import { toRecordingRequest, toRecordingStatus } from '@/domain/recording/recordingSession.mapper';
import type { RecordingAction } from './recording.slice';
import { adminRecordingCodeKey } from './recordingErrors';

type Handler = (event: RealtimeEvent) => void;

/**
 * The recording frames a screen answers itself (spec §5.2): a state is
 * acknowledged by its version once applied, a ping is answered at once. The
 * gateway stores nothing until both screens have acknowledged ON, so a state
 * older than the one on screen is neither applied nor acknowledged.
 *
 * `appliedVersion` reads the version the screen currently renders.
 */
export function recordingEvents(
  dispatch: Dispatch<RecordingAction | { type: 'error/raised'; errorKey: string }>,
  transport: Pick<RealtimeTransport, 'send'>,
  appliedVersion: () => number
): [string, Handler][] {
  return [
    [
      'recording_state',
      (event) => {
        const status = toRecordingStatus(event);
        if (status === null || status.stateVersion < appliedVersion()) {
          return;
        }
        dispatch({ type: 'recording/state', status });
        // A state frame is contact with the gateway as much as a ping is: a
        // reconnected screen would otherwise read "paused" until the next ping.
        dispatch({ type: 'recording/ping', at: Date.now() });
        transport.send({ type: 'recording_state_ack', state_version: status.stateVersion });
      },
    ],
    [
      'recording_request',
      (event) => {
        const request = toRecordingRequest(event);
        if (request !== null) {
          dispatch({ type: 'recording/request', request });
        }
      },
    ],
    [
      // Only the employee gets these: a guest's yes the archive could not record.
      'recording_error',
      (event) => {
        const code = typeof event.code === 'string' ? event.code : undefined;
        dispatch({ type: 'error/raised', errorKey: adminRecordingCodeKey(code) });
      },
    ],
    [
      'recording_ping',
      () => {
        dispatch({ type: 'recording/ping', at: Date.now() });
        transport.send({ type: 'recording_pong' });
      },
    ],
  ];
}

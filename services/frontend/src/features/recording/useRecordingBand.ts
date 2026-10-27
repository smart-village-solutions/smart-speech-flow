import type { RealtimeStatus } from '@/core/realtime/realtime.port';
import type { ClientRole } from '@/core/roles';
import type { RecordingSlice } from './recording.slice';
import { bandView, isLive, type BandView } from './recordingBand';
import { useNow } from './useNow';

export interface RecordingBandState {
  view: BandView | null;
  now: number;
}

/** The band to show now; the clock runs while recording is not off, for liveness and time. */
export function useRecordingBand(
  role: ClientRole,
  slice: RecordingSlice,
  connection: RealtimeStatus,
  canRequest: boolean
): RecordingBandState {
  const now = useNow(slice.status.phase !== 'off');
  const view = bandView(role, slice, isLive(slice, connection, now), canRequest);
  return { view, now };
}

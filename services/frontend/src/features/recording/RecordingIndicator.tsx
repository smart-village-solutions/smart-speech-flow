import type { BandAction } from './recordingBand';
import { RecordingBand } from './RecordingBand';
import type { RecordingBandState } from './useRecordingBand';

interface RecordingIndicatorProps {
  band: RecordingBandState;
  onAction: (action: BandAction) => void;
}

/** The band, and while recording is live the red frame around the whole screen. */
export function RecordingIndicator({ band, onAction }: Readonly<RecordingIndicatorProps>) {
  if (band.view === null) {
    return null;
  }
  return (
    <>
      {band.view.variant === 'live' && (
        <div
          aria-hidden="true"
          data-recording-frame=""
          className="pointer-events-none fixed inset-0 z-40 border-4 border-recording-live"
        />
      )}
      <RecordingBand view={band.view} now={band.now} onAction={onAction} />
    </>
  );
}

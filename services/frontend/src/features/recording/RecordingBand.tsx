import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import { elapsed, type BandAction, type BandView } from './recordingBand';

const ACTION_KEYS: Record<BandAction, string> = {
  request: 'admin.recording.request',
  cancel: 'admin.recording.cancel',
  stop: 'recording.stop',
};

interface RecordingBandProps {
  view: BandView;
  now: number;
  onAction: (action: BandAction) => void;
}

/**
 * The strip under the header that says whether this conversation is being
 * recorded (SCREEN_SPECS "Recording"). The elapsed time sits outside the
 * status region, so a screen reader announces changes, not every second.
 */
export function RecordingBand({ view, now, onAction }: Readonly<RecordingBandProps>) {
  const { t } = useTranslation();
  const live = view.variant === 'live';
  const { action } = view;

  return (
    <div
      data-recording-band={view.variant}
      className="fixed inset-x-0 top-header z-10 flex h-recording-band justify-center"
    >
      <div
        className={cn(
          'flex w-full justify-center',
          live
            ? 'bg-recording-live text-white'
            : 'border-b border-border-status bg-surface-status text-fg-status'
        )}
      >
        <div className="flex w-full max-w-app items-center justify-between gap-3 px-5 text-label font-medium">
          <div className="flex min-w-0 items-center gap-2">
            {live && (
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-full bg-white motion-safe:animate-pulse"
              />
            )}
            <output lang={view.language} className="min-w-0 text-wrap">
              {view.labelText ?? t(view.labelKey)}
              {view.detailText !== undefined
                ? ` · ${view.detailText}`
                : view.detailKey !== null && ` · ${t(view.detailKey)}`}
            </output>
            {view.since !== null && (
              <span className="shrink-0 font-semibold tabular-nums">
                {elapsed(view.since, now)}
              </span>
            )}
          </div>
          {action !== null && (
            <button
              type="button"
              onClick={() => onAction(action)}
              className={cn(
                'shrink-0 rounded-pill border px-3 py-1 text-meta font-medium transition-colors duration-150',
                live
                  ? 'border-white hover:bg-white/10'
                  : 'border-border-card text-fg-body hover:bg-surface-row-hover'
              )}
            >
              {t(ACTION_KEYS[action])}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

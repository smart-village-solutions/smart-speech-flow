import type { CSSProperties, Ref } from 'react';
import { cn } from '@/lib/cn';
import { Waveform } from './Waveform';

function formatSeconds(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0');
  const rest = Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0');
  return `${minutes}:${rest}`;
}

interface RecordingBubbleProps {
  /** Measured input loudness, one entry per committed bar. */
  levels: number[];
  elapsedSeconds: number;
  totalSeconds: number;
  className?: string;
  style?: CSSProperties;
  ref?: Ref<HTMLDivElement>;
}

/** The live waveform and countdown shown while the microphone is open. */
export function RecordingBubble({
  levels,
  elapsedSeconds,
  totalSeconds,
  className,
  style,
  ref,
}: Readonly<RecordingBubbleProps>) {
  return (
    <div
      ref={ref}
      style={style}
      className={cn(
        'ms-bubble-inset me-bubble-gutter max-w-bubble rounded-bubble-self border border-border-card bg-surface-card p-4 shadow-xl',
        className
      )}
    >
      <div className="mb-3">
        <Waveform activeBars={levels.length} barColorClass="bg-recording" heights={levels} />
      </div>
      <div className="flex justify-between text-caption font-medium tabular-nums text-fg-muted">
        <span>{formatSeconds(elapsedSeconds)}</span>
        <span>-{formatSeconds(totalSeconds - elapsedSeconds)}</span>
      </div>
    </div>
  );
}

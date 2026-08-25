import { BAR_COUNT, WAVE_HEIGHTS } from '@/core/audio/waveform';
import { cn } from '@/lib/cn';

interface WaveformProps {
  activeBars: number;
  /** Tailwind background class for filled bars. */
  barColorClass: string;
  /**
   * Bar heights as fractions of the container, 0 to 1. Real audio supplies
   * these; without them the design's decorative shape is drawn, whose leading
   * bars are flat 4px stubs. Measured audio has no such lead-in.
   *
   * Fewer than `BAR_COUNT` heights draws a part-finished waveform: the row
   * still reserves every slot, so bars keep their width as they accumulate
   * instead of stretching across the bubble and shrinking as more arrive.
   */
  heights?: number[];
}

export function Waveform({ activeBars, barColorClass, heights = WAVE_HEIGHTS }: WaveformProps) {
  return (
    <div className="flex h-10 items-center gap-[3px] overflow-hidden" aria-hidden="true">
      {Array.from({ length: BAR_COUNT }, (_, index) => {
        const height = heights[index];

        if (height === undefined) {
          return <div key={index} className="flex-1" />;
        }

        return (
          <div
            key={index}
            className={cn(
              'flex-1 rounded-full transition-colors duration-75',
              index < activeBars ? barColorClass : 'bg-surface-wave-idle'
            )}
            style={{ height: height === 0 ? '4px' : `${height * 100}%` }}
          />
        );
      })}
    </div>
  );
}

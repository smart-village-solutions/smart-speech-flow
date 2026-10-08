import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import { range } from '@/lib/range';

interface ScaleInputProps {
  min: number;
  max: number;
  value: number | null;
  onChange: (value: number) => void;
  minLabel?: string;
  maxLabel?: string;
}

/**
 * Both rows are plain flex rows, so under dir="rtl" the lowest value and its
 * label sit on the right together.
 */
export function ScaleInput({
  min,
  max,
  value,
  onChange,
  minLabel,
  maxLabel,
}: Readonly<ScaleInputProps>) {
  const { t } = useTranslation();
  const labelled = minLabel !== undefined || maxLabel !== undefined;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1">
        {range(min, max).map((score) => (
          <button
            key={score}
            type="button"
            aria-label={t('feedback.nps.option', { score })}
            aria-pressed={value === score}
            onClick={() => onChange(score)}
            className={cn(
              'size-8 rounded-lg text-meta font-semibold transition-all duration-100 active:scale-95',
              value === score
                ? 'bg-accent text-accent-on'
                : 'bg-surface-nps text-fg-icon hover:bg-surface-nps-hover'
            )}
          >
            {score}
          </button>
        ))}
      </div>
      {labelled && (
        <div className="flex justify-between text-caption text-fg-muted">
          <span>{minLabel}</span>
          <span>{maxLabel}</span>
        </div>
      )}
    </div>
  );
}

import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';

interface NpsScaleProps {
  value: number;
  onChange: (value: number) => void;
}

export function NpsScale({ value, onChange }: Readonly<NpsScaleProps>) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-wrap gap-1">
      {Array.from({ length: 11 }, (_, score) => (
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
  );
}

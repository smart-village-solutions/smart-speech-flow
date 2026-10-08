import { useState } from 'react';
import { Star } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';
import { range } from '@/lib/range';

interface StarRatingProps {
  min: number;
  max: number;
  value: number | null;
  onChange: (value: number) => void;
}

/** The question around it is the group, so this is not a fieldset of its own. */
export function StarRating({ min, max, value, onChange }: Readonly<StarRatingProps>) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState<number | null>(null);
  const shown = hovered ?? value;

  return (
    <div className="flex gap-1">
      {range(min, max).map((score) => (
        <button
          key={score}
          type="button"
          aria-label={t('feedback.stars', { count: score })}
          aria-pressed={value === score}
          onMouseEnter={() => setHovered(score)}
          onMouseLeave={() => setHovered(null)}
          onClick={() => onChange(score)}
          className="transition-transform duration-75 active:scale-90"
        >
          <Star
            size={22}
            strokeWidth={1.5}
            className={cn(
              shown !== null && shown >= score ? 'fill-accent text-accent' : 'text-fg-faint'
            )}
          />
        </button>
      ))}
    </div>
  );
}

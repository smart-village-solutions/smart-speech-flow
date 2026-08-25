import { useState } from 'react';
import { Star } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/cn';

interface StarRatingProps {
  value: number;
  onChange: (value: number) => void;
  /** Names the group for assistive technology. */
  label: string;
}

export function StarRating({ value, onChange, label }: Readonly<StarRatingProps>) {
  const { t } = useTranslation();
  const [hovered, setHovered] = useState(0);

  return (
    // <fieldset> carries role="group" itself; Tailwind's preflight strips its
    // default border, padding and margin.
    <fieldset aria-label={label} className="flex gap-1">
      {[1, 2, 3, 4, 5].map((score) => {
        const filled = (hovered || value) >= score;

        return (
          <button
            key={score}
            type="button"
            aria-label={t('feedback.stars', { count: score })}
            aria-pressed={value === score}
            onMouseEnter={() => setHovered(score)}
            onMouseLeave={() => setHovered(0)}
            onClick={() => onChange(score)}
            className="transition-transform duration-75 active:scale-90"
          >
            <Star
              size={22}
              strokeWidth={1.5}
              className={cn(filled ? 'fill-accent text-accent' : 'text-fg-faint')}
            />
          </button>
        );
      })}
    </fieldset>
  );
}

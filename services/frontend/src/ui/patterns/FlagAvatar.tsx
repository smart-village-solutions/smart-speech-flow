import { cn } from '@/lib/cn';
import type { Language } from '@/domain/language/language.types';
import { flagCodeFor } from './flags';

interface FlagAvatarProps {
  language: Language;
  size?: '2xs' | 'xs' | 'sm' | 'lg';
  className?: string;
}

/** `2xs` is the session status pill, `xs` the session-list row. */
const DIMENSION = {
  '2xs': 'size-flag-pill',
  xs: 'size-flag-row',
  sm: 'size-10',
  lg: 'size-flag-lg',
} as const;

export function FlagAvatar({ language, size = 'sm', className }: Readonly<FlagAvatarProps>) {
  const flagCode = flagCodeFor(language.code);
  const dimension = DIMENSION[size];

  return (
    <div
      className={cn(
        'relative shrink-0 overflow-hidden rounded-full border border-flag-ring',
        dimension,
        className
      )}
    >
      {flagCode === null ? (
        <span className="flex size-full items-center justify-center bg-surface-field text-meta font-semibold text-fg-muted">
          {language.code.toUpperCase()}
        </span>
      ) : (
        <img
          src={`/flags/${flagCode}.png`}
          alt={language.english}
          className="size-full object-cover"
          draggable={false}
        />
      )}
    </div>
  );
}

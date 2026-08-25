import { cn } from '@/lib/cn';
import type { Language } from '@/domain/language/language.types';
import { flagCodeFor } from './flags';

interface FlagAvatarProps {
  language: Language;
  size?: 'sm' | 'lg';
  className?: string;
}

export function FlagAvatar({ language, size = 'sm', className }: FlagAvatarProps) {
  const flagCode = flagCodeFor(language.code);
  const dimension = size === 'sm' ? 'size-10' : 'size-flag-lg';

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

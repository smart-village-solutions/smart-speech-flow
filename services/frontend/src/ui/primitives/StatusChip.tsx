import type { HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import { STATUS_TONES, type StatusTone } from './statusTones';

interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: StatusTone;
  showIndicator?: boolean;
}

/** Static status text; the caller chooses whether changes need a live region. */
export function StatusChip({
  tone = 'neutral',
  showIndicator = true,
  children,
  className,
  ...props
}: Readonly<StatusChipProps>) {
  return (
    <span
      className={cn(
        'inline-flex h-9 items-center gap-2 rounded-pill border px-3 text-note font-medium leading-chat',
        STATUS_TONES[tone],
        className
      )}
      {...props}
    >
      {showIndicator && <span aria-hidden className="size-2 shrink-0 rounded-full bg-current" />}
      {children}
    </span>
  );
}

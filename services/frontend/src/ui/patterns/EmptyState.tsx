import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'children'> {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}

/** Content and optional recovery action; no unsolicited live announcement. */
export function EmptyState({
  title,
  description,
  action,
  className,
  ...props
}: Readonly<EmptyStateProps>) {
  return (
    <div
      className={cn(
        'flex flex-col items-start gap-3 rounded-2xl border border-border-card bg-surface-card p-5',
        className
      )}
      {...props}
    >
      <h3 className="text-thanks font-semibold leading-chat text-fg-strong">{title}</h3>
      {description && (
        <p className="text-note leading-chat text-fg-essential-muted">{description}</p>
      )}
      {action && <div>{action}</div>}
    </div>
  );
}

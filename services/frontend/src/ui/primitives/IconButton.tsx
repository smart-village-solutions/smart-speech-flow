import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** Required: these buttons carry an icon only. */
  label: string;
  tone?: 'default' | 'close';
  size?: 'small' | 'medium' | 'large';
  children: ReactNode;
}

export function IconButton({
  label,
  tone = 'default',
  size,
  className,
  children,
  type = 'button',
  ...props
}: Readonly<IconButtonProps>) {
  const resolvedSize = size ?? (tone === 'close' ? 'small' : 'medium');
  return (
    <button
      type={type}
      aria-label={label}
      className={cn(
        'focus-ring hit-target relative flex shrink-0 items-center justify-center rounded-full transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 aria-pressed:bg-surface-icon-hover aria-pressed:text-fg-strong',
        tone === 'default'
          ? 'text-fg-icon hover:bg-surface-icon-hover hover:text-fg-strong'
          : 'text-fg-icon-close hover:bg-surface-icon-hover hover:text-fg-strong',
        { small: 'size-8', medium: 'size-9', large: 'size-16' }[resolvedSize],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

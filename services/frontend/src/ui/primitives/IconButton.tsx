import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label'> {
  /** Required: these buttons carry an icon only. */
  label: string;
  tone?: 'default' | 'close';
  children: ReactNode;
}

export function IconButton({
  label,
  tone = 'default',
  className,
  children,
  type = 'button',
  ...props
}: Readonly<IconButtonProps>) {
  return (
    <button
      type={type}
      aria-label={label}
      className={cn(
        'flex items-center justify-center rounded-full transition-colors duration-150',
        tone === 'default'
          ? 'size-9 text-fg-icon hover:bg-surface-icon-hover hover:text-fg-strong'
          : 'size-8 text-fg-icon-close hover:bg-surface-icon-hover hover:text-fg-strong',
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

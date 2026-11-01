import type { Ref, TextareaHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  ref?: Ref<HTMLTextAreaElement>;
  variant?: 'plain' | 'field';
}

export function Textarea({ className, variant = 'plain', rows = 3, ...props }: Readonly<TextareaProps>) {
  return (
    <textarea
      rows={rows}
      className={cn(
        'focus-ring w-full resize-none text-body leading-chat text-fg-chat outline-none placeholder:text-fg-placeholder disabled:cursor-not-allowed disabled:opacity-50',
        variant === 'plain' ? 'bg-transparent aria-invalid:shadow-[inset_0_0_0_1px_var(--fg-status-alert)]' : 'rounded-xl border border-border-field bg-surface-field px-4 py-3 text-fg-body aria-invalid:border-fg-status-alert',
        className
      )}
      {...props}
    />
  );
}

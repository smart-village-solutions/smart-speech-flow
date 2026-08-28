import { useId } from 'react';
import type { InputHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> {
  label: string;
  /** The user-menu forms label their fields by placeholder, as the export does. */
  labelHidden?: boolean;
  density?: 'default' | 'compact';
  /** Shown under the field and announced; also marks the input invalid. */
  error?: string | null;
  className?: string;
}

const DENSITY = {
  default: 'rounded-row px-3 py-2.5 text-note',
  compact: 'rounded-xl px-3 py-2 text-label',
} as const;

export function TextField({
  label,
  labelHidden = false,
  density = 'default',
  error = null,
  className,
  type = 'text',
  ...props
}: Readonly<TextFieldProps>) {
  const id = useId();

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={id}
        className={labelHidden ? 'sr-only' : 'text-label font-medium text-fg-body'}
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        aria-invalid={error === null ? undefined : true}
        aria-describedby={error === null ? undefined : `${id}-error`}
        className={cn(
          'w-full border border-border-card bg-surface-field text-fg-strong outline-none',
          'placeholder:text-fg-placeholder focus:border-accent',
          DENSITY[density],
          error === null ? undefined : 'border-fg-status-alert',
          className
        )}
        {...props}
      />
      {error === null ? null : (
        <p id={`${id}-error`} role="alert" className="text-meta text-fg-status-alert">
          {error}
        </p>
      )}
    </div>
  );
}

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
  default: 'rounded-row px-3 py-field-y text-body',
  compact: 'rounded-xl px-3 py-field-y-compact text-body',
} as const;

export function TextField({
  label,
  labelHidden = false,
  density = 'default',
  error = null,
  className,
  type = 'text',
  'aria-describedby': describedBy,
  'aria-invalid': invalid,
  ...props
}: Readonly<TextFieldProps>) {
  const id = useId();

  return (
    <div className="flex flex-col gap-field-gap">
      <label
        htmlFor={id}
        className={labelHidden ? 'sr-only' : 'text-label font-medium leading-snug text-fg-body'}
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        aria-invalid={error === null ? invalid : true}
        aria-describedby={[describedBy, error === null ? undefined : `${id}-error`].filter(Boolean).join(' ') || undefined}
        className={cn(
          'focus-ring w-full border border-border-field bg-surface-field leading-snug text-fg-strong outline-none disabled:cursor-not-allowed disabled:opacity-50',
          'placeholder:text-fg-placeholder focus:border-accent aria-invalid:border-fg-status-alert aria-invalid:focus:border-fg-status-alert',
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

import { useId, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
}

export function Checkbox({ checked, onCheckedChange, children, className, disabled = false }: Readonly<CheckboxProps>) {
  const id = useId();

  return (
    <label
      htmlFor={id}
      className={cn('group flex min-h-12 cursor-pointer items-start gap-3 py-3', disabled && 'cursor-not-allowed opacity-50', className)}
    >
      <span className="relative mt-0.5 shrink-0">
        <input
          id={id}
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onCheckedChange(event.target.checked)}
        />
        <span
          aria-hidden="true"
          className={cn(
            'flex size-5 items-center justify-center rounded-box border-2 transition-colors duration-150 peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus',
            checked
              ? 'border-accent bg-accent'
              : cn('border-border-checkbox bg-transparent', !disabled && 'group-hover:border-border-checkbox-hover')
          )}
        >
          {checked && (
            <svg className="size-3 text-accent-on" viewBox="0 0 12 12" fill="none">
              <path
                d="M2 6l3 3 5-5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </span>
      </span>
      <span className={cn('text-note leading-snug tracking-prose text-fg-consent transition-colors duration-150', !disabled && 'group-hover:text-fg-consent-hover')}>
        {children}
      </span>
    </label>
  );
}

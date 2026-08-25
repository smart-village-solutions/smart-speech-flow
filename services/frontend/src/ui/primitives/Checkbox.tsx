import { useId, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  children: ReactNode;
  className?: string;
}

export function Checkbox({ checked, onCheckedChange, children, className }: CheckboxProps) {
  const id = useId();

  return (
    <label htmlFor={id} className={cn('group flex cursor-pointer items-start gap-3', className)}>
      <span className="relative mt-0.5 shrink-0">
        <input
          id={id}
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(event) => onCheckedChange(event.target.checked)}
        />
        <span
          aria-hidden="true"
          className={cn(
            'flex size-5 items-center justify-center rounded-box border-2 transition-colors duration-150',
            checked
              ? 'border-accent bg-accent'
              : 'border-border-checkbox bg-transparent group-hover:border-border-checkbox-hover'
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
      <span className="text-note leading-snug tracking-prose text-fg-consent transition-colors duration-150 group-hover:text-fg-consent-hover">
        {children}
      </span>
    </label>
  );
}

import type { ButtonHTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/cn';

const button = cva(
  'inline-flex items-center justify-center gap-2 transition-all duration-200 disabled:cursor-not-allowed',
  {
    variants: {
      variant: {
        pill: 'h-10 w-full rounded-pill text-body font-medium tracking-button active:scale-[0.98] disabled:opacity-40',
        sheet: 'w-full rounded-2xl py-3.5 text-body font-semibold active:scale-[0.98]',
        compact: 'rounded-full px-6 py-2.5 text-note font-semibold',
      },
    },
    defaultVariants: { variant: 'pill' },
  }
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>;

/**
 * Accent colouring comes from the brand tokens, so a disabled sheet button is
 * styled by the caller: the export uses a distinct muted surface for it.
 */
export function Button({ className, variant, type = 'button', ...props }: Readonly<ButtonProps>) {
  return <button type={type} className={cn(button({ variant }), className)} {...props} />;
}

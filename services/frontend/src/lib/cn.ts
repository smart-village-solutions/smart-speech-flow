import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/**
 * The theme's `--text-*` sizes. Unregistered, tailwind-merge reads `text-note`
 * as a colour and drops it whenever a `text-fg-*` follows.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: [
        'caption',
        'meta',
        'label',
        'note',
        'body',
        'item',
        'thanks',
        'code',
        'code-lg',
        'dots',
        'overlay-title',
        'title',
      ],
    },
  },
});

/** Joins class names and resolves conflicting Tailwind utilities. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

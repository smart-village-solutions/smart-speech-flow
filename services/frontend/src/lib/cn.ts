import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/**
 * The theme's `--text-*` sizes. Unregistered, tailwind-merge reads `text-note`
 * as a colour and drops it whenever a `text-fg-*` follows.
 *
 * The font-size conflict list is emptied because it is Tailwind v3's: there a
 * size set the line height too, so a later size replaced an earlier
 * `leading-*`. In v4 `leading-*` wins whatever the order.
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
  override: {
    conflictingClassGroups: { 'font-size': [] },
  },
});

/** Joins class names and resolves conflicting Tailwind utilities. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

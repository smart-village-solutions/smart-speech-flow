import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { cn } from '@/lib/cn';

// Read from disk: vitest runs with `css: false`, which empties CSS imports, `?raw` included.
const tokens = readFileSync(path.join(import.meta.dirname, '../../ui/styles/tokens.css'), 'utf8');

/** Every `--text-<name>` size in the theme, read from the stylesheet itself. */
const TEXT_SIZES = [...tokens.matchAll(/^[ \t]*--text-([\w-]+):/gm)]
  .map((match) => match[1])
  // `--text-<name>--line-height` companions are not sizes of their own.
  .filter((name) => !name.includes('--'));

describe('cn', () => {
  it('joins class names', () => {
    expect(cn('a', 'b')).toBe('a b');
  });

  it('drops falsy values', () => {
    const include = false as boolean;
    expect(cn('a', include && 'b', undefined, 'c')).toBe('a c');
  });

  it('lets a later Tailwind class win over an earlier conflicting one', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4');
  });

  it('finds the theme text sizes to check', () => {
    expect(TEXT_SIZES).toEqual(expect.arrayContaining(['meta', 'note', 'body', 'code-lg']));
  });

  it.each(TEXT_SIZES)('keeps the text-%s size when a text colour follows it', (size) => {
    expect(cn(`text-${size}`, 'text-fg-body')).toBe(`text-${size} text-fg-body`);
  });

  it('still lets a later theme text size win over an earlier one', () => {
    expect(cn('text-meta', 'text-note')).toBe('text-note');
  });

  // Tailwind v4 applies `leading-*` over a size's own line height whatever the order.
  it('keeps a line height that comes before a theme text size', () => {
    expect(cn('leading-tight', 'text-note')).toBe('leading-tight text-note');
  });

  it('still lets a later text colour win over an earlier one', () => {
    expect(cn('text-fg-body', 'text-fg-danger')).toBe('text-fg-danger');
  });
});

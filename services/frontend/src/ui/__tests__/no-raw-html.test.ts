import { describe, expect, it } from 'vitest';

/**
 * Studio markup reaches the page only through RichText, which rebuilds an
 * allowlist. Any API that writes an HTML string into the DOM would bypass it.
 */
const FORBIDDEN = [
  /dangerouslySetInnerHTML/,
  /(inner|outer)HTML['"`]?\]?\s*\+?=(?!=)/,
  /insertAdjacentHTML/,
  /document\.write/,
  /setHTML/,
  /createContextualFragment/,
  /srcdoc/i,
];
const SELF = '/src/ui/__tests__/no-raw-html.test.ts';

const sources = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function offendingLines(path: string, source: string): string[] {
  return source
    .split('\n')
    .flatMap((line, index) =>
      FORBIDDEN.some((pattern) => pattern.test(line)) ? [`${path}:${index + 1}`] : []
    );
}

describe('no raw HTML reaches the page', () => {
  // Without this the glob silently matching nothing would read as a pass.
  it('reads the sources', () => {
    expect(Object.keys(sources)).toContain('/src/ui/patterns/RichText.tsx');
    expect(Object.keys(sources).length).toBeGreaterThan(100);
  });

  it('writes no HTML string into the DOM anywhere in src', () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => path !== SELF)
      .flatMap(([path, source]) => offendingLines(path, source));

    expect(offenders).toEqual([]);
  });
});

import { describe, expect, it } from 'vitest';

/**
 * The customer UI runs right to left in Arabic and Persian, so the screens are
 * laid out with logical properties. A physical one survives `dir="rtl"`
 * unchanged and silently puts a control on the wrong side, which no jsdom
 * assertion would notice — this catches it at the source instead.
 */
const FORBIDDEN = [
  // margin and padding: use ms-, me-, ps-, pe-
  /\b[mp][lr]-[a-z0-9[\]./-]+/,
  // offsets: use start-, end-. inset-x- is symmetric and allowed.
  /\b(?<!inset-)(left|right)-[a-z0-9[\]./-]+/,
  // alignment: use text-start, text-end
  /\btext-(left|right)\b/,
  // corners: the rounded-bubble-* helpers are logical, unlike these
  /\brounded-(tl|tr|bl|br)-/,
  // borders: use border-s, border-e
  /\bborder-[lr]-/,
];

const sources = import.meta.glob('/src/{features,ui}/**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

/** Doc comments have to quote the thing they forbid, so they are not scanned. */
function isComment(line: string): boolean {
  const trimmed = line.trim();
  return trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*');
}

describe('the customer screens lay out logically', () => {
  // Without this the glob silently matching nothing would read as a pass.
  it('reads the screen sources', () => {
    expect(Object.keys(sources)).toContain('/src/ui/patterns/MessageBubble.tsx');
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it('use no physical direction utilities', () => {
    const offenders: string[] = [];

    for (const [path, source] of Object.entries(sources)) {
      if (path.includes('/__tests__/')) {
        continue;
      }

      source.split('\n').forEach((line, index) => {
        if (isComment(line)) {
          return;
        }

        for (const pattern of FORBIDDEN) {
          const hit = pattern.exec(line);
          if (hit !== null) {
            offenders.push(`${path}:${index + 1} ${hit[0]}`);
          }
        }
      });
    }

    expect(offenders).toEqual([]);
  });
});

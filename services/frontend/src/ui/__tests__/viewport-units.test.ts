import { describe, expect, it } from 'vitest';

/**
 * `vh` is the *large* viewport height — the page as it would be with the mobile
 * browser's toolbar hidden. While the toolbar is showing, a `100vh` box is
 * taller than what the customer can see, so the document scrolls and anything
 * anchored to the bottom of that box sits under the browser chrome. That is
 * what buried the microphone and keyboard buttons on the conversation screen.
 *
 * `dvh` tracks the viewport actually on screen, so the layout fits whatever the
 * device gives it. The legacy pages under `pages/` and `components/` still use
 * `vh` and are deliberately not scanned.
 */
const FORBIDDEN = [/\b(min-h-screen|h-screen)\b/, /\d+vh\b/];

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

describe('the customer screens fit the viewport they are given', () => {
  // Without this the glob silently matching nothing would read as a pass.
  it('reads the screen sources', () => {
    expect(Object.keys(sources)).toContain('/src/ui/patterns/ScreenShell.tsx');
    expect(Object.keys(sources).length).toBeGreaterThan(20);
  });

  it('size themselves in dvh, never vh', () => {
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

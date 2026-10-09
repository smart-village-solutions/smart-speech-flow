import { describe, expect, it } from 'vitest';
import { CATALOGUES } from '@/i18n';

/**
 * Every catalogue key must be read by the app; a key only a test reads is dead.
 * Keys built at runtime, such as `admin.sessions.${day}`, are matched by
 * turning each template literal into a pattern with one segment per
 * placeholder, so a dead sibling under such a prefix can slip through.
 */
const sources = import.meta.glob('/src/**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

function flatten(value: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, entry]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof entry === 'object' && entry !== null
      ? flatten(entry as Record<string, unknown>, path)
      : [path];
  });
}

/** Tests, their fixtures and handlers, and test files beside the code are not the app. */
const isTestCode = (path: string) =>
  path.includes('/__tests__/') || path.startsWith('/src/test/') || /\.test\.tsx?$/.test(path);

const appSources = Object.entries(sources)
  .filter(([path]) => !isTestCode(path))
  .map(([, source]) => source);

const literals = new Set(
  appSources.flatMap((source) =>
    Array.from(source.matchAll(/['"`]([a-zA-Z]+(?:\.\w+)+)['"`]/g), (match) => match[1])
  )
);

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

const templates = appSources.flatMap((source) =>
  Array.from(
    source.matchAll(/`([a-zA-Z]+\.[^`]*?\$\{[^`]*)`/g),
    (match) => new RegExp(`^${match[1].split(/\$\{[^}]*\}/).map(escape).join('[^.]+')}$`)
  )
);

function isRead(key: string): boolean {
  return literals.has(key) || templates.some((pattern) => pattern.test(key));
}

describe('translation keys', () => {
  // Without this the glob silently matching nothing would read as a pass.
  it('reads the app sources and their runtime-built keys', () => {
    expect(appSources.length).toBeGreaterThan(50);
    expect(Object.keys(sources).some((path) => path.startsWith('/src/test/'))).toBe(true);
    expect(isTestCode('/src/test/handlers.ts')).toBe(true);
    expect(isTestCode('/src/features/feedback/FeedbackSheet.tsx')).toBe(false);
    expect(templates.some((pattern) => pattern.test('feedback.quality.label'))).toBe(true);
    expect(isRead('header.feedback')).toBe(true);
  });

  it('are each read by the app, in every catalogue', () => {
    const unread = Object.entries(CATALOGUES).flatMap(([locale, catalogue]) =>
      flatten(catalogue as Record<string, unknown>)
        .filter((key) => !isRead(key))
        .map((key) => `${locale}: ${key}`)
    );

    expect(unread).toEqual([]);
  });
});

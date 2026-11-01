import { describe, expect, it } from 'vitest';
import { directionFor, SUPPORTED_UI_LOCALES } from '@/i18n';

describe('directionFor', () => {
  it('reports right-to-left for Arabic and Persian', () => {
    expect(directionFor('ar')).toBe('rtl');
    expect(directionFor('fa')).toBe('rtl');
  });

  // Amharic uses Ge'ez, which also runs left to right.
  it('reports left-to-right for every other supported locale', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      if (locale === 'ar' || locale === 'fa') {
        continue;
      }
      expect(directionFor(locale), locale).toBe('ltr');
    }
  });

  it('falls back to left-to-right for a locale it does not know', () => {
    expect(directionFor('xx')).toBe('ltr');
  });
});

it.each([
  ['ar-SA', 'rtl'],
  ['AR-eg', 'rtl'],
  ['fa-IR', 'rtl'],
  ['Fa-Arab-IR', 'rtl'],
  ['de-DE', 'ltr'],
  ['en-US', 'ltr'],
  ['xx-YY', 'ltr'],
])('derives %s direction from its primary language', (locale, direction) => {
  expect(directionFor(locale)).toBe(direction);
});

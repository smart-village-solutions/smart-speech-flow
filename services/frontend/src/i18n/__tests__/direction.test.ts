import { describe, expect, it } from 'vitest';
import { directionFor, SUPPORTED_UI_LOCALES } from '@/i18n';

describe('directionFor', () => {
  it('reports right-to-left for Arabic and Persian', () => {
    expect(directionFor('ar')).toBe('rtl');
    expect(directionFor('fa')).toBe('rtl');
  });

  // Kurmancî is written in the Latin alphabet, unlike Sorani Kurdish. Amharic
  // and Tigrinya use Ge'ez, which also runs left to right.
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

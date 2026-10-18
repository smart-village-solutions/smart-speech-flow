import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { SUPPORTED_UI_LOCALES } from '@/i18n';
import { flagCodeFor } from '@/ui/patterns/flags';

describe('flagCodeFor', () => {
  it.each([
    ['it', 'it'],
    ['ro', 'ro'],
    ['pl', 'pl'],
    ['bg', 'bg'],
    ['el', 'gr'],
    ['fr', 'fr'],
    ['es', 'es'],
    ['pt', 'pt'],
    ['sq', 'al'],
    ['hu', 'hu'],
    ['zh', 'cn'],
    ['hi', 'in'],
  ])('gives %s the flag %s', (language, flag) => {
    expect(flagCodeFor(language)).toBe(flag);
  });

  // A mapped flag with no image renders a broken image rather than the chip.
  it('maps only to flags that are bundled', () => {
    for (const locale of SUPPORTED_UI_LOCALES) {
      const flag = flagCodeFor(locale);
      if (flag === null) {
        continue;
      }
      expect(existsSync(resolve('public/flags', `${flag}.png`)), `${locale} → ${flag}`).toBe(true);
    }
  });
});

import type { BrandId } from '@/app/config/env';
import type { BrandSource } from './brand.port';
import type { BrandDefinition } from './brand.types';
import { NO_LEGAL_LINKS } from './noLegalLinks';

/** Kassel's links are the live Studio values of 2026-10-07. */
const BRANDS: BrandDefinition[] = [
  { id: 'ssf', legal: NO_LEGAL_LINKS },
  {
    id: 'kassel',
    legal: {
      imprintUrl: 'https://www.kassel.de/impressum.php',
      privacyPolicyUrl: 'https://www.kassel.de/datenschutzerklaerung.php',
      accessibilityStatementUrl: 'https://www.kassel.de/erklaerung-zur-barrierefreiheit.php',
    },
  },
];

export function createStaticBrandSource(defaultBrand: BrandId): BrandSource {
  return {
    list: () => BRANDS,
    getDefault: () => defaultBrand,
  };
}

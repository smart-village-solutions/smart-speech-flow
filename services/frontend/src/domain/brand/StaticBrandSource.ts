import type { BrandId } from '@/app/config/env';
import type { BrandSource } from './brand.port';
import type { BrandDefinition } from './brand.types';

const BRANDS: BrandDefinition[] = [
  { id: 'ssf', displayName: 'Smart Speech Flow' },
  { id: 'kassel', displayName: 'Kassel Dialog' },
];

export function createStaticBrandSource(defaultBrand: BrandId): BrandSource {
  return {
    list: () => BRANDS,
    getDefault: () => defaultBrand,
  };
}

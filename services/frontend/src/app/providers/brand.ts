import { createContext, useContext } from 'react';
import type { BrandId } from '@/app/config/env';
import type { LegalLinks } from '@/domain/content/content.types';

export interface BrandContextValue {
  brand: BrandId;
  displayName: string;
  /** The active brand's bundled legal links, the fallback for Studio's. */
  legal: LegalLinks;
  toggleBrand: () => void;
}

export const BrandContext = createContext<BrandContextValue | null>(null);

export function useBrand(): BrandContextValue {
  const value = useContext(BrandContext);

  if (value === null) {
    throw new Error('useBrand must be used inside a BrandProvider');
  }

  return value;
}

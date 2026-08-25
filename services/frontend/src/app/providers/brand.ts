import { createContext, useContext } from 'react';
import type { BrandId } from '@/app/config/env';

export interface BrandContextValue {
  brand: BrandId;
  displayName: string;
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

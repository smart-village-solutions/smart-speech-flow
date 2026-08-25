import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { BrandId } from '@/app/config/env';
import type { BrandSource } from '@/domain/brand/brand.port';
import { BrandContext } from './brand';

interface BrandProviderProps {
  children: ReactNode;
  source: BrandSource;
}

export function BrandProvider({ children, source }: BrandProviderProps) {
  const brands = useMemo(() => source.list(), [source]);
  const [brand, setBrand] = useState<BrandId>(() => source.getDefault());

  useEffect(() => {
    document.documentElement.setAttribute('data-brand', brand);
  }, [brand]);

  const toggleBrand = useCallback(() => {
    setBrand((current) => {
      const index = brands.findIndex((candidate) => candidate.id === current);
      return brands[(index + 1) % brands.length].id;
    });
  }, [brands]);

  const value = useMemo(() => {
    const active = brands.find((candidate) => candidate.id === brand);
    return { brand, displayName: active?.displayName ?? brand, toggleBrand };
  }, [brand, brands, toggleBrand]);

  return <BrandContext.Provider value={value}>{children}</BrandContext.Provider>;
}

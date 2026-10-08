import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { BrandId } from '@/app/config/env';
import type { BrandSource } from '@/domain/brand/brand.port';
import { NO_LEGAL_LINKS } from '@/domain/brand/noLegalLinks';
import { BrandContext } from './brand';

interface BrandProviderProps {
  children: ReactNode;
  source: BrandSource;
}

export function BrandProvider({ children, source }: Readonly<BrandProviderProps>) {
  const { t } = useTranslation();
  const brands = useMemo(() => source.list(), [source]);
  const [brand, setBrand] = useState<BrandId>(() => source.getDefault());

  useEffect(() => {
    document.documentElement.dataset.brand = brand;
  }, [brand]);

  const toggleBrand = useCallback(() => {
    setBrand((current) => {
      const index = brands.findIndex((candidate) => candidate.id === current);
      return brands[(index + 1) % brands.length].id;
    });
  }, [brands]);

  const value = useMemo(() => {
    const legal = brands.find((candidate) => candidate.id === brand)?.legal ?? NO_LEGAL_LINKS;
    return { brand, displayName: t('app.name'), legal, toggleBrand };
  }, [brand, brands, t, toggleBrand]);

  return <BrandContext.Provider value={value}>{children}</BrandContext.Provider>;
}

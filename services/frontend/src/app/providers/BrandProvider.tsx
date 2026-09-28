import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { BrandId } from '@/app/config/env';
import type { BrandSource } from '@/domain/brand/brand.port';
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
    return { brand, displayName: t('app.name'), toggleBrand };
  }, [brand, t, toggleBrand]);

  return <BrandContext.Provider value={value}>{children}</BrandContext.Provider>;
}

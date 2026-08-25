import type { ReactNode } from 'react';
import { ServicesContext, type Services } from './services';

interface ServicesProviderProps {
  children: ReactNode;
  services: Services;
}

export function ServicesProvider({ children, services }: ServicesProviderProps) {
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

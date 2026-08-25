import type { ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { ToastProvider } from '@/contexts/ToastContext';
import { readConfig } from '@/app/config/env';
import { AppProvidersInner } from './AppProvidersInner';

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AppProvidersInner config={readConfig()}>{children}</AppProvidersInner>
      </ToastProvider>
    </BrowserRouter>
  );
}

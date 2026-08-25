import { useState } from 'react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppError } from '@/core/http/AppError';

/** Retrying a 404 or a validation failure only delays the error. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof AppError && (error.kind === 'notFound' || error.kind === 'validation')) {
    return false;
  }

  return failureCount < 2;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: shouldRetry, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      })
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

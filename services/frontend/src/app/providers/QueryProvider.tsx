import { useState } from 'react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppError } from '@/core/http/AppError';

/**
 * Retrying what the server has refused outright -- a 404, a 409, a validation
 * failure -- only delays the error. `AppError.retryable` says which those are.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof AppError && !error.retryable) {
    return false;
  }

  return failureCount < 2;
}

export function QueryProvider({ children }: Readonly<{ children: ReactNode }>) {
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

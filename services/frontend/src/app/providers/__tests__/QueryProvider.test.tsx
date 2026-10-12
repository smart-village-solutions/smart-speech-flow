import { render, screen } from '@testing-library/react';
import { useQuery } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { QueryProvider } from '@/app/providers/QueryProvider';
import { AppError, type AppErrorKind } from '@/core/http/AppError';

function Probe({ kind, status, calls }: Readonly<{ kind: AppErrorKind; status: number; calls: number[] }>) {
  const query = useQuery({
    queryKey: ['probe', kind],
    queryFn: () => {
      calls.push(1);
      return Promise.reject(new AppError(kind, { status }));
    },
  });
  return <p>{query.isError ? 'failed' : 'loading'}</p>;
}

describe('QueryProvider', () => {
  it.each([
    ['sessionHasGuest', 409],
    ['languageChanged', 400],
    ['notFound', 404],
  ] as const)('does not retry a %s refusal, which would fail the same way', async (kind, status) => {
    const calls: number[] = [];

    render(
      <QueryProvider>
        <Probe kind={kind} status={status} calls={calls} />
      </QueryProvider>
    );

    expect(await screen.findByText('failed')).toBeInTheDocument();
    expect(calls).toHaveLength(1);
  });
});

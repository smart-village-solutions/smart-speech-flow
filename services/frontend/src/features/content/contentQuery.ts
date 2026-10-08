import type { UseQueryResult } from '@tanstack/react-query';

/** Studio content; `undefined` while loading and after any failure, which means bundled copy. */
export interface ContentState<T> {
  content: T | undefined;
  /** False only while a request is outstanding; a query not yet enabled is settled. */
  settled: boolean;
}

export const contentKeys = {
  public: ['content', 'public'] as const,
  guest: (sessionId: string, language: string) =>
    ['content', 'guest', sessionId, language] as const,
  guestLanguages: (sessionId: string) => ['content', 'languages', sessionId] as const,
  staff: ['content', 'staff'] as const,
};

/**
 * Bundled copy is a complete answer, so a failure is not retried. The routes
 * allow 60 s of browser caching, and content counts as fresh for as long.
 */
export const CONTENT_QUERY = { retry: false, staleTime: 60_000 } as const;

export function toContentState<T>(query: UseQueryResult<T>): ContentState<T> {
  return { content: query.data, settled: query.fetchStatus === 'idle' || !query.isPending };
}

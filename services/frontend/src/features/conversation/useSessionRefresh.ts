import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

/** Re-reads the session, whose customer language decides both send directions. */
export function useSessionRefresh(sessionId: string): () => void {
  const queryClient = useQueryClient();
  return useCallback(
    () => void queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
    [queryClient, sessionId]
  );
}

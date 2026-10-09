import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { guestContentQuery } from './useGuestContent';

/** Starts loading a language's guest content as the guest picks it, so the consent screen rarely waits. */
export function usePrefetchGuestContent(sessionId: string | undefined): (language: string) => void {
  const queryClient = useQueryClient();
  const { content } = useServices();
  return useCallback(
    (language: string) => {
      if (sessionId === undefined) return;
      void queryClient.prefetchQuery(guestContentQuery(content, sessionId, language));
    },
    [queryClient, content, sessionId]
  );
}

import { useQuery } from '@tanstack/react-query';
import { useScreenLocale } from '@/app/providers/locale';
import { useServices } from '@/app/providers/services';

/**
 * Which two languages this conversation runs in, and the one the screen is
 * shown in. The url carries no language code — the session is what says which
 * one the customer reads — so nothing is declared until the query answers.
 *
 * The fallbacks matter only for the first render: the gateway rejects a message
 * whose source language is not the session's, so a send in that window fails.
 * `ConsentScreen` publishes the activated session to close it.
 */
export function useSessionLanguages(sessionId: string): { source: string; target: string } {
  const { session } = useServices();

  const query = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => session.getSession(sessionId),
  });

  useScreenLocale(query.data?.customerLanguage ?? '');

  return {
    source: query.data?.customerLanguage ?? 'en',
    target: query.data?.adminLanguage ?? 'de',
  };
}

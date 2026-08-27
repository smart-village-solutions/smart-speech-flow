import { useQuery } from '@tanstack/react-query';
import { useScreenLocale } from '@/app/providers/locale';
import { useServices } from '@/app/providers/services';
import type { ClientRole } from '@/core/roles';

interface SessionLanguages {
  source: string;
  target: string;
  /** Null until the customer has chosen one. The admin overlay shows it. */
  customerLanguage: string | null;
}

/**
 * Which two languages this conversation runs in, and the one the screen is
 * shown in. The url carries no language code — the session is what says which
 * one the customer reads — so nothing is declared until the query answers.
 *
 * The direction is the role's: the gateway requires the customer to send
 * `customer_language → admin_language` and the admin the reverse, and rejects
 * anything else with a 400.
 *
 * Only the customer screen adopts the customer's language. The admin screen
 * stays German: its copy is staff-facing and exists in two catalogues only.
 *
 * The fallbacks matter only for the first render: the gateway rejects a message
 * whose source language is not the session's, so a send in that window fails.
 * `ConsentScreen` publishes the activated session to close it.
 */
export function useSessionLanguages(sessionId: string, role: ClientRole): SessionLanguages {
  const { session } = useServices();

  const query = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => session.getSession(sessionId),
  });

  const customerLanguage = query.data?.customerLanguage ?? null;
  const adminLanguage = query.data?.adminLanguage ?? 'de';

  useScreenLocale(role === 'admin' ? 'de' : (customerLanguage ?? ''));

  if (role === 'admin') {
    return { source: adminLanguage, target: customerLanguage ?? 'en', customerLanguage };
  }

  return { source: customerLanguage ?? 'en', target: adminLanguage, customerLanguage };
}

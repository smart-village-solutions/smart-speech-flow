import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';

/** The staff view of an employee's own key recovery; a step-up redirect may return to it. */
export const KEY_RECOVERY_VIEW = 'keyRecovery';

/** The caller's next batch of conversations their key cannot open (spec §9.6). */
export function useOwnCandidates(enabled: boolean) {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: ['recovery', 'own'],
    queryFn: () => recoveryRequests.ownCandidates(),
    enabled,
  });
}

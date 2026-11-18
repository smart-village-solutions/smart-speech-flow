import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';

/** The caller's next batch of conversations their key cannot open (spec §9.6). */
export function useOwnCandidates(enabled: boolean) {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: ['recovery', 'own'],
    queryFn: () => recoveryRequests.ownCandidates(),
    enabled,
  });
}

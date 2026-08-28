import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { SystemLoad } from '@/domain/health/health.types';

/** Live enough for a dashboard, quiet enough not to hammer the gateway. */
const REFETCH_INTERVAL_MS = 15_000;

export function useSystemLoad() {
  const { health } = useServices();

  return useQuery<SystemLoad>({
    queryKey: ['systemLoad'],
    queryFn: () => health.getSystemLoad(),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

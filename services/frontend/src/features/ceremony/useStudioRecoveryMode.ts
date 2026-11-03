import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { RecoveryKey } from '@/domain/recovery/recovery.types';

// Outside the ceremony's key: its polling and invalidations must not read Studio each time.
const STUDIO_MODE_QUERY = ['recording', 'studio-recovery-mode'] as const;

/**
 * The recovery mode the tenant's Studio policy sets (#680), read once per screen.
 * Null without a policy, and when Studio cannot be read: the administrator chooses.
 */
export function useStudioRecoveryMode(enabled = true) {
  const { recoveryCeremony } = useServices();
  const query = useQuery({
    queryKey: STUDIO_MODE_QUERY,
    queryFn: () => recoveryCeremony.studioMode(),
    enabled,
    retry: false,
    staleTime: 60_000,
  });
  return { mode: query.data ?? null, pending: enabled && query.isPending };
}

export function thresholdOf(mode: RecoveryKey['mode']): number {
  return mode === 'standard' ? 1 : 2;
}

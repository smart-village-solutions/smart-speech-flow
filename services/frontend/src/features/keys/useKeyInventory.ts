import { useLayoutEffect, useSyncExternalStore } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';

export const INVENTORY_QUERY = ['recording', 'versions'] as const;

export function useKeyInventory(owner: KeyOwner | null, enabled = true) {
  const { recordingKeys, keyVault } = useServices();
  const tenantId = owner?.tenantId,
    userSub = owner?.userSub;
  const result = useQuery({
    queryKey: [...INVENTORY_QUERY, tenantId, userSub],
    queryFn: () => recordingKeys.versions(),
    enabled: enabled && !!owner,
    staleTime: 0,
    refetchInterval: 60_000,
  });
  useLayoutEffect(() => {
    const current = getAdminIdentity();
    if (
      enabled &&
      result.data &&
      current &&
      current.tenantId === tenantId &&
      current.userSub === userSub
    ) {
      keyVault.reconcile(current, result.data.versions);
    }
  }, [enabled, keyVault, result.data, tenantId, userSub]);
  return result;
}

export function useVaultRevision() {
  const { keyVault } = useServices();
  return useSyncExternalStore(keyVault.subscribe, keyVault.revision, keyVault.revision);
}

import type { KeyOwner, KeyVault } from '@/core/crypto/archive-crypto.port';
import {
  getAdminIdentity,
  subscribeToKeycloakAuthorization,
  subscribeToKeycloakExpiration,
} from './keycloak';

function sameOwner(left: KeyOwner | null, right: KeyOwner | null): boolean {
  return left?.tenantId === right?.tenantId && left?.userSub === right?.userSub;
}

/** One subscription for the application's tab, independent of screen navigation. */
export function followKeycloakIdentity(vault: KeyVault): () => void {
  let owner = getAdminIdentity();
  const stopAuthorization = subscribeToKeycloakAuthorization(() => {
    const next = getAdminIdentity();
    if (!sameOwner(owner, next)) vault.lock();
    owner = next;
  });
  const stopExpiration = subscribeToKeycloakExpiration(() => vault.lock());
  return () => {
    stopAuthorization();
    stopExpiration();
    vault.lock();
  };
}

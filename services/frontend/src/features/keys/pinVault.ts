import { getAdminIdentity } from '@/app/auth/keycloak';
import type { KeyOwner, KeyVault } from '@/core/crypto/archive-crypto.port';

/** Pin identity and lock generation across asynchronous archive/review operations. */
export function pinVault(vault: KeyVault, owner: KeyOwner) {
  const generation = vault.generation();
  const assertCurrent = () => {
    const current = getAdminIdentity();
    if (
      current?.tenantId !== owner.tenantId ||
      current.userSub !== owner.userSub ||
      generation !== vault.generation()
    ) {
      throw new Error('Personal access changed');
    }
  };
  return {
    assertCurrent,
    keyForVersion: (v: number) => {
      assertCurrent();
      return vault.version(owner, v);
    },
  };
}

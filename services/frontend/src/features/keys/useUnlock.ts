import { useState } from 'react';
import { useServices } from '@/app/providers/services';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import type { OwnKey } from '@/domain/recording/recording.types';

export function useUnlock(owner: Readonly<KeyOwner>, ownKey: Readonly<OwnKey>) {
  const { archiveCrypto, keyVault } = useServices();
  const [failed, setFailed] = useState(false);
  const [pending, setPending] = useState(false);

  const submit = async (passphrase: string): Promise<boolean> => {
    const generation = keyVault.generation();
    setFailed(false);
    setPending(true);
    try {
      const unlocked = await archiveCrypto.unlock(ownKey.blob, passphrase, owner, ownKey);
      return keyVault.holdIfCurrent(unlocked, generation);
    } catch {
      // A wrong passphrase and a blob that does not match its keys look the same here.
      setFailed(true);
      return false;
    } finally {
      setPending(false);
    }
  };

  return { submit, failed, pending };
}

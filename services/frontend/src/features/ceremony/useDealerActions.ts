import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { equalBytes } from '@/core/crypto/bytes';
import {
  CeremonyCheckError,
  type CeremonyFacts,
  ShareMismatchError,
} from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony, CeremonyDealer } from '@/domain/recovery/recovery.types';
import { useCeremonyStep } from './useCeremony';

/**
 * A custodian dealer opens its share with the key the previous generation lists: the
 * unlocked one, or the earlier key re-enrolment kept, unlocked here in memory only (§9.6, §9.7).
 */
export function useDealerActions(
  ceremony: Readonly<Ceremony>,
  facts: Readonly<CeremonyFacts>,
  dealer: Readonly<CeremonyDealer>,
  owner: Readonly<KeyOwner>,
  vault: Readonly<UnlockedKeys> | null
) {
  const { recoveryCeremony, ceremonyCrypto, archiveCrypto } = useServices();
  const step = useCeremonyStep(ceremony.ceremonyId);
  const [earlier, setEarlier] = useState<UnlockedKeys | null>(null);
  const [unlockFailed, setUnlockFailed] = useState(false);
  const material = useQuery({
    // Outside the ceremony's query key: each step refetches that, and each read is audited.
    queryKey: ['recording', 'resharing-dealer', ceremony.ceremonyId],
    queryFn: () => recoveryCeremony.dealer(ceremony.ceremonyId),
    staleTime: Infinity,
  });
  const served = material.data ?? null;
  const vaultFits =
    served !== null && vault !== null && equalBytes(vault.fingerprint, served.fingerprint);
  const keys = vaultFits ? vault : earlier;

  const unlockEarlier = async (passphrase: string) => {
    if (served === null) return;
    setUnlockFailed(false);
    try {
      setEarlier(await archiveCrypto.unlock(served.blob, passphrase, owner, served));
    } catch {
      setUnlockFailed(true);
    }
  };

  const deal = () =>
    step.run(async () => {
      const listed = facts.resharing?.previous?.participants.find(
        (p) => p.holderIndex === dealer.dealerIndex
      );
      if (served === null || keys === null || listed === undefined)
        throw new CeremonyCheckError('chain_invalid');
      const receiver = { privateKey: keys.encPrivate, publicKey: keys.encPub };
      try {
        const share = await ceremonyCrypto.openShare(
          facts,
          listed,
          served.encryptedShare,
          receiver
        );
        const dealing = await ceremonyCrypto.dealShare(
          facts,
          dealer.dealerIndex,
          share,
          keys.sigPrivate
        );
        await recoveryCeremony.deal(ceremony.ceremonyId, dealing);
      } catch (caught) {
        // The share the gateway serves is not the one the certified transcript lists.
        if (caught instanceof ShareMismatchError) throw new CeremonyCheckError('chain_invalid');
        throw caught;
      }
    });

  return {
    deal,
    unlockEarlier,
    unlockFailed,
    needsEarlierKey: served !== null && !vaultFits && earlier === null,
    ready: keys !== null,
    served,
    error: step.error,
    pending: step.pending,
  };
}

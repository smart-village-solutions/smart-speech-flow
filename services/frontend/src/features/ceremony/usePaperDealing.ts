import { useState } from 'react';
import { useServices } from '@/app/providers/services';
import { type CeremonyFacts, ShareMismatchError } from '@/core/crypto/ceremony-crypto.port';
import { ORDER } from '@/core/crypto/curve';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import { useCeremonyStep } from './useCeremony';

/** 64 hex characters, spaces allowed as printed; anything else is no share. */
function parseSheet(typed: string): bigint | null {
  const hex = typed.replaceAll(/\s/g, '');
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) return null;
  const value = BigInt(`0x${hex}`);
  return value > 0n && value < ORDER ? value : null;
}

/**
 * The ceremony device deals for each paper sheet that is a dealer. A sheet that does
 * not match its public share is most likely a typo: it is asked for again, nothing is
 * sent, and nothing aborts (spec §9.7).
 */
export function usePaperDealing(ceremony: Readonly<Ceremony>, facts: Readonly<CeremonyFacts>) {
  const { recoveryCeremony, ceremonyCrypto } = useServices();
  const step = useCeremonyStep(ceremony.ceremonyId);
  const [mismatch, setMismatch] = useState(false);

  const dealSheet = (dealerIndex: number, typed: string, onDealt: () => void) =>
    step.run(async () => {
      setMismatch(false);
      const share = parseSheet(typed);
      if (share === null) {
        setMismatch(true);
        return;
      }
      try {
        const dealing = await ceremonyCrypto.dealShare(facts, dealerIndex, share, null);
        await recoveryCeremony.paperDeal(ceremony.ceremonyId, dealerIndex, dealing);
        onDealt();
      } catch (caught) {
        if (!(caught instanceof ShareMismatchError)) throw caught;
        setMismatch(true);
      }
    });

  return { dealSheet, mismatch, error: step.error, pending: step.pending };
}

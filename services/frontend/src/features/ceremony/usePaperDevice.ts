import { useState } from 'react';
import { useServices } from '@/app/providers/services';
import { heldShare, type CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import { useCeremonyStep } from './useCeremony';

export interface PaperSheet {
  holderRef: string;
  holderIndex: number;
  share: bigint;
}

/**
 * The ceremony device verifies every dealing like a custodian, opens the paper
 * sub-shares, and prints them. Shares stay in this component's memory until
 * the confirmation, then the device key is dropped (spec §9.2, paper backup).
 */
export function usePaperDevice(ceremony: Readonly<Ceremony>, facts: Readonly<CeremonyFacts>) {
  const { recoveryCeremony, ceremonyCrypto, paperDevice } = useServices();
  const step = useCeremonyStep(ceremony.ceremonyId);
  const [sheets, setSheets] = useState<PaperSheet[] | null>(null);

  const verify = () =>
    step.run(async () => {
      const device = paperDevice.current();
      if (device === null) return;
      const subshares = await recoveryCeremony.subshares(ceremony.ceremonyId);
      const received = await ceremonyCrypto.receive(facts, device, subshares, ceremony.transcriptHash ?? new Uint8Array(0));
      setSheets(
        ceremony.participants
          .filter((participant) => participant.kind === 'paper')
          .map((participant) => ({
            holderRef: participant.holderRef,
            holderIndex: participant.holderIndex,
            share: heldShare(received, participant.holderIndex),
          }))
      );
    });

  const confirm = () =>
    step.run(async () => {
      await recoveryCeremony.confirmPaper(ceremony.ceremonyId, ceremony.transcriptHash ?? new Uint8Array(0));
      setSheets(null);
      paperDevice.clear();
    });

  return { device: paperDevice.current(), sheets, verify, confirm, error: step.error, pending: step.pending };
}

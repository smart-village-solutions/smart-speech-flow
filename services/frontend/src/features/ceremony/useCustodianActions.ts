import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { equalBytes } from '@/core/crypto/bytes';
import { CeremonyCheckError, heldShare, type CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony, CeremonyParticipant } from '@/domain/recovery/recovery.types';
import { useCeremonyStep } from './useCeremony';

/** The gateway must list this custodian with the keys this browser has unlocked. */
function requireOwnKeys(participant: Readonly<CeremonyParticipant>, keys: Readonly<UnlockedKeys>): void {
  const sigPub = participant.sigPub ?? new Uint8Array(0);
  if (!equalBytes(participant.encPub, keys.encPub) || !equalBytes(sigPub, keys.sigPub)) {
    throw new CeremonyCheckError('fingerprint_mismatch');
  }
}

export function useCustodianActions(
  ceremony: Readonly<Ceremony>,
  facts: Readonly<CeremonyFacts>,
  participant: Readonly<CeremonyParticipant>,
  keys: Readonly<UnlockedKeys>
) {
  const { recoveryCeremony, ceremonyCrypto } = useServices();
  const step = useCeremonyStep(ceremony.ceremonyId);

  const deal = () =>
    step.run(async () => {
      requireOwnKeys(participant, keys);
      const dealing = await ceremonyCrypto.deal(facts, participant.holderIndex, keys.sigPrivate);
      await recoveryCeremony.deal(ceremony.ceremonyId, dealing);
    });

  const confirm = () =>
    step.run(async () => {
      requireOwnKeys(participant, keys);
      const expected = ceremony.transcriptHash ?? new Uint8Array(0);
      const subshares = await recoveryCeremony.subshares(ceremony.ceremonyId);
      const receiver = { privateKey: keys.encPrivate, publicKey: keys.encPub };
      const received = await ceremonyCrypto.receive(facts, receiver, subshares, expected);
      const share = heldShare(received, participant.holderIndex);
      const confirmation = await ceremonyCrypto.confirm(facts, participant, share, received.transcriptHash, keys.sigPrivate);
      await recoveryCeremony.confirm(ceremony.ceremonyId, confirmation);
    });

  return { deal, confirm, error: step.error, pending: step.pending };
}

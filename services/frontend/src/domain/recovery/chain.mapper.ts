import type { TrustChain } from '@/core/crypto/ceremony-crypto.port';
import type { ServedChain } from './recovery.types';

/** The chain as the crypto port certifies it, for this tenant (spec §9.7). */
export function trustChain(tenantId: string, served: Readonly<ServedChain>): TrustChain {
  return {
    recoveryKeyId: served.recoveryKeyId,
    firstTranscriptHash: served.firstTranscriptHash,
    holdersCeremonyId: served.holdersCeremonyId,
    holdersTranscriptHash: served.holdersTranscriptHash,
    generations: served.generations.map((g) => ({
      transcriptHash: g.transcriptHash,
      signatures: g.signatures,
      facts: {
        tenantId,
        ceremonyId: g.ceremonyId,
        k: g.k,
        participants: g.participants,
        dealings: g.dealings,
        gatewayKeys: g.gatewayKeys,
        resharing:
          g.kind === 'resharing' && g.previousTranscript !== null
            ? {
                recoveryKeyId: served.recoveryKeyId,
                previousTranscript: g.previousTranscript,
                dealers: g.dealers,
                previous: null,
              }
            : undefined,
      },
    })),
  };
}

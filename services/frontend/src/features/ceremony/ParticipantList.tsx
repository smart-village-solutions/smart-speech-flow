import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { toHex } from '@/core/crypto/bytes';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { Ceremony, CeremonyParticipant } from '@/domain/recovery/recovery.types';

interface ParticipantListProps {
  ceremony: Ceremony;
  facts: CeremonyFacts;
}

function statusKey(ceremony: Readonly<Ceremony>, participant: Readonly<CeremonyParticipant>): string {
  if (participant.kind === 'paper') {
    return ceremony.paperConfirmed ? 'admin.ceremony.statusPrinted' : 'admin.ceremony.statusWaiting';
  }
  if (ceremony.confirmed.includes(participant.holderIndex)) return 'admin.ceremony.statusSigned';
  // A resharing's dealers keep their old indices: a new holder's index says nothing about dealing.
  if (ceremony.kind === 'resharing') return 'admin.ceremony.statusWaiting';
  const dealt = ceremony.dealings.some((dealing) => dealing.dealerIndex === participant.holderIndex);
  return dealt ? 'admin.ceremony.statusDealt' : 'admin.ceremony.statusWaiting';
}

/**
 * Fingerprints are recomputed here from the listed keys, never taken from the
 * gateway's word, so that comparing them in person means something (spec §3).
 */
export function ParticipantList({ ceremony, facts }: Readonly<ParticipantListProps>) {
  const { t } = useTranslation();
  const { ceremonyCrypto } = useServices();
  const fingerprints = useQuery({
    // Keyed by the listed keys themselves, so a swapped key is recomputed, never shown from cache.
    queryKey: [
      'recording',
      'ceremony',
      ceremony.ceremonyId,
      'fingerprints',
      ceremony.participants.map((p) => `${p.holderIndex}:${toHex(p.encPub)}:${toHex(p.sigPub ?? new Uint8Array(0))}`),
    ],
    queryFn: () => ceremonyCrypto.fingerprints(facts),
  });

  if (fingerprints.isError) {
    return (
      <p role="alert" className="text-note text-fg-status-alert print:hidden">
        {t('admin.ceremony.fingerprintMismatch')}
      </p>
    );
  }

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5 print:hidden">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.ceremony.participantsTitle')}</h2>
      <ul className="flex flex-col gap-3">
        {ceremony.participants.map((participant) => {
          const fingerprint = fingerprints.data?.get(participant.holderIndex);
          return (
            <li key={participant.holderIndex} className="flex flex-col gap-1">
              <span className="text-note font-semibold text-fg-strong">
                {participant.displayName ?? t('admin.ceremony.paperHolder', { ref: participant.holderRef })} ·{' '}
                {t(statusKey(ceremony, participant))}
              </span>
              <code className="text-meta text-fg-muted">{fingerprint ? displayFingerprint(fingerprint) : '…'}</code>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

import { useTranslation } from 'react-i18next';
import type { Bytes } from '@/core/crypto/bytes';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { CeremonyParticipant } from '@/domain/recovery/recovery.types';
import { Checkbox } from '@/ui/primitives/Checkbox';

interface NewHolderTicksProps {
  participants: readonly CeremonyParticipant[];
  /** Holder index -> the fingerprint shown when it was ticked. */
  ticked: ReadonlyMap<number, Bytes>;
  onChange: (ticked: Map<number, Bytes>) => void;
}

/** A dealer seals to these keys: each fingerprint is compared before anything is dealt (spec §9.7). */
export function NewHolderTicks({ participants, ticked, onChange }: Readonly<NewHolderTicksProps>) {
  const { t } = useTranslation();
  // The tick binds the value compared, so a key swapped after it no longer counts as ticked.
  const toggle = (participant: Readonly<CeremonyParticipant>, on: boolean) => {
    const next = new Map(ticked);
    if (on) next.set(participant.holderIndex, participant.fingerprint);
    else next.delete(participant.holderIndex);
    onChange(next);
  };

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2 text-note text-fg-muted">
        {t('admin.ceremony.reshare.newHolders')}
      </legend>
      {participants.map((p) => (
        <Checkbox
          key={p.holderIndex}
          checked={ticked.has(p.holderIndex)}
          onCheckedChange={(on) => toggle(p, on)}
        >
          {p.kind === 'paper'
            ? t('admin.ceremony.paperHolder', { ref: p.holderRef })
            : (p.displayName ?? p.holderRef)}{' '}
          <code>{displayFingerprint(p.fingerprint)}</code> · {t('admin.ceremony.reshare.compared')}
        </Checkbox>
      ))}
    </fieldset>
  );
}

import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { Bytes } from '@/core/crypto/bytes';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';
import { NewHolderTicks } from './NewHolderTicks';
import { StepAlert } from './StepAlert';
import { CEREMONY_VIEW, allTicked } from './useCeremony';
import { usePaperDealing } from './usePaperDealing';

interface PaperDealerPanelProps {
  ceremony: Ceremony;
  facts: CeremonyFacts;
}

/** On the starter's device: each old paper sheet is typed in and hands over its share (spec §9.7). */
export function PaperDealerPanel({ ceremony, facts }: Readonly<PaperDealerPanelProps>) {
  const { t } = useTranslation();
  const paper = usePaperDealing(ceremony, facts);
  const [ticked, setTicked] = useState<Map<number, Bytes>>(new Map());
  const [typed, setTyped] = useState('');
  const waiting = ceremony.dealers.filter(
    (d) =>
      d.kind === 'paper' &&
      !ceremony.dealings.some((dealing) => dealing.dealerIndex === d.dealerIndex)
  );
  const [chosen, setChosen] = useState<number | null>(null);
  const sheet = waiting.find((d) => d.dealerIndex === chosen) ?? waiting[0];

  if (paper.error === 'stepUp') return <StepUpPrompt returnTo={CEREMONY_VIEW} />;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (sheet === undefined) return;
    // The typed share is cleared once dealt, and kept to correct when it did not match.
    void paper.dealSheet(sheet.dealerIndex, typed, () => setTyped(''));
  };

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5 print:hidden">
      <h2 className="text-body font-semibold text-fg-strong">
        {t('admin.ceremony.reshare.paperTitle')}
      </h2>
      {sheet === undefined ? (
        <p className="text-note text-fg-muted">{t('admin.ceremony.reshare.sheetsDone')}</p>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <NewHolderTicks
            participants={ceremony.participants}
            ticked={ticked}
            onChange={setTicked}
          />
          <select
            value={sheet.dealerIndex}
            onChange={(event) => setChosen(Number(event.target.value))}
            className="rounded-lg border border-border-card bg-surface-card p-2 text-body text-fg-strong"
          >
            {waiting.map((d) => (
              <option key={d.dealerIndex} value={d.dealerIndex}>
                {t('admin.ceremony.reshare.sheet', { ref: d.holderRef })}
              </option>
            ))}
          </select>
          <TextField
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            label={t('admin.ceremony.reshare.sheetValue')}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            error={paper.mismatch ? t('admin.ceremony.reshare.sheetMismatch') : null}
          />
          <Button
            type="submit"
            variant="compact"
            className="self-start bg-accent text-accent-on"
            disabled={
              !allTicked(ceremony.participants, ticked) || paper.pending || typed.trim() === ''
            }
          >
            {t(paper.pending ? 'admin.ceremony.working' : 'admin.ceremony.reshare.dealSheet')}
          </Button>
        </form>
      )}
      {paper.error !== null && <StepAlert error={paper.error} />}
    </section>
  );
}

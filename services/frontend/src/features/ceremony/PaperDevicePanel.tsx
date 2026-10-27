import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CeremonyFacts } from '@/core/crypto/ceremony-crypto.port';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { Ceremony } from '@/domain/recovery/recovery.types';
import { Button } from '@/ui/primitives/Button';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { PaperSheets } from './PaperSheets';
import { StepAlert } from './StepAlert';
import { usePaperDevice } from './usePaperDevice';

interface PaperDevicePanelProps {
  ceremony: Ceremony;
  facts: CeremonyFacts;
}

/** Shown on the device that started the ceremony with paper shares. */
export function PaperDevicePanel({ ceremony, facts }: Readonly<PaperDevicePanelProps>) {
  const { t } = useTranslation();
  const paper = usePaperDevice(ceremony, facts);
  const [sealed, setSealed] = useState(false);

  if (paper.device === null && ceremony.paperConfirmed) {
    return <p className="text-note text-fg-muted">{t('admin.ceremony.paperDone')}</p>;
  }
  if (paper.device === null) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.ceremony.deviceLost')}
      </p>
    );
  }

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5 print:border-0">
      <h2 className="text-body font-semibold text-fg-strong print:hidden">{t('admin.ceremony.paperTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted print:hidden">
        {t('admin.ceremony.deviceFingerprint')} <code>{displayFingerprint(paper.device.fingerprint)}</code>
      </p>
      {ceremony.status === 'dealing' && (
        <p className="text-note text-fg-muted print:hidden">{t('admin.ceremony.paperWaiting')}</p>
      )}
      {ceremony.status === 'confirming' && paper.sheets === null && (
        <Button variant="compact" className="self-start bg-accent text-accent-on print:hidden" disabled={paper.pending} onClick={() => void paper.verify()}>
          {t('admin.ceremony.verifyPaperAction')}
        </Button>
      )}
      {paper.sheets !== null && (
        <>
          <PaperSheets ceremony={ceremony} tenantId={facts.tenantId} sheets={paper.sheets} />
          <Button variant="compact" className="self-start bg-accent text-accent-on print:hidden" onClick={() => globalThis.print()}>
            {t('admin.ceremony.printAction')}
          </Button>
          <div className="print:hidden">
            <Checkbox checked={sealed} onCheckedChange={setSealed}>
              {t('admin.ceremony.sealedAttest')}
            </Checkbox>
          </div>
          <Button variant="compact" className="self-start bg-accent text-accent-on print:hidden" disabled={!sealed || paper.pending} onClick={() => void paper.confirm()}>
            {t('admin.ceremony.paperConfirmAction')}
          </Button>
        </>
      )}
      {paper.error !== null && paper.error !== 'stepUp' && <StepAlert error={paper.error} />}
    </section>
  );
}

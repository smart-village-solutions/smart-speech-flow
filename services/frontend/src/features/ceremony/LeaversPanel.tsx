import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { LeaverRow } from './LeaverRow';
import { CEREMONY_VIEW } from './useCeremony';
import { useLeavers } from './useLeavers';

/**
 * Users with a key whom Studio no longer gives a recording permission (spec §9.8).
 * Step-up is asked for first and latched, so its redirect never loses a chosen candidate.
 */
export function LeaversPanel() {
  const { t } = useTranslation();
  const [fresh] = useState(() => hasFreshStepUp());
  const [confirming, setConfirming] = useState<string | null>(null);
  const leavers = useLeavers();
  const candidates = leavers.candidates ?? [];
  const needsStepUp = (!fresh && candidates.length > 0) || leavers.stepUp;

  return (
    <>
      {needsStepUp && <StepUpPrompt returnTo={CEREMONY_VIEW} />}
      <section className="flex flex-col gap-3 rounded-2xl border border-border-card bg-surface-card p-5 print:hidden">
        <h2 className="text-body font-semibold text-fg-strong">
          {t('admin.ceremony.leavers.title')}
        </h2>
        <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.leavers.intro')}</p>
        {leavers.listError !== null && (
          <p role="alert" className="text-note text-fg-status-alert">
            {t(leavers.listError)}
          </p>
        )}
        {leavers.candidates !== null && candidates.length === 0 && (
          <p className="text-note text-fg-muted">{t('admin.ceremony.leavers.none')}</p>
        )}
        <ul className="flex flex-col gap-3">
          {candidates.map((candidate) => (
            <LeaverRow
              key={candidate.sub}
              candidate={candidate}
              disabled={!fresh || leavers.pending}
              confirming={confirming === candidate.sub}
              onAsk={() => {
                leavers.reset();
                setConfirming(candidate.sub);
              }}
              onCancel={() => setConfirming(null)}
              onConfirm={() => leavers.mark(candidate, () => setConfirming(null))}
            />
          ))}
        </ul>
        {leavers.markError !== null && !leavers.stepUp && (
          <p role="alert" className="text-meta text-fg-status-alert">
            {t(leavers.markError)}
          </p>
        )}
      </section>
    </>
  );
}

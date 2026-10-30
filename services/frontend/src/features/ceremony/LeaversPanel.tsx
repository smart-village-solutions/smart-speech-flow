import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { hasFreshStepUp } from '@/app/auth/keycloak';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { LeaverRow } from './LeaverRow';
import { CEREMONY_VIEW } from './useCeremony';
import { useLeavers } from './useLeavers';

/**
 * Users with a key whom Studio no longer gives a recording permission (spec §9.8).
 * Step-up is asked for only once the admin asks to mark someone, and latched at mount.
 */
export function LeaversPanel() {
  const { t } = useTranslation();
  const [fresh] = useState(() => hasFreshStepUp());
  const [confirming, setConfirming] = useState<string | null>(null);
  const [askedStale, setAskedStale] = useState(false);
  const leavers = useLeavers();
  const candidates = leavers.candidates ?? [];

  return (
    <>
      {(askedStale || leavers.stepUp) && <StepUpPrompt returnTo={CEREMONY_VIEW} />}
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
              disabled={leavers.pending}
              confirming={confirming === candidate.sub}
              onAsk={() => {
                leavers.reset();
                if (fresh) setConfirming(candidate.sub);
                else setAskedStale(true);
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

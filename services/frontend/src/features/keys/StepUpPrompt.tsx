import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { requestStepUp } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import { Button } from '@/ui/primitives/Button';
import { KEYS_VIEW } from './useKeys';

const BODY = {
  keys: 'admin.keys.stepUpBody',
  ceremony: 'admin.ceremony.stepUpBody',
  recoveryRequests: 'admin.recovery.stepUpBody',
  recoveryApprovals: 'admin.recovery.stepUpBody',
} as const;

interface StepUpPromptProps {
  /** The staff view the redirect returns to, which also picks the explanation. */
  returnTo?: keyof typeof BODY;
}

/** Enrolment and ceremony steps need a fresh MFA login; the redirect back reopens the screen. */
export function StepUpPrompt({ returnTo = KEYS_VIEW }: Readonly<StepUpPromptProps>) {
  const { t } = useTranslation();
  const { resume } = useServices();
  const [failed, setFailed] = useState(false);

  const start = () => {
    resume.remember(returnTo);
    requestStepUp().catch(() => setFailed(true));
  };

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.keys.stepUpTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">{t(BODY[returnTo])}</p>
      {failed && (
        <p role="alert" className="text-meta text-fg-status-alert">
          {t('admin.keys.unavailable')}
        </p>
      )}
      <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={start}>
        {t('admin.keys.stepUpAction')}
      </Button>
    </section>
  );
}

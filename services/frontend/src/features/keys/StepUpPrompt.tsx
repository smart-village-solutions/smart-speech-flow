import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { requestStepUp } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import { Button } from '@/ui/primitives/Button';
import { KEYS_VIEW } from './useKeys';

/** Enrolment needs a fresh MFA login; the redirect back reopens this screen. */
export function StepUpPrompt() {
  const { t } = useTranslation();
  const { resume } = useServices();
  const [failed, setFailed] = useState(false);

  const start = () => {
    resume.remember(KEYS_VIEW);
    requestStepUp().catch(() => setFailed(true));
  };

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.keys.stepUpTitle')}</h2>
      <p className="text-note leading-chat text-fg-muted">{t('admin.keys.stepUpBody')}</p>
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

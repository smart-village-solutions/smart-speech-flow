import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useScreenLocale } from '@/app/providers/locale';
import { RouteState } from '@/app/router/RouteState';
import type { LinkDetails } from '@/domain/recording/recording.types';
import { formatDate } from '@/features/archive/format';
import { clockTime } from '@/lib/sessionTimes';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { Button } from '@/ui/primitives/Button';
import {
  type ConfirmationError,
  type ConfirmationOutcome,
  useKeyConfirmation,
} from './useKeyConfirmation';

const ERROR_KEYS: Record<ConfirmationError, string> = {
  missing: 'admin.keys.confirmation.missing',
  invalid: 'admin.keys.confirmation.invalid',
  expired: 'admin.keys.confirmation.expired',
  ceremony: 'admin.keys.confirmation.ceremony',
  failed: 'admin.keys.confirmation.failed',
};

function Card({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <ScreenShell>
      <main className="flex w-full flex-1 flex-col px-5 pb-10 pt-content-top">
        <div className="mx-auto flex w-full max-w-sm flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5">
          {children}
        </div>
      </main>
    </ScreenShell>
  );
}

function Outcome({ outcome }: Readonly<{ outcome: ConfirmationOutcome }>) {
  const { t } = useTranslation();
  return (
    <section role="status" className="flex flex-col gap-3">
      {outcome.kind === 'confirmed' ? (
        <>
          <p className="text-note text-fg-body">{t('admin.keys.confirmation.confirmed')}</p>
          <code className="text-body font-semibold text-fg-strong">
            {outcome.fingerprintDisplay}
          </code>
          <p className="text-note text-fg-muted">{t('admin.keys.confirmation.confirmedNext')}</p>
        </>
      ) : (
        <p className="text-note text-fg-body">{t('admin.keys.confirmation.declined')}</p>
      )}
    </section>
  );
}

function Details({ details, locale }: Readonly<{ details: LinkDetails; locale: string }>) {
  const { t } = useTranslation();
  const date = formatDate(details.requestedAt, locale);
  const time = clockTime(new Date(details.requestedAt).getTime(), locale);
  return (
    <>
      <p className="text-note leading-chat text-fg-muted">
        {t('admin.keys.confirmation.body', { date, time })}
      </p>
      <code className="text-body font-semibold text-fg-strong">{details.fingerprintDisplay}</code>
      <p className="text-note text-fg-muted">{t('admin.keys.confirmation.hint')}</p>
    </>
  );
}

/** The page the re-enrolment mail links to (spec §9.9); nobody needs to be signed in. */
export function KeyConfirmationScreen() {
  const { t, i18n } = useTranslation();
  useScreenLocale(navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en');
  const { details, error, busy, outcome, retry, confirm, decline } = useKeyConfirmation();

  if (details === null && error === null && outcome === null) return <RouteState />;
  return (
    <Card>
      <h1 className="text-thanks font-semibold text-fg-strong">
        {t('admin.keys.confirmation.title')}
      </h1>
      {outcome !== null && <Outcome outcome={outcome} />}
      {outcome === null && details !== null && <Details details={details} locale={i18n.language} />}
      {error !== null && (
        <p role="alert" className="text-note text-fg-status-alert">
          {t(ERROR_KEYS[error])}
        </p>
      )}
      {error === 'failed' && details === null && (
        <Button variant="compact" className="self-start bg-accent text-accent-on" onClick={retry}>
          {t('admin.keys.confirmation.retry')}
        </Button>
      )}
      {outcome === null && details !== null && (
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button
            variant="compact"
            className="bg-accent text-accent-on"
            disabled={busy}
            onClick={() => void confirm()}
          >
            {t('admin.keys.confirmation.confirm')}
          </Button>
          <Button
            variant="compact"
            className="bg-surface-field text-fg-strong"
            disabled={busy}
            onClick={() => void decline()}
          >
            {t('admin.keys.confirmation.decline')}
          </Button>
        </div>
      )}
    </Card>
  );
}

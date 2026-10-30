import { useTranslation } from 'react-i18next';
import type { LeaverCandidate } from '@/domain/recovery/recovery.types';
import { formatDate } from '@/features/archive/format';
import { useCopyToClipboard } from '@/ui/hooks/useCopyToClipboard';
import { Button } from '@/ui/primitives/Button';

const COPY = {
  idle: 'admin.ceremony.leavers.copySub',
  copied: 'admin.ceremony.leavers.copied',
  failed: 'admin.ceremony.leavers.copyFailed',
} as const;

interface LeaverRowProps {
  candidate: LeaverCandidate;
  /** Until a fresh MFA login, and while a marking is sent. */
  disabled: boolean;
  confirming: boolean;
  onAsk: () => void;
  onCancel: () => void;
  onConfirm: () => void;
}

/** One candidate: what lets an admin recognise them without a name, and the marking (§9.8). */
export function LeaverRow({
  candidate,
  disabled,
  confirming,
  onAsk,
  onCancel,
  onConfirm,
}: Readonly<LeaverRowProps>) {
  const { t, i18n } = useTranslation();
  const { state, copy } = useCopyToClipboard();
  const last = candidate.lastConversationAt;

  return (
    <li className="flex flex-col gap-2 border-t border-border-card pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-note font-semibold text-fg-strong">
          {candidate.displayName ?? candidate.sub}
        </span>
        {candidate.custodian && (
          <span className="rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium text-fg-status-alert">
            {t('admin.ceremony.leavers.custodian')}
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all text-meta text-fg-muted">{candidate.sub}</code>
        <Button
          variant="compact"
          className="bg-surface-field text-fg-strong"
          onClick={() => void copy(candidate.sub)}
        >
          {t(COPY[state])}
        </Button>
      </div>
      <p className="text-meta text-fg-muted">
        {t('admin.ceremony.leavers.fingerprint')} <code>{candidate.fingerprintDisplay}</code>
      </p>
      <p className="text-meta text-fg-muted">
        {t('admin.ceremony.leavers.activity', {
          enrolled: formatDate(candidate.enrolledAt, i18n.language),
          conversations: candidate.conversations,
        })}{' '}
        {last === null
          ? t('admin.ceremony.leavers.noConversation')
          : t('admin.ceremony.leavers.lastConversation', { date: formatDate(last, i18n.language) })}
      </p>
      {confirming ? (
        <div role="alert" className="flex flex-col gap-3">
          <p className="text-note leading-chat text-fg-strong">
            {t('admin.ceremony.leavers.confirmBody')}
          </p>
          {candidate.custodian && (
            <p className="text-note leading-chat text-fg-status-alert">
              {t('admin.ceremony.leavers.confirmCustodian')}
            </p>
          )}
          <div className="flex flex-wrap gap-3">
            <Button
              variant="compact"
              className="bg-accent text-accent-on"
              disabled={disabled}
              onClick={onConfirm}
            >
              {t('admin.ceremony.leavers.confirm')}
            </Button>
            <Button
              variant="compact"
              className="bg-surface-field text-fg-strong"
              onClick={onCancel}
            >
              {t('admin.ceremony.leavers.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <Button
          variant="compact"
          className="self-start bg-accent text-accent-on"
          disabled={disabled}
          onClick={onAsk}
        >
          {t('admin.ceremony.leavers.mark')}
        </Button>
      )}
    </li>
  );
}

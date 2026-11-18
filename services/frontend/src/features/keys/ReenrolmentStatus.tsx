import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { OwnKey } from '@/domain/recording/recording.types';
import { clockTime } from '@/lib/sessionTimes';
import { usePendingReenrolment } from './useKeys';

function Card({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <section
      role="status"
      className="flex flex-col gap-3 rounded-2xl border border-border-status bg-surface-card p-5"
    >
      {children}
    </section>
  );
}

function Message({ text, fingerprint }: Readonly<{ text: string; fingerprint?: string }>) {
  return (
    <Card>
      <p className="text-note text-fg-body">{text}</p>
      {fingerprint && <code className="text-note font-semibold text-fg-strong">{fingerprint}</code>}
    </Card>
  );
}

interface ReenrolmentStatusProps {
  ownKey: OwnKey;
  /** The key this screen just sent, before the gateway has named it as waiting. */
  requested?: string;
}

/**
 * Where a re-enrolment stands (§9.9): waiting for its mailed link, active once the
 * served key is the one that waited, or ended without it. Read from the gateway, so
 * it survives a reload and follows a link opened on another device.
 */
export function ReenrolmentStatus({ ownKey, requested }: Readonly<ReenrolmentStatusProps>) {
  const { t, i18n } = useTranslation();
  const { pending, read, waitedFor } = usePendingReenrolment();
  const awaited = waitedFor ?? requested;
  if (pending === null && awaited !== undefined && ownKey.fingerprintDisplay === awaited) {
    return <Message text={t('admin.keys.reenrol.done')} fingerprint={awaited} />;
  }
  if (pending !== null) {
    const time = clockTime(new Date(pending.expiresAt).getTime(), i18n.language);
    return (
      <Message
        text={t('admin.keys.reenrol.pendingUntil', { time })}
        fingerprint={pending.fingerprintDisplay}
      />
    );
  }
  if (requested === undefined) return null;
  if (!read) return <Message text={t('admin.keys.reenrol.pending')} fingerprint={requested} />;
  return <Message text={t('admin.keys.reenrol.ended')} />;
}

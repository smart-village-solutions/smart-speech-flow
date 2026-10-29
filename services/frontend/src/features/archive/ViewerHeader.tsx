import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { ConversationFacts } from '@/domain/archive/archive.types';
import { formatDate, formatTime, formatTimeRange, minutesBetween } from './format';
import type { HeaderView } from './timeline';
import type { StampView } from './verifyConversation';

interface ViewerHeaderProps {
  conversation: ConversationFacts;
  header: HeaderView;
  stamps: readonly StampView[];
  lastSeq: number;
}

function languageName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

function Field({ term, children }: Readonly<{ term: string; children: ReactNode }>) {
  return (
    <div className="flex gap-2 text-label">
      <dt className="text-fg-muted">{term}</dt>
      <dd className="text-fg-body">{children}</dd>
    </div>
  );
}

export function ViewerHeader({
  conversation,
  header,
  stamps,
  lastSeq,
}: Readonly<ViewerHeaderProps>) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const { startedAt, endedAt } = conversation;
  const stamp = stamps.find((item) => item.headSeq === lastSeq);
  const stampLine = (genTime: string) =>
    [
      t('admin.archive.stamp.at', {
        time: [formatDate(genTime, locale), formatTime(genTime, locale)].join(' '),
      }),
      t('admin.archive.stamp.unverified'),
    ].join(' ');
  const languages = header.languages.map((code) => languageName(code, locale)).join(', ');

  return (
    <div className="rounded-2xl border border-border-card bg-surface-card p-5">
      <h1 className="mb-3 text-thanks font-semibold text-fg-strong">
        {formatDate(startedAt, locale)} · {formatTimeRange(startedAt, endedAt, locale)} ·{' '}
        {t('admin.archive.duration', { minutes: minutesBetween(startedAt, endedAt) })}
      </h1>
      {conversation.incomplete && (
        <p className="mb-2 inline-block rounded-full bg-surface-status px-2 py-0.5 text-meta font-medium text-fg-status-alert">
          {t('admin.archive.incomplete')}
        </p>
      )}
      <dl className="flex flex-col gap-1">
        {header.guestName !== null && (
          <Field term={t('admin.archive.field.guest')}>
            {header.guestName}
            {header.enteredBy !== null &&
              ' ' + t(`admin.archive.consent.enteredBy.${header.enteredBy}`)}
          </Field>
        )}
        {languages !== '' && <Field term={t('admin.archive.field.languages')}>{languages}</Field>}
        <Field term={t('admin.archive.field.basis')}>
          {t(`admin.archive.basis.${conversation.legalBasis}`)}
        </Field>
        <Field term={t('admin.archive.field.retention')}>
          {t('admin.archive.retention', { date: formatDate(conversation.retentionUntil, locale) })}
          {conversation.legalHold && ` · ${t('admin.archive.hold')}`}
        </Field>
        <Field term={t('admin.archive.field.verification')}>
          {t(`admin.archive.verification.${conversation.verification}`)}
        </Field>
        <Field term={t('admin.archive.field.stamp')}>
          {stamp === undefined ? t('admin.archive.stamp.pending') : stampLine(stamp.genTime)}
        </Field>
      </dl>
    </div>
  );
}

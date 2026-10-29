import { useTranslation } from 'react-i18next';
import type { OpenedConversation, WindowFacts } from '@/domain/archive/archive.types';
import { Button } from '@/ui/primitives/Button';
import { AmendmentNote } from './AmendmentNote';
import { ConsentBody } from './ConsentBody';
import { formatTime } from './format';
import { MessageBody } from './MessageBody';
import type { EntryView } from './timeline';

interface EntryCardProps {
  view: EntryView;
  opened: OpenedConversation;
  keys: ReadonlyMap<string, CryptoKey>;
  /** Absent while an earlier amendment waits for confirmation. */
  onAmend?: (entryId: string) => void;
}

function WindowDivider({ window, closing }: Readonly<{ window: WindowFacts; closing: boolean }>) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const label = closing
    ? t('admin.archive.window.closed', {
        time: formatTime(window.closedAt ?? window.openedAt, locale),
        reason: t(`admin.archive.closeReason.${window.closeReason ?? 'session_ended'}`),
      })
    : t('admin.archive.window.opened', { time: formatTime(window.openedAt, locale) });
  return (
    <li className="my-3 flex items-center gap-3 text-meta text-fg-muted">
      <span className="h-px flex-1 bg-border-divider" />
      <span>{label}</span>
      <span className="h-px flex-1 bg-border-divider" />
    </li>
  );
}

function Content({ view, opened, keys }: Readonly<Omit<EntryCardProps, 'onAmend'>>) {
  const { t } = useTranslation();
  if (view.state !== 'ok' || view.record === undefined) {
    return (
      <p className="text-label text-fg-status-alert">{t(`admin.archive.entry.${view.state}`)}</p>
    );
  }
  if (view.record.kind === 'consent') return <ConsentBody record={view.record.record} />;
  if (view.record.kind === 'message' || view.record.kind === 'failed') {
    return (
      <MessageBody record={view.record.record} entry={view.entry} opened={opened} keys={keys} />
    );
  }
  return null;
}

/** One entry with its playbacks and amendments beside it; originals are never edited. */
export function EntryCard({ view, opened, keys, onAmend }: Readonly<EntryCardProps>) {
  const { t, i18n } = useTranslation();
  const locale = i18n.language;
  const sender =
    view.record?.kind === 'message' || view.record?.kind === 'failed'
      ? view.record.record.sender
      : null;

  return (
    <>
      {view.opens && <WindowDivider window={view.opens} closing={false} />}
      <li className="mt-2 flex flex-col gap-2 rounded-xl border border-border-card bg-surface-card px-4 py-3">
        <p className="text-meta font-medium text-fg-muted">
          {formatTime(view.entry.createdAt, locale)} · {t(`admin.archive.kind.${view.entry.kind}`)}
          {sender !== null && ' · ' + t(`admin.archive.sender.${sender}`)}
        </p>
        <Content view={view} opened={opened} keys={keys} />
        {view.playbacks.map((playback) => (
          <p key={`${playback.event}-${playback.at}`} className="text-meta text-fg-muted">
            {t(`admin.archive.playback.${playback.event}`, {
              time: formatTime(playback.at, locale),
            })}
          </p>
        ))}
        {view.amendments.map((amendment) => (
          <AmendmentNote key={amendment.entryId} amendment={amendment} onAmend={onAmend} />
        ))}
        {view.state === 'ok' && onAmend && (
          <Button
            variant="compact"
            className="self-start"
            onClick={() => onAmend(view.entry.entryId)}
          >
            {t('admin.archive.amend')}
          </Button>
        )}
      </li>
      {view.closes && <WindowDivider window={view.closes} closing />}
    </>
  );
}

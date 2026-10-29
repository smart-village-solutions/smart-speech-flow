import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { AmendmentDialog } from './AmendmentDialog';
import { AmendmentNote } from './AmendmentNote';
import { EntryCard } from './EntryCard';
import { GapList } from './GapList';
import { PendingAmendment } from './PendingAmendment';
import { useAmend } from './useAmend';
import { type Opened, useOpenedConversation } from './useArchive';
import { ViewerHeader } from './ViewerHeader';

interface ConversationViewerProps {
  conversationId: string;
  unlocked: UnlockedKeys;
}

interface ReadyViewerProps {
  state: Extract<Opened, { status: 'ready' }>;
  onAdded: () => void;
}

function ReadyViewer({ state, onAdded }: Readonly<ReadyViewerProps>) {
  const { t } = useTranslation();
  const { opened, view, keys, stamps } = state;
  const [amending, setAmending] = useState<string | null>(null);
  const amend = useAmend(opened, keys, () => {
    setAmending(null);
    onAdded();
  });
  // While an amendment waits for confirmation no other starts: it keeps its own bytes.
  const onAmend = amend.unconfirmed ? undefined : setAmending;

  return (
    <>
      <ViewerHeader
        conversation={opened.conversation}
        header={view.header}
        stamps={stamps}
        lastSeq={opened.entries.at(-1)?.seq ?? 0}
      />
      {view.gaps.length > 0 && <GapList gaps={view.gaps} />}
      {amending === null && amend.unconfirmed && <PendingAmendment amend={amend} />}
      <ol className="flex flex-col">
        {view.entries.map((entry) => (
          <EntryCard
            key={entry.entry.entryId}
            view={entry}
            opened={opened}
            keys={keys}
            onAmend={onAmend}
          />
        ))}
      </ol>
      {view.unattached.map((amendment) => (
        <div
          key={amendment.entryId}
          className="rounded-xl border border-border-card bg-surface-card px-4 py-3"
        >
          <p className="text-meta font-medium text-fg-muted">
            {t('admin.archive.amendment.unattached')}
          </p>
          <AmendmentNote amendment={amendment} onAmend={onAmend} />
        </div>
      ))}
      {amending !== null && (
        <AmendmentDialog
          opened={opened}
          amend={amend}
          references={[amending]}
          onClose={() => setAmending(null)}
        />
      )}
    </>
  );
}

/** One conversation, shown only once every check of spec §10.6 has passed. */
export function ConversationViewer({
  conversationId,
  unlocked,
}: Readonly<ConversationViewerProps>) {
  const { t } = useTranslation();
  const [version, setVersion] = useState(0);
  const state = useOpenedConversation(conversationId, unlocked, version);

  if (state.status === 'checking')
    return <p className="text-note text-fg-muted">{t('admin.archive.checking')}</p>;
  if (state.status === 'unavailable') {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.archive.unavailable')}
      </p>
    );
  }
  if (state.status === 'broken') {
    return (
      <div role="alert" className="rounded-2xl border border-border-status bg-surface-card p-5">
        <h2 className="mb-1.5 text-body font-semibold text-fg-strong">
          {t('admin.archive.integrity.title')}
        </h2>
        <p className="text-note text-fg-muted">{t(`admin.archive.integrity.${state.stage}`)}</p>
      </div>
    );
  }
  return <ReadyViewer state={state} onAdded={() => setVersion((value) => value + 1)} />;
}

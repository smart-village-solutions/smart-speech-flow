import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getAdminIdentity } from '@/app/auth/keycloak';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { AmendmentDialog } from './AmendmentDialog';
import { AmendmentNote } from './AmendmentNote';
import { EntryCard } from './EntryCard';
import { FindingsColumns } from './FindingsColumns';
import { GapList } from './GapList';
import { OpeningState } from './OpeningState';
import { verifiedSummary } from './summary';
import { PendingAmendment } from './PendingAmendment';
import { useAmend } from './useAmend';
import { VerificationPanel } from './VerificationPanel';
import { type Opened, useOpenedConversation } from './useArchive';
import { ViewerHeader } from './ViewerHeader';

interface ConversationViewerProps {
  conversationId: string;
  /** The list row's employee: someone else's for a recovered conversation (§9.5). */
  employeeSub?: string;
  unlocked: UnlockedKeys;
}

interface ReadyViewerProps {
  state: Extract<Opened, { status: 'ready' }>;
  unlocked: UnlockedKeys;
  onAdded: () => void;
}

/** Amendments are the employee's own (§10.4); while one waits for confirmation no other starts. */
function amendable(opened: Readonly<OpenedConversation>, unconfirmed: boolean): boolean {
  return opened.conversation.employeeSub === getAdminIdentity()?.userSub && !unconfirmed;
}

function ReadyViewer({ state, unlocked, onAdded }: Readonly<ReadyViewerProps>) {
  const { t } = useTranslation();
  const { opened, view, keys, stamps } = state;
  const [amending, setAmending] = useState<string | null>(null);
  const amend = useAmend(opened, keys, () => {
    setAmending(null);
    onAdded();
  });
  const onAmend = amendable(opened, amend.unconfirmed) ? setAmending : undefined;

  return (
    <>
      <ViewerHeader
        conversation={opened.conversation}
        header={view.header}
        stamps={stamps}
        lastSeq={opened.entries.at(-1)?.seq ?? 0}
        summary={verifiedSummary(state.records)}
      />
      <VerificationPanel state={state} unlocked={unlocked} onChanged={onAdded} />
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
          >
            <FindingsColumns entryId={entry.entry.entryId} records={state.records} />
          </EntryCard>
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
  employeeSub,
  unlocked,
}: Readonly<ConversationViewerProps>) {
  const [version, setVersion] = useState(0);
  const state = useOpenedConversation(conversationId, unlocked, version, employeeSub);

  if (state.status !== 'ready')
    return <OpeningState state={state} unavailable="admin.archive.unavailable" />;
  return (
    <ReadyViewer
      state={state}
      unlocked={unlocked}
      onAdded={() => setVersion((value) => value + 1)}
    />
  );
}

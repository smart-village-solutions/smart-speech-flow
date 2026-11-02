import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { Button } from '@/ui/primitives/Button';
import type { Opened } from './openConversation';
import { RequestVerificationDialog } from './RequestVerificationDialog';
import { useRequestVerification } from './useRequestVerification';
import { VerificationRecords } from './VerificationRecords';

interface VerificationPanelProps {
  state: Extract<Opened, { status: 'ready' }>;
  unlocked: UnlockedKeys;
  onChanged: () => void;
}

function Dialog({
  state,
  unlocked,
  onClose,
}: Readonly<{
  state: VerificationPanelProps['state'];
  unlocked: UnlockedKeys;
  onClose: (assigned: boolean) => void;
}>) {
  const request = useRequestVerification(state, unlocked, () => onClose(true));
  return (
    <RequestVerificationDialog
      request={request}
      languages={state.view.header.languages}
      onClose={() => onClose(false)}
    />
  );
}

/** Requesting verification and every record, for whoever may open the conversation (§10.7). */
export function VerificationPanel({
  state,
  unlocked,
  onChanged,
}: Readonly<VerificationPanelProps>) {
  const { t } = useTranslation();
  const [requesting, setRequesting] = useState(false);
  const everyKey = state.opened.keys.every((key) => key.wrap !== null);
  const close = (assigned: boolean) => {
    setRequesting(false);
    if (assigned) onChanged();
  };
  return (
    <>
      {everyKey ? (
        <Button
          variant="compact"
          className="self-start bg-accent text-accent-on"
          onClick={() => setRequesting(true)}
        >
          {t('admin.archive.verification.request')}
        </Button>
      ) : (
        <p className="text-label text-fg-muted">{t('admin.archive.verification.missingKeys')}</p>
      )}
      <VerificationRecords
        records={state.records}
        onReassign={everyKey ? () => setRequesting(true) : undefined}
      />
      {requesting && <Dialog state={state} unlocked={unlocked} onClose={close} />}
    </>
  );
}

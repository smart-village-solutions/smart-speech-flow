import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { type Bytes, equalBytes } from '@/core/crypto/bytes';
import { Button } from '@/ui/primitives/Button';
import { DeclineForm } from './DeclineForm';
import { RecoveryLocked } from './RecoveryLocked';

interface ReviewActionsProps {
  fingerprint: Bytes | null;
  keys: UnlockedKeys | null;
  pending: boolean;
  onApprove: (confirmed: Bytes) => void;
  onDecline: (reason: string) => void;
  onOpenKeys: () => void;
}

/**
 * The tick holds the fingerprint it was given: a different value shown later
 * reads as unticked, and approving seals only to the ticked one (spec §9.5).
 */
export function ReviewActions({
  fingerprint,
  keys,
  pending,
  onApprove,
  onDecline,
  onOpenKeys,
}: Readonly<ReviewActionsProps>) {
  const { t } = useTranslation();
  const [ticked, setTicked] = useState<Bytes | null>(null);
  const confirmed = ticked !== null && fingerprint !== null && equalBytes(ticked, fingerprint);
  return (
    <>
      <label className="flex items-start gap-3 text-note text-fg-body">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={fingerprint === null}
          onChange={(e) => setTicked(e.target.checked ? fingerprint : null)}
        />
        {t('admin.recovery.approve.confirmed')}
      </label>
      {keys === null ? (
        <RecoveryLocked onOpenKeys={onOpenKeys} />
      ) : (
        <Button
          className="self-start bg-accent text-accent-on"
          disabled={!confirmed || pending}
          onClick={() => {
            if (ticked !== null) onApprove(ticked);
          }}
        >
          {t(pending ? 'admin.recovery.approve.approving' : 'admin.recovery.approve.action')}
        </Button>
      )}
      <DeclineForm pending={pending} onDecline={onDecline} />
    </>
  );
}

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { AbortReason } from '@/domain/recovery/recovery.types';
import { Button } from '@/ui/primitives/Button';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';
import { CEREMONY_QUERY } from './useCeremony';

/** Any participant may stop a ceremony; it then restarts from scratch (spec §9.2, §19). */
export function AbortButton({ ceremonyId, reason }: Readonly<{ ceremonyId: string; reason: AbortReason }>) {
  const { t } = useTranslation();
  const { recoveryCeremony, paperDevice } = useServices();
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [failed, setFailed] = useState(false);

  // The paper key goes only once the gateway has closed the ceremony; until then it may still finish.
  const abort = async () => {
    setAsking(false);
    setFailed(false);
    try {
      await recoveryCeremony.abort(ceremonyId, reason);
      paperDevice.clear();
    } catch {
      setFailed(true);
    }
    await queryClient.invalidateQueries({ queryKey: CEREMONY_QUERY });
  };

  return (
    <>
      <Button variant="compact" className="self-start border border-border-card text-fg-strong print:hidden" onClick={() => setAsking(true)}>
        {t('admin.ceremony.abortAction')}
      </Button>
      {failed && (
        <p role="alert" className="text-meta text-fg-status-alert print:hidden">
          {t('admin.ceremony.abortFailed')}
        </p>
      )}
      <ConfirmDialog
        open={asking}
        title={t('admin.ceremony.abortTitle')}
        body={t('admin.ceremony.abortBody')}
        confirmLabel={t('admin.ceremony.abortAction')}
        cancelLabel={t('admin.ceremony.keepGoing')}
        onConfirm={() => void abort()}
        onCancel={() => setAsking(false)}
      />
    </>
  );
}

import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { RecoveryKey } from '@/domain/recovery/recovery.types';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { Button } from '@/ui/primitives/Button';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { CandidateList } from './CandidateList';
import { ThresholdSelect } from './ThresholdSelect';
import { DealerPicker } from './DealerPicker';
import { CEREMONY_VIEW } from './useCeremony';
import { type ResharingError, useStartResharing } from './useStartResharing';

const ERROR_KEYS: Record<Exclude<ResharingError, 'stepUp'>, string> = {
  dealers: 'admin.ceremony.reshare.errorDealers',
  unusable: 'admin.ceremony.reshare.errorUnusable',
  changed: 'admin.ceremony.reshare.errorChanged',
  invalid: 'admin.ceremony.startInvalid',
  failed: 'admin.ceremony.startFailed',
};
const MAX_CUSTODIANS = 10;

interface ReshareFormProps {
  tenantId: string;
  recoveryKey: RecoveryKey;
  onCancel: () => void;
}

/** The admin names the new custodians and k current holders to hand their shares over (spec §9.7). */
export function ReshareForm({ tenantId, recoveryKey, onCancel }: Readonly<ReshareFormProps>) {
  const { t } = useTranslation();
  const { start, error, pending } = useStartResharing(tenantId);
  const [custodians, setCustodians] = useState<string[]>([]);
  const [dealers, setDealers] = useState<number[]>([]);
  const [k, setK] = useState(recoveryKey.k);
  const [paper, setPaper] = useState(false);

  if (error === 'stepUp') return <StepUpPrompt returnTo={CEREMONY_VIEW} />;

  const ready =
    dealers.length === recoveryKey.k &&
    custodians.length >= k + 1 &&
    custodians.length <= MAX_CUSTODIANS;
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void start({ k, custodians, dealers, paper, holdersCeremonyId: recoveryKey.holdersCeremonyId });
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-4 rounded-2xl border border-border-card bg-surface-card p-5"
    >
      <h2 className="text-body font-semibold text-fg-strong">
        {t('admin.ceremony.reshare.title')}
      </h2>
      <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.reshare.intro')}</p>
      <CandidateList chosen={custodians} onChange={setCustodians} />
      <ThresholdSelect k={k} onChange={setK} />
      <Checkbox checked={paper} onCheckedChange={setPaper}>
        {t('admin.ceremony.paperLabel')}
      </Checkbox>
      <DealerPicker
        holders={recoveryKey.holders}
        k={recoveryKey.k}
        chosen={dealers}
        onChange={setDealers}
      />
      {error !== null && (
        <p role="alert" className="text-meta text-fg-status-alert">
          {t(ERROR_KEYS[error])}
        </p>
      )}
      <div className="flex gap-3">
        <Button
          type="submit"
          variant="compact"
          className="bg-accent text-accent-on"
          disabled={pending || !ready}
        >
          {t(pending ? 'admin.ceremony.reshare.pending' : 'admin.ceremony.reshare.submit')}
        </Button>
        <Button type="button" variant="compact" onClick={onCancel}>
          {t('admin.ceremony.reshare.cancel')}
        </Button>
      </div>
    </form>
  );
}

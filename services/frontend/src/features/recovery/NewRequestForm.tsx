import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { Button } from '@/ui/primitives/Button';
import { CandidatePicker, MAX_CONVERSATIONS } from './CandidatePicker';
import { StepUpPrompt } from '@/features/keys/StepUpPrompt';
import { dayRange, localDay } from './days';
import { FIELD, type Filter, LABEL, RequestFilter } from './RequestFilter';
import { faultKey } from './faults';
import { RECOVERY_REQUESTS_VIEW, useCandidates, useEmployees, useFileRequest } from './useRecovery';

interface NewRequestFormProps {
  keys: UnlockedKeys;
  onFiled: () => void;
}

export function NewRequestForm({ keys, onFiled }: Readonly<NewRequestFormProps>) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<Filter>(() => ({
    employee: '',
    from: localDay(-30),
    to: localDay(),
  }));
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const [reason, setReason] = useState('');
  const employees = useEmployees();
  const range = dayRange(filter.from, filter.to);
  const candidates = useCandidates(filter.employee, range?.from ?? '', range?.to ?? '');
  const filing = useFileRequest(keys, 'access');
  // A new filter shows other conversations: hidden ticks would still count toward the cap.
  const refilter = (next: Filter) => {
    setFilter(next);
    setTicked(new Set());
  };

  if (filing.fault === 'step_up') return <StepUpPrompt returnTo={RECOVERY_REQUESTS_VIEW} />;

  const toggle = (id: string) =>
    setTicked((current) => {
      const next = new Set(current);
      if (!next.delete(id) && next.size < MAX_CONVERSATIONS) next.add(id);
      return next;
    });
  const chosen = (candidates.data ?? []).filter((c) => ticked.has(c.conversationId));
  const ready = chosen.length > 0 && reason.trim() !== '' && !filing.pending;
  const submit = async () => {
    if (await filing.file({ reason: reason.trim(), candidates: chosen })) onFiled();
  };

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-body font-semibold text-fg-strong">{t('admin.recovery.new.title')}</h2>
      <RequestFilter employees={employees.data ?? []} filter={filter} onChange={refilter} />
      {filter.employee !== '' && candidates.data && (
        <CandidatePicker candidates={candidates.data} ticked={ticked} onToggle={toggle} />
      )}
      <label className={LABEL}>
        {t('admin.recovery.new.reason')}
        <textarea
          rows={4}
          maxLength={1000}
          className={FIELD}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <span className="-mt-3 self-end text-meta text-fg-muted">
        {t('admin.recovery.new.used', { used: reason.length })}
      </span>
      <Button
        className="self-start bg-accent text-accent-on"
        disabled={!ready}
        onClick={() => void submit()}
      >
        {t('admin.recovery.new.submit')}
      </Button>
      {filing.fault !== null && (
        <p role="alert" className="text-label text-fg-status-alert">
          {t(faultKey(filing.fault))}
        </p>
      )}
    </section>
  );
}

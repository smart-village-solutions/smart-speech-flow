import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { Button } from '@/ui/primitives/Button';
import { CandidatePicker, MAX_CONVERSATIONS } from './CandidatePicker';
import { faultKey } from './faults';
import { useCandidates, useEmployees, useFileRequest } from './useRecovery';

const FIELD =
  'w-full rounded-xl border border-border-card bg-surface-card px-3 py-2.5 text-note text-fg-body';
const LABEL = 'flex flex-col gap-1.5 text-meta font-medium text-fg-muted';
const DAY = 24 * 60 * 60 * 1000;

const isoDay = (at: number) => new Date(at).toISOString().slice(0, 10);
/** A date input's day as the start of that day, local time, in ISO form. */
const startOf = (day: string) => new Date(`${day}T00:00:00`).toISOString();

interface NewRequestFormProps {
  keys: UnlockedKeys;
  onFiled: () => void;
}

export function NewRequestForm({ keys, onFiled }: Readonly<NewRequestFormProps>) {
  const { t } = useTranslation();
  const [employee, setEmployee] = useState('');
  const [from, setFrom] = useState(() => isoDay(Date.now() - 30 * DAY));
  const [to, setTo] = useState(() => isoDay(Date.now() + DAY));
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const [reason, setReason] = useState('');
  const employees = useEmployees();
  const candidates = useCandidates(employee, startOf(from), startOf(to));
  const filing = useFileRequest(keys);

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
      <label className={LABEL}>
        {t('admin.recovery.new.employee')}
        <select className={FIELD} value={employee} onChange={(e) => setEmployee(e.target.value)}>
          <option value="">{t('admin.recovery.new.chooseEmployee')}</option>
          {(employees.data ?? []).map((e) => (
            <option key={e.sub} value={e.sub}>
              {e.displayName ?? e.sub}
            </option>
          ))}
        </select>
      </label>
      <div className="flex gap-3">
        <label className={`${LABEL} flex-1`}>
          {t('admin.recovery.new.from')}
          <input
            type="date"
            className={FIELD}
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <label className={`${LABEL} flex-1`}>
          {t('admin.recovery.new.to')}
          <input type="date" className={FIELD} value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      {employee !== '' && candidates.data && (
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

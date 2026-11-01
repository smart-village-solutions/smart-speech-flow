import { useTranslation } from 'react-i18next';
import type { RecoveryEmployee } from '@/domain/recovery/requests.types';

export const FIELD =
  'w-full rounded-xl border border-border-card bg-surface-card px-3 py-2.5 text-body text-fg-body';
export const LABEL = 'flex flex-col gap-1.5 text-meta font-medium text-fg-muted';

export interface Filter {
  employee: string;
  from: string;
  to: string;
}

interface RequestFilterProps {
  employees: readonly RecoveryEmployee[];
  filter: Filter;
  onChange: (filter: Filter) => void;
}

/** Whose conversations, between which local days; leavers are listed by sub. */
export function RequestFilter({ employees, filter, onChange }: Readonly<RequestFilterProps>) {
  const { t } = useTranslation();
  const set = (field: keyof Filter) => (value: string) => onChange({ ...filter, [field]: value });
  return (
    <>
      <label className={LABEL}>
        {t('admin.recovery.new.employee')}
        <select
          className={FIELD}
          value={filter.employee}
          onChange={(e) => set('employee')(e.target.value)}
        >
          <option value="">{t('admin.recovery.new.chooseEmployee')}</option>
          {employees.map((e) => (
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
            value={filter.from}
            onChange={(e) => set('from')(e.target.value)}
          />
        </label>
        <label className={`${LABEL} flex-1`}>
          {t('admin.recovery.new.to')}
          <input
            type="date"
            className={FIELD}
            value={filter.to}
            onChange={(e) => set('to')(e.target.value)}
          />
        </label>
      </div>
    </>
  );
}

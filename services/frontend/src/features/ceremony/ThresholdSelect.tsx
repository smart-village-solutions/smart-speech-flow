import { useTranslation } from 'react-i18next';

const THRESHOLDS = [1, 2, 3, 4, 5];

/** How many shares open a conversation: 1 to 5 (spec §9.2). */
export function ThresholdSelect({
  k,
  onChange,
}: Readonly<{ k: number; onChange: (k: number) => void }>) {
  const { t } = useTranslation();
  return (
    <label className="flex flex-col gap-1 text-note text-fg-strong">
      {t('admin.ceremony.thresholdLabel')}
      <select
        value={k}
        onChange={(event) => onChange(Number(event.target.value))}
        className="rounded-lg border border-border-card bg-surface-card p-2 text-body text-fg-strong"
      >
        {THRESHOLDS.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
    </label>
  );
}

import { useId } from 'react';
import { useTranslation } from 'react-i18next';

/**
 * The concept's two recovery modes (§7.7): standard needs one approval, enhanced
 * two. The gateway still takes 1 to 5; a key needing more keeps its own choice.
 */
const MODES = [1, 2];

export function RecoveryModeChoice({
  k,
  onChange,
}: Readonly<{ k: number; onChange: (k: number) => void }>) {
  const { t } = useTranslation();
  const name = useId();
  const choices = MODES.includes(k) ? MODES : [...MODES, k];
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-note text-fg-strong">{t('admin.ceremony.modeLabel')}</legend>
      {choices.map((value) => (
        <label key={value} className="flex items-start gap-2 text-note text-fg-body">
          <input
            type="radio"
            name={name}
            className="mt-1"
            checked={k === value}
            onChange={() => onChange(value)}
          />
          {value === 1
            ? t('admin.ceremony.modeStandard')
            : t('admin.ceremony.modeEnhanced', { k: value })}
        </label>
      ))}
    </fieldset>
  );
}

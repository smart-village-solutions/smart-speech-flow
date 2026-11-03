import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { recoveryModeText } from './recoveryMode';

/**
 * The concept's two recovery modes (§7.7): standard needs one approval, enhanced
 * two. The gateway still takes 1 to 5, so an active key that needs more keeps
 * its own value as a choice while its approvers are changed.
 */
const MODES = [1, 2];

interface RecoveryModeChoiceProps {
  k: number;
  onChange: (k: number) => void;
  /** The active key's threshold, when changing its approvers. */
  held?: number;
  /** Studio's policy sets the mode: `k` is shown as the only, fixed choice (#680). */
  fromStudio?: boolean;
}

export function RecoveryModeChoice({
  k,
  onChange,
  held,
  fromStudio = false,
}: Readonly<RecoveryModeChoiceProps>) {
  const { t } = useTranslation();
  const name = useId();
  const offered = held === undefined || MODES.includes(held) ? MODES : [...MODES, held];
  const choices = fromStudio ? [k] : offered;
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
            disabled={fromStudio}
            onChange={() => onChange(value)}
          />
          {recoveryModeText(t, value)}
        </label>
      ))}
      {fromStudio && (
        <p className="text-meta text-fg-muted">{t('admin.ceremony.modeFromStudio')}</p>
      )}
    </fieldset>
  );
}

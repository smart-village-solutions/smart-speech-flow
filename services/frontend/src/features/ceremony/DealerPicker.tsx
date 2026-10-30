import { useTranslation } from 'react-i18next';
import type { CurrentHolder } from '@/domain/recovery/recovery.types';
import { Checkbox } from '@/ui/primitives/Checkbox';

interface DealerPickerProps {
  holders: readonly CurrentHolder[];
  k: number;
  chosen: number[];
  onChange: (chosen: number[]) => void;
}

function holderName(holder: Readonly<CurrentHolder>, paper: (ref: string) => string): string {
  if (holder.kind === 'paper') return paper(holder.holderRef);
  return holder.displayName ?? holder.holderRef;
}

/** Exactly k current holders hand their shares over; one whose share is lost cannot (spec §9.7). */
export function DealerPicker({ holders, k, chosen, onChange }: Readonly<DealerPickerProps>) {
  const { t } = useTranslation();
  const toggle = (index: number, on: boolean) =>
    onChange(on ? [...chosen, index] : chosen.filter((item) => item !== index));

  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2 text-note font-semibold text-fg-strong">
        {t('admin.ceremony.reshare.dealers', { k })}
      </legend>
      {holders.map((holder) => (
        <div key={holder.holderIndex} className="flex items-center justify-between gap-3">
          <Checkbox
            checked={chosen.includes(holder.holderIndex)}
            disabled={holder.state === 'lost'}
            onCheckedChange={(on) => toggle(holder.holderIndex, on)}
          >
            {holderName(holder, (ref) => t('admin.ceremony.reshare.holderPaper', { ref }))}
          </Checkbox>
          <span
            className={`text-meta ${holder.state === 'lost' ? 'text-fg-status-alert' : 'text-fg-muted'}`}
          >
            {t(`admin.ceremony.reshare.state.${holder.state}`)}
          </span>
        </div>
      ))}
    </fieldset>
  );
}

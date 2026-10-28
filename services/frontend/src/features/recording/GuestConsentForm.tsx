import { useTranslation } from 'react-i18next';
import type { PolicyLevel } from '@/domain/recording/recordingSession.types';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { TextField } from '@/ui/primitives/TextField';
import { NAME_MAX_LENGTH } from './consentLimits';
import { SignaturePad } from './SignaturePad';

export interface ConsentFormValues {
  name: string;
  signaturePng: string | null;
  cannotSign: boolean;
}

interface GuestConsentFormProps {
  values: ConsentFormValues;
  /** The employee typed the name; the guest confirms or corrects it. */
  proposed: boolean;
  signature: PolicyLevel;
  onChange: (values: ConsentFormValues) => void;
}

/** What a first yes adds to the text (spec §6): the guest's name, and a signature per policy. */
export function GuestConsentForm({
  values,
  proposed,
  signature,
  onChange,
}: Readonly<GuestConsentFormProps>) {
  const { t } = useTranslation();
  const label = t('recording.consent.signature');

  return (
    <>
      <div className="mt-4 flex flex-col gap-1.5">
        <TextField
          label={t('recording.consent.name')}
          value={values.name}
          // A tablet passes from guest to guest: it must not offer earlier names.
          autoComplete="off"
          maxLength={NAME_MAX_LENGTH}
          onChange={(event) => onChange({ ...values, name: event.target.value })}
        />
        {proposed && (
          <p className="text-meta text-fg-muted">{t('recording.consent.nameProposed')}</p>
        )}
      </div>
      {signature !== 'off' && (
        <SignaturePad
          label={signature === 'optional' ? `${label} (${t('recording.consent.optional')})` : label}
          onChange={(signaturePng) => onChange({ ...values, signaturePng })}
        />
      )}
      {signature === 'required' && (
        <Checkbox
          className="mt-3"
          checked={values.cannotSign}
          onCheckedChange={(cannotSign) => onChange({ ...values, cannotSign })}
        >
          {t('recording.consent.cannotSign')}
        </Checkbox>
      )}
    </>
  );
}

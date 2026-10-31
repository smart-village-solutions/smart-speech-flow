import { useTranslation } from 'react-i18next';
import type { PolicyLevel } from '@/domain/recording/recordingSession.types';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { TextField } from '@/ui/primitives/TextField';
import { NAME_MAX_LENGTH } from './consentLimits';

interface RequestIdentityFieldsProps {
  idCheck: PolicyLevel | null;
  name: string;
  idChecked: boolean;
  onNameChange: (name: string) => void;
  onIdCheckedChange: (checked: boolean) => void;
}

/** Identity details are collected only for the conversation's first request. */
export function RequestIdentityFields({
  idCheck,
  name,
  idChecked,
  onNameChange,
  onIdCheckedChange,
}: Readonly<RequestIdentityFieldsProps>) {
  const { t } = useTranslation();
  const offered = idCheck === 'optional' || idCheck === 'required';
  return (
    <>
      <div className="mt-4 flex flex-col gap-1.5">
        <TextField
          label={t('admin.recording.ask.name')}
          value={name}
          autoComplete="off"
          maxLength={NAME_MAX_LENGTH}
          onChange={(event) => onNameChange(event.target.value)}
        />
        <p className="text-meta text-fg-muted">{t('admin.recording.ask.nameHint')}</p>
      </div>
      {offered && (
        <Checkbox className="mt-4" checked={idChecked} onCheckedChange={onIdCheckedChange}>
          {t('admin.recording.ask.idChecked')}
        </Checkbox>
      )}
      {idCheck === 'required' && (
        <p className="mt-2 text-meta text-fg-muted">{t('admin.recording.ask.idRequired')}</p>
      )}
    </>
  );
}

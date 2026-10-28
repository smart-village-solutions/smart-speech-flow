import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { PolicyLevel, RecordingAsk } from '@/domain/recording/recordingSession.types';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { TextField } from '@/ui/primitives/TextField';
import { NAME_MAX_LENGTH } from './consentLimits';

interface RecordingRequestDialogProps {
  /** The policy's ID check; null when unknown, which offers none. */
  idCheck: PolicyLevel | null;
  error: string | null;
  sending: boolean;
  onSubmit: (ask: RecordingAsk) => void;
  onCancel: () => void;
}

/** The employee's first request: the guest's name to confirm, and the ID check (spec §6). */
export function RecordingRequestDialog({
  idCheck,
  error,
  sending,
  onSubmit,
  onCancel,
}: Readonly<RecordingRequestDialogProps>) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [idChecked, setIdChecked] = useState(false);
  const offered = idCheck === 'optional' || idCheck === 'required';
  const guestName = name.trim();

  return (
    <QuestionDialog
      open
      title={t('admin.recording.ask.title')}
      confirmLabel={t('admin.recording.request')}
      cancelLabel={t('admin.recording.ask.cancel')}
      error={error === null ? null : t(error)}
      confirmDisabled={sending || (idCheck === 'required' && !idChecked)}
      onConfirm={() =>
        onSubmit({
          ...(guestName === '' ? {} : { guestName }),
          ...(offered ? { idChecked } : {}),
        })
      }
      onCancel={onCancel}
    >
      <p className="mt-2 text-note leading-chat text-fg-muted">{t('admin.recording.ask.body')}</p>
      <div className="mt-4 flex flex-col gap-1.5">
        <TextField
          label={t('admin.recording.ask.name')}
          value={name}
          autoComplete="off"
          maxLength={NAME_MAX_LENGTH}
          onChange={(event) => setName(event.target.value)}
        />
        <p className="text-meta text-fg-muted">{t('admin.recording.ask.nameHint')}</p>
      </div>
      {offered && (
        <Checkbox className="mt-4" checked={idChecked} onCheckedChange={setIdChecked}>
          {t('admin.recording.ask.idChecked')}
        </Checkbox>
      )}
      {idCheck === 'required' && (
        <p className="mt-2 text-meta text-fg-muted">{t('admin.recording.ask.idRequired')}</p>
      )}
    </QuestionDialog>
  );
}

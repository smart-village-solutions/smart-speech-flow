import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  ConsentKind,
  PolicyLevel,
  RecordingAsk,
  StaffRelease,
} from '@/domain/recording/recordingSession.types';
import { RichText } from '@/ui/patterns/RichText';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { TextField } from '@/ui/primitives/TextField';
import { NAME_MAX_LENGTH } from './consentLimits';

interface RecordingRequestDialogProps {
  /** The policy's ID check; null when unknown, which offers none. */
  idCheck: PolicyLevel | null;
  kind: ConsentKind;
  staffRelease: StaffRelease | null;
  error: string | null;
  sending: boolean;
  onSubmit: (ask: RecordingAsk) => void;
  onCancel: () => void;
}

/** Each section's employee release, with the name and ID check on a first request. */
export function RecordingRequestDialog({
  idCheck,
  kind,
  staffRelease,
  error,
  sending,
  onSubmit,
  onCancel,
}: Readonly<RecordingRequestDialogProps>) {
  const { t, i18n } = useTranslation();
  const [name, setName] = useState('');
  const [idChecked, setIdChecked] = useState(false);
  const first = kind === 'first';
  const offered = first && (idCheck === 'optional' || idCheck === 'required');
  const guestName = name.trim();

  return (
    <QuestionDialog
      open
      title={t('admin.recording.ask.title')}
      choicesLanguage={staffRelease?.language}
      confirmLabel={staffRelease?.acceptLabel ?? t('admin.recording.request')}
      cancelLabel={staffRelease?.declineLabel ?? t('admin.recording.ask.cancel')}
      error={error === null ? null : t(error)}
      confirmDisabled={sending || (first && idCheck === 'required' && !idChecked)}
      onConfirm={() =>
        onSubmit({
          ...(first && guestName !== '' ? { guestName } : {}),
          ...(staffRelease === null ? {} : { staffReleaseSha256: staffRelease.sha256 }),
          ...(offered ? { idChecked } : {}),
        })
      }
      onCancel={onCancel}
    >
      <p className="mt-2 text-note leading-chat text-fg-muted">{t('admin.recording.ask.body')}</p>
      {staffRelease !== null &&
        staffRelease.language.split('-')[0] !== i18n.language.split('-')[0] && (
          <p className="mt-2 text-note text-fg-muted">
            {t('recording.consent.originalLanguage', { language: staffRelease.language })}
          </p>
        )}
      {staffRelease !== null && (
        <div
          lang={staffRelease.language}
          className="mt-4 flex flex-col gap-3 text-note leading-chat"
        >
          <RichText html={staffRelease.html} />
        </div>
      )}
      {first && (
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
      )}
      {offered && (
        <Checkbox className="mt-4" checked={idChecked} onCheckedChange={setIdChecked}>
          {t('admin.recording.ask.idChecked')}
        </Checkbox>
      )}
      {first && idCheck === 'required' && (
        <p className="mt-2 text-meta text-fg-muted">{t('admin.recording.ask.idRequired')}</p>
      )}
    </QuestionDialog>
  );
}

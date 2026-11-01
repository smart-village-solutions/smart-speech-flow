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
import { RequestIdentityFields } from './RequestIdentityFields';

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
  const { t } = useTranslation();
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
      <StaffReleaseContent release={staffRelease} />
      {first && (
        <RequestIdentityFields
          idCheck={idCheck}
          name={name}
          idChecked={idChecked}
          onNameChange={setName}
          onIdCheckedChange={setIdChecked}
        />
      )}
    </QuestionDialog>
  );
}

/** The employee reviews the served language, with source fallback identified visibly. */
function StaffReleaseContent({ release }: Readonly<{ release: StaffRelease | null }>) {
  const { t, i18n } = useTranslation();
  if (release === null) return null;
  const sourceLanguage = release.language.split('-')[0] !== i18n.language.split('-')[0];
  return (
    <>
      {sourceLanguage && (
        <p className="mt-2 text-note text-fg-muted">
          {t('recording.consent.originalLanguage', { language: release.language })}
        </p>
      )}
      <div lang={release.language} className="mt-4 flex flex-col gap-3 text-note leading-chat">
        <RichText html={release.html} />
      </div>
    </>
  );
}

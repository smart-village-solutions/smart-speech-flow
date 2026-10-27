import { useTranslation } from 'react-i18next';
import type { RecordingRequest } from '@/domain/recording/recordingSession.types';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';

interface GuestRecordingQuestionProps {
  /** The open question, or null when none is asked. */
  request: RecordingRequest | null;
  /** The last answer could not be delivered; the question stays open. */
  failed: boolean;
  onAnswer: (consent: boolean) => void;
}

/**
 * The employee's request, put to the guest. Any way out but "yes" answers no.
 * Phase 3C of #615 replaces the body with the server's consent text.
 */
export function GuestRecordingQuestion({
  request,
  failed,
  onAnswer,
}: Readonly<GuestRecordingQuestionProps>) {
  const { t } = useTranslation();
  const resume = request?.consentKind === 'resume';

  return (
    <ConfirmDialog
      open={request !== null}
      title={t(resume ? 'recording.ask.resumeTitle' : 'recording.ask.title')}
      body={t(resume ? 'recording.ask.resumeBody' : 'recording.ask.body')}
      confirmLabel={t('recording.ask.yes')}
      cancelLabel={t('recording.ask.no')}
      error={failed ? t('recording.error') : null}
      onConfirm={() => onAnswer(true)}
      onCancel={() => onAnswer(false)}
    />
  );
}

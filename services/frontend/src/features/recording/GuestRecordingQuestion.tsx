import { useTranslation } from 'react-i18next';
import type {
  ConsentEvidence,
  ConsentText,
  RecordingRequest,
} from '@/domain/recording/recordingSession.types';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';
import { ConsentBody, type ReadAloud } from './ConsentBody';
import { DocumentationConsentChoice } from './DocumentationConsentChoice';
import { useGuestConsentForm } from './useGuestConsentForm';
import { GuestConsentForm } from './GuestConsentForm';

interface GuestRecordingQuestionProps {
  /** The open question, or null when none is asked. */
  request: RecordingRequest | null;
  /** Its text as served, once it has arrived, with the hash of that very string. */
  consent: { text: ConsentText; hash: string } | null;
  textFailed: boolean;
  voice: ReadAloud;
  /** The i18n key of the last answer's refusal; the question stays open. */
  error: string | null;
  onAnswer: (consent: boolean, evidence?: ConsentEvidence) => void;
}

/**
 * The employee's request, put to the guest with the gateway's consent text
 * (spec §6). Any way out but "yes" answers no. Keyed by the request, so a new
 * question starts with a fresh form.
 */
export function GuestRecordingQuestion({
  request,
  consent,
  textFailed,
  voice,
  error,
  onAnswer,
}: Readonly<GuestRecordingQuestionProps>) {
  const { t } = useTranslation();
  const text = consent?.text ?? null;
  const form = useGuestConsentForm(consent, onAnswer);
  const resume = request?.consentKind === 'resume';
  const shown = form.blocked ?? error;

  return (
    <QuestionDialog
      open={request !== null}
      title={t(resume ? 'recording.ask.resumeTitle' : 'recording.ask.title')}
      choicesLanguage={text?.language}
      confirmLabel={text?.acceptLabel ?? t('recording.ask.yes')}
      cancelLabel={text?.declineLabel ?? t('recording.ask.no')}
      error={shown === null ? null : t(shown)}
      confirmDisabled={consent === null || !form.documentationAccepted}
      onConfirm={form.confirm}
      onCancel={() => onAnswer(false)}
    >
      <ConsentBody text={text} failed={textFailed} voice={voice} />
      <DocumentationConsentChoice
        text={text}
        accepted={form.documentationAccepted}
        onAccept={form.acceptDocumentation}
        onDecline={() => onAnswer(false)}
      />
      {text?.consentKind === 'first' && (
        <GuestConsentForm
          values={form.values}
          proposed={text.proposedName !== null}
          signature={text.signature}
          onChange={form.edit}
        />
      )}
    </QuestionDialog>
  );
}

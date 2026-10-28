import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  ConsentEvidence,
  ConsentText,
  RecordingRequest,
} from '@/domain/recording/recordingSession.types';
import { QuestionDialog } from '@/ui/patterns/QuestionDialog';
import { ConsentBody, type ReadAloud } from './ConsentBody';
import { GuestConsentForm, type ConsentFormValues } from './GuestConsentForm';

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

/** The checks the gateway makes too, made first so a guest never waits to learn them. */
function missing(values: ConsentFormValues, text: ConsentText): string | null {
  if (text.consentKind === 'resume') return null;
  if (values.name.trim() === '') return 'recording.consent.nameRequired';
  const unsigned = values.signaturePng === null && !values.cannotSign;
  return text.signature === 'required' && unsigned ? 'recording.consent.signatureRequired' : null;
}

function evidenceOf(values: ConsentFormValues, text: ConsentText, hash: string): ConsentEvidence {
  if (text.consentKind === 'resume') return { textSha256: hash };
  return {
    textSha256: hash,
    name: values.name.trim(),
    ...(values.signaturePng === null ? {} : { signaturePng: values.signaturePng }),
    ...(values.cannotSign ? { cannotSign: true } : {}),
  };
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
  const [edited, setEdited] = useState<ConsentFormValues | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const resume = request?.consentKind === 'resume';
  const text = consent?.text ?? null;
  const values = edited ?? {
    name: text?.proposedName ?? '',
    signaturePng: null,
    cannotSign: false,
  };

  const confirm = () => {
    if (consent === null) return;
    const reason = missing(values, consent.text);
    setBlocked(reason);
    if (reason === null) onAnswer(true, evidenceOf(values, consent.text, consent.hash));
  };

  const shown = blocked ?? error;

  return (
    <QuestionDialog
      open={request !== null}
      title={t(resume ? 'recording.ask.resumeTitle' : 'recording.ask.title')}
      confirmLabel={t('recording.ask.yes')}
      cancelLabel={t('recording.ask.no')}
      error={shown === null ? null : t(shown)}
      confirmDisabled={consent === null}
      onConfirm={confirm}
      onCancel={() => onAnswer(false)}
    >
      <ConsentBody text={text} failed={textFailed} voice={voice} />
      {text?.consentKind === 'first' && (
        <GuestConsentForm
          values={values}
          proposed={text.proposedName !== null}
          signature={text.signature}
          onChange={(next) => {
            setEdited(next);
            setBlocked(null);
          }}
        />
      )}
    </QuestionDialog>
  );
}

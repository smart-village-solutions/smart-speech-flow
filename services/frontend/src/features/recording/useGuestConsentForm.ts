import { useState } from 'react';
import type { ConsentEvidence, ConsentText } from '@/domain/recording/recordingSession.types';
import type { ConsentFormValues } from './GuestConsentForm';

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

/** Keeps form edits and documentation consent bound to the displayed text version. */
export function useGuestConsentForm(
  consent: { text: ConsentText; hash: string } | null,
  onAnswer: (consent: boolean, evidence?: ConsentEvidence) => void
) {
  const [edited, setEdited] = useState<ConsentFormValues | null>(null);
  const [acceptedHash, setAcceptedHash] = useState<string | null>(null);
  const [blocked, setBlocked] = useState<string | null>(null);
  const text = consent?.text ?? null;
  const values = edited ?? {
    name: text?.proposedName ?? '',
    signaturePng: null,
    cannotSign: false,
  };
  const documentationAccepted =
    text?.documentationConsent == null || (consent !== null && acceptedHash === consent.hash);

  const confirm = () => {
    if (consent === null || !documentationAccepted) return;
    const reason = missing(values, consent.text);
    setBlocked(reason);
    if (reason !== null) return;
    const evidence = evidenceOf(values, consent.text, consent.hash);
    if (consent.text.documentationConsent != null) evidence.documentationConsent = true;
    onAnswer(true, evidence);
  };
  const edit = (next: ConsentFormValues) => {
    setEdited(next);
    setBlocked(null);
  };
  const acceptDocumentation = (accepted: boolean) => {
    setAcceptedHash(accepted ? (consent?.hash ?? null) : null);
  };
  return { values, blocked, documentationAccepted, confirm, edit, acceptDocumentation };
}

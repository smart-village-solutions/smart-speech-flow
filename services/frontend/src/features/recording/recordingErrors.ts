import { AppError } from '@/core/http/AppError';

const ADMIN_CODES = new Set([
  'GUEST_NOT_CONNECTED',
  'RECORDING_DISABLED',
  'RECOVERY_KEY_MISSING',
  'RECORDING_POLICY_UNAVAILABLE',
  'RECORDING_BUSY',
  'ARCHIVE_UNAVAILABLE',
  'ARCHIVE_WRITE_FAILED',
  'ID_CHECK_REQUIRED',
  'STAFF_RELEASE_TEXT_MISMATCH',
]);

/** A refused yes the guest can act on; anything else is the generic message. */
const GUEST_ANSWER_KEYS: Readonly<Record<string, string>> = {
  CONSENT_TEXT_MISMATCH: 'recording.consent.textChanged',
  DOCUMENTATION_CONSENT_REQUIRED: 'recording.consent.documentationRequired',
  STAFF_RELEASE_TEXT_MISMATCH: 'recording.consent.staffReleaseChanged',
  NAME_REQUIRED: 'recording.consent.nameRequired',
  SIGNATURE_REQUIRED: 'recording.consent.signatureRequired',
  INVALID_SIGNATURE: 'recording.consent.signatureRequired',
};

export const TEXT_CHANGED_KEY = GUEST_ANSWER_KEYS.CONSENT_TEXT_MISMATCH;

/** The admin's message for a gateway recording code; unknown codes get the generic one. */
export function adminRecordingCodeKey(code: string | undefined): string {
  return code !== undefined && ADMIN_CODES.has(code)
    ? `admin.recording.error.${code}`
    : 'admin.recording.error.generic';
}

/** The admin's message for a refused recording change, by the gateway's code. */
export function adminRecordingErrorKey(error: unknown): string {
  return adminRecordingCodeKey(error instanceof AppError ? error.serverCode : undefined);
}

/** The guest's message for a refused answer, by the gateway's code. */
export function guestAnswerErrorKey(error: unknown): string {
  const code = error instanceof AppError ? error.serverCode : undefined;
  return (code !== undefined && GUEST_ANSWER_KEYS[code]) || 'recording.error';
}

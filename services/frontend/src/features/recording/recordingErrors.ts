import { AppError } from '@/core/http/AppError';

const ADMIN_CODES = new Set([
  'GUEST_NOT_CONNECTED',
  'RECORDING_DISABLED',
  'RECOVERY_KEY_MISSING',
  'RECORDING_POLICY_UNAVAILABLE',
  'RECORDING_BUSY',
]);

/** The admin's message for a refused recording change, by the gateway's code. */
export function adminRecordingErrorKey(error: unknown): string {
  const code = error instanceof AppError ? error.serverCode : undefined;
  return code !== undefined && ADMIN_CODES.has(code)
    ? `admin.recording.error.${code}`
    : 'admin.recording.error.generic';
}

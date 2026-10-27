import { AppError } from '@/core/http/AppError';

const ADMIN_CODES = new Set([
  'GUEST_NOT_CONNECTED',
  'RECORDING_DISABLED',
  'RECOVERY_KEY_MISSING',
  'RECORDING_POLICY_UNAVAILABLE',
  'RECORDING_BUSY',
  'ARCHIVE_UNAVAILABLE',
  'ARCHIVE_WRITE_FAILED',
]);

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

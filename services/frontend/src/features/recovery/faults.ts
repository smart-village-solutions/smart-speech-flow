const CHECKS = new Set([
  'self_approval',
  'not_listed',
  'request_signature',
  'out_of_scope',
  'wrap_signature',
  'share_mismatch',
  'trust',
  'step_up',
  'fingerprint_changed',
]);
const REFUSALS = new Set([
  'REQUEST_EXISTS',
  'ALREADY_ACCESSIBLE',
  'KEY_NOT_ENROLLED',
  'CONVERSATION_NOT_FOUND',
  'RECOVERY_KEY_MISSING',
  'SIGNATURE_INVALID',
  'REQUESTER_CANNOT_APPROVE',
  'ALREADY_DECIDED',
  'REQUEST_CLOSED',
  'NOT_ENOUGH_APPROVALS',
  'SCOPE_NOT_COVERED',
  'SCOPE_TOO_LARGE',
]);

/** The message for a step's failure: a check of ours, a known refusal, or "unavailable". */
export function faultKey(fault: string): string {
  const code = fault.startsWith('refused.') ? fault.slice('refused.'.length) : null;
  if (code !== null && REFUSALS.has(code)) return `admin.recovery.error.${code}`;
  if (CHECKS.has(fault)) return `admin.recovery.fault.${fault}`;
  return 'admin.recovery.fault.unavailable';
}

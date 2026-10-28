import { z } from 'zod';
import type {
  AdminRecordingView,
  ConsentText,
  RecordingRequest,
  RecordingStatus,
  RecordingView,
} from './recordingSession.types';

const phase = z.enum(['off', 'asking', 'arming', 'on', 'paused']);
const consentKind = z.enum(['first', 'resume']);
const policyLevel = z.enum(['off', 'optional', 'required']);
const since = z
  .string()
  .nullable()
  .transform((value) => (value === null ? null : Date.parse(value)))
  .refine((value) => value === null || Number.isFinite(value), 'expected an ISO time');

const status = z.object({
  state: phase,
  reason: z.string().nullable(),
  window_id: z.string().nullable(),
  state_version: z.number().int().nonnegative(),
  since,
});

const request = z.object({ request_id: z.string().min(1), consent_kind: consentKind });

const view = status.extend({
  request_id: z.string().min(1).optional(),
  consent_kind: consentKind.optional(),
});

const adminView = view.extend({
  can_request: z.boolean(),
  unavailable_reason: z.string().nullable(),
  next_consent_kind: consentKind,
  id_check: policyLevel.nullable(),
});

const consentText = z.object({
  request_id: z.string().min(1),
  consent_kind: consentKind,
  language: z.string().min(1),
  html: z.string().min(1),
  signature: policyLevel,
  proposed_name: z.string().nullable(),
});

function toStatus(parsed: z.infer<typeof status>): RecordingStatus {
  return {
    phase: parsed.state,
    reason: parsed.reason,
    windowId: parsed.window_id,
    stateVersion: parsed.state_version,
    since: parsed.since,
  };
}

function toView(parsed: z.infer<typeof view>): RecordingView {
  const { request_id: requestId, consent_kind: consentKind } = parsed;
  const open = parsed.state === 'asking' && requestId !== undefined && consentKind !== undefined;
  return {
    status: toStatus(parsed),
    request: open ? { requestId, consentKind } : null,
  };
}

/** A `recording_state` frame or a route's body; null for anything malformed. */
export function toRecordingStatus(raw: unknown): RecordingStatus | null {
  const parsed = status.safeParse(raw);
  return parsed.success ? toStatus(parsed.data) : null;
}

/** A `recording_request` frame; null for anything malformed. */
export function toRecordingRequest(raw: unknown): RecordingRequest | null {
  const parsed = request.safeParse(raw);
  return parsed.success
    ? { requestId: parsed.data.request_id, consentKind: parsed.data.consent_kind }
    : null;
}

/** Each throws on a body it cannot use; callers treat that like any failed request. */
export function toRecordingView(body: unknown): RecordingView {
  return toView(view.parse(body));
}

export function toAdminRecordingView(body: unknown): AdminRecordingView {
  const parsed = adminView.parse(body);
  return {
    ...toView(parsed),
    canRequest: parsed.can_request,
    unavailableReason: parsed.unavailable_reason,
    nextConsentKind: parsed.next_consent_kind,
    idCheck: parsed.id_check,
  };
}

export function toConsentText(body: unknown): ConsentText {
  const parsed = consentText.parse(body);
  return {
    requestId: parsed.request_id,
    consentKind: parsed.consent_kind,
    language: parsed.language,
    html: parsed.html,
    signature: parsed.signature,
    proposedName: parsed.proposed_name,
  };
}

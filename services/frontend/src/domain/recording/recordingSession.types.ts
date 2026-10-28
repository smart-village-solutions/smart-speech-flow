/** The phases of spec §5.1, as the gateway sends them. */
export type RecordingPhase = 'off' | 'asking' | 'arming' | 'on' | 'paused';

export type ConsentKind = 'first' | 'resume';

/** How a tenant's policy asks for a signature or an ID check (spec §14). */
export type PolicyLevel = 'off' | 'optional' | 'required';

/** What a screen reports of a clip it played (spec §7.1). */
export type PlaybackEvent = 'started' | 'completed';

/** One `recording_state`: what both screens render and acknowledge. */
export interface RecordingStatus {
  phase: RecordingPhase;
  reason: string | null;
  windowId: string | null;
  stateVersion: number;
  /** When this phase began, in epoch ms. */
  since: number | null;
}

/** The open question a guest answers. */
export interface RecordingRequest {
  requestId: string;
  consentKind: ConsentKind;
}

export interface RecordingView {
  status: RecordingStatus;
  request: RecordingRequest | null;
}

export interface AdminRecordingView extends RecordingView {
  canRequest: boolean;
  /** The gateway's code when the employee may not ask now. */
  unavailableReason: string | null;
  /** A first request may carry the guest's name and the ID check; a resume carries neither. */
  nextConsentKind: ConsentKind;
  /** The policy's ID check, known only while the employee may ask. */
  idCheck: PolicyLevel | null;
}

/** What the employee adds to a first request (spec §6). */
export interface RecordingAsk {
  guestName?: string;
  idChecked?: boolean;
}

/** The open question's text, exactly as the gateway serves it (spec §6). */
export interface ConsentText {
  requestId: string;
  consentKind: ConsentKind;
  language: string;
  /** Sanitised by the gateway; its SHA-256 is what a yes carries. */
  html: string;
  /** Off for a resume. */
  signature: PolicyLevel;
  /** The employee's spelling of the guest's name, for the guest to confirm. */
  proposedName: string | null;
}

/** What a yes carries: the hash of the text shown, and on a first yes the name and signature. */
export interface ConsentEvidence {
  textSha256: string;
  name?: string;
  /** Base64 of the drawn PNG. */
  signaturePng?: string;
  /** The guest confirmed by tapping instead of signing. */
  cannotSign?: boolean;
}

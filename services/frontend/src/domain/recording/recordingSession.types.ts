/** The phases of spec §5.1, as the gateway sends them. */
export type RecordingPhase = 'off' | 'asking' | 'arming' | 'on' | 'paused';

export type ConsentKind = 'first' | 'resume';

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
}

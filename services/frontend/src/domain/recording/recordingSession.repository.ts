import type { AxiosInstance } from 'axios';
import type { ClientRole } from '@/core/roles';
import {
  toAdminRecordingView,
  toConsentText,
  toRecordingStatus,
  toRecordingView,
} from './recordingSession.mapper';
import type {
  AdminRecordingView,
  ConsentEvidence,
  ConsentText,
  PlaybackEvent,
  RecordingAsk,
  RecordingStatus,
  RecordingView,
} from './recordingSession.types';

/**
 * Recording a live conversation (spec §5.2). Every change answers with the
 * state it led to; the same state also arrives as a `recording_state` frame.
 */
export interface RecordingSessionRepository {
  adminView(sessionId: string): Promise<AdminRecordingView>;
  guestView(sessionId: string): Promise<RecordingView>;
  request(sessionId: string, requestId: string, ask?: RecordingAsk): Promise<RecordingStatus>;
  cancel(sessionId: string, requestId: string): Promise<RecordingStatus>;
  /** A yes needs `evidence`; a no is sent without any. */
  answer(
    sessionId: string,
    requestId: string,
    consent: boolean,
    evidence?: ConsentEvidence
  ): Promise<RecordingStatus>;
  /** The open question's text in the guest's language. */
  consentText(sessionId: string): Promise<ConsentText>;
  /** Where that text is read aloud; a clip URL for the playback queue, one per text. */
  consentAudioUrl(sessionId: string, requestId: string, textSha256: string): string;
  stop(sessionId: string, role: ClientRole): Promise<RecordingStatus>;
  /** A clip this screen played; archived only if its message was (spec §7.1). */
  reportPlayback(
    sessionId: string,
    role: ClientRole,
    messageId: string,
    event: PlaybackEvent
  ): Promise<void>;
}

const base = (role: ClientRole, sessionId: string) =>
  `/api/${role}/session/${encodeURIComponent(sessionId)}/recording`;

function status(body: unknown): RecordingStatus {
  const parsed = toRecordingStatus(body);
  if (parsed === null) {
    throw new TypeError('Unexpected recording state');
  }
  return parsed;
}

function evidenceBody(evidence: ConsentEvidence): Record<string, unknown> {
  return {
    text_sha256: evidence.textSha256,
    ...(evidence.name === undefined ? {} : { name: evidence.name }),
    ...(evidence.signaturePng === undefined ? {} : { signature_png: evidence.signaturePng }),
    ...(evidence.cannotSign === undefined ? {} : { cannot_sign: evidence.cannotSign }),
  };
}

export function createRecordingSessionRepository(http: AxiosInstance): RecordingSessionRepository {
  return {
    async adminView(sessionId) {
      const response = await http.get<unknown>(base('admin', sessionId));
      return toAdminRecordingView(response.data);
    },

    async guestView(sessionId) {
      const response = await http.get<unknown>(base('customer', sessionId));
      return toRecordingView(response.data);
    },

    async request(sessionId, requestId, ask = {}) {
      const response = await http.post<unknown>(`${base('admin', sessionId)}/request`, {
        request_id: requestId,
        ...(ask.guestName === undefined ? {} : { guest_name: ask.guestName }),
        ...(ask.idChecked === undefined ? {} : { id_checked: ask.idChecked }),
      });
      return status(response.data);
    },

    async cancel(sessionId, requestId) {
      const response = await http.post<unknown>(`${base('admin', sessionId)}/cancel`, {
        request_id: requestId,
      });
      return status(response.data);
    },

    async answer(sessionId, requestId, consent, evidence) {
      const response = await http.post<unknown>(`${base('customer', sessionId)}/answer`, {
        request_id: requestId,
        consent,
        ...(evidence === undefined ? {} : evidenceBody(evidence)),
      });
      return status(response.data);
    },

    async consentText(sessionId) {
      const response = await http.get<unknown>(`${base('customer', sessionId)}/consent`);
      return toConsentText(response.data);
    },

    consentAudioUrl(sessionId, requestId, textSha256) {
      const query = new URLSearchParams({ request_id: requestId, text_sha256: textSha256 });
      return `${base('customer', sessionId)}/consent/audio?${query.toString()}`;
    },

    async stop(sessionId, role) {
      const response = await http.post<unknown>(`${base(role, sessionId)}/stop`);
      return status(response.data);
    },

    async reportPlayback(sessionId, role, messageId, event) {
      await http.post(`${base(role, sessionId)}/playback`, { message_id: messageId, event });
    },
  };
}

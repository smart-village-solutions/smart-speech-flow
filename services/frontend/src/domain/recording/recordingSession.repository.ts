import type { AxiosInstance } from 'axios';
import type { ClientRole } from '@/core/roles';
import {
  toAdminRecordingView,
  toRecordingStatus,
  toRecordingView,
} from './recordingSession.mapper';
import type {
  AdminRecordingView,
  PlaybackEvent,
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
  request(sessionId: string, requestId: string): Promise<RecordingStatus>;
  cancel(sessionId: string, requestId: string): Promise<RecordingStatus>;
  answer(sessionId: string, requestId: string, consent: boolean): Promise<RecordingStatus>;
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

    async request(sessionId, requestId) {
      const response = await http.post<unknown>(`${base('admin', sessionId)}/request`, {
        request_id: requestId,
      });
      return status(response.data);
    },

    async cancel(sessionId, requestId) {
      const response = await http.post<unknown>(`${base('admin', sessionId)}/cancel`, {
        request_id: requestId,
      });
      return status(response.data);
    },

    async answer(sessionId, requestId, consent) {
      const response = await http.post<unknown>(`${base('customer', sessionId)}/answer`, {
        request_id: requestId,
        consent,
      });
      return status(response.data);
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

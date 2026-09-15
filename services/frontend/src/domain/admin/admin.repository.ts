import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import { toAdminSessions, toCreatedSession } from './admin.mapper';
import type { SessionCreateDto, SessionHistoryDto } from './admin.mapper';
import type { AdminSession, CreatedSession } from './admin.types';

export type RealtimeTransportKind = 'websocket' | 'polling';

interface RealtimeTicketDto {
  ticket: string;
  expires_at: string;
}

export interface AdminRepository {
  createSession(): Promise<CreatedSession>;
  listSessions(limit: number): Promise<AdminSession[]>;
  terminateSession(sessionId: string): Promise<void>;
  issueRealtimeTicket(sessionId: string, transport: RealtimeTransportKind): Promise<string>;
}

export function createAdminRepository(http: AxiosInstance): AdminRepository {
  return {
    async createSession() {
      const response = await http.post<SessionCreateDto>('/api/admin/session/create');
      return toCreatedSession(response.data);
    },

    async listSessions(limit) {
      const response = await http.get<SessionHistoryDto>('/api/admin/session/history', {
        params: { limit },
      });
      return toAdminSessions(response.data);
    },

    async terminateSession(sessionId) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      // 200 with `already_terminated` is also success: the caller wanted the
      // session ended and it is.
      await http.delete(`/api/admin/session/${safeId}/terminate`);
    },

    async issueRealtimeTicket(sessionId, transport) {
      const safeId = requirePathIdentifier(sessionId, 'session');
      const response = await http.post<RealtimeTicketDto>(
        `/api/admin/session/${safeId}/realtime-ticket`,
        { transport }
      );
      return response.data.ticket;
    },
  };
}

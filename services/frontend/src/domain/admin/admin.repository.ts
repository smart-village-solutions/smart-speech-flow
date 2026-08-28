import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import { toAdminSessions, toCreatedSession } from './admin.mapper';
import type { SessionCreateDto, SessionHistoryDto } from './admin.mapper';
import type { AdminSession, CreatedSession } from './admin.types';

/**
 * `/api/admin/*` carries no authentication of any kind on the gateway, so there
 * is nothing to attach here.
 */
export interface AdminRepository {
  createSession(): Promise<CreatedSession>;
  listSessions(limit: number): Promise<AdminSession[]>;
  terminateSession(sessionId: string): Promise<void>;
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
  };
}

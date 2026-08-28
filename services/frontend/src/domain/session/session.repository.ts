import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import type { ClientRole } from '@/core/roles';
import { activationToSession, toSession } from './session.mapper';
import type { ActivateSessionDto, SessionInfoDto } from './session.mapper';
import type { Session } from './session.types';

export interface SessionRepository {
  getSession(id: string): Promise<Session>;
  activate(id: string, languageCode: string): Promise<Session>;
  reportActivity(id: string, role: ClientRole): Promise<void>;
}

export function createSessionRepository(http: AxiosInstance): SessionRepository {
  return {
    async getSession(id) {
      const safeId = requirePathIdentifier(id, 'session');
      const response = await http.get<SessionInfoDto>(`/api/session/${safeId}`);
      return toSession(response.data);
    },

    async activate(id, languageCode) {
      const safeId = requirePathIdentifier(id, 'session');
      const response = await http.post<ActivateSessionDto>('/api/customer/session/activate', {
        session_id: safeId,
        customer_language: languageCode,
      });
      return activationToSession(response.data);
    },

    async reportActivity(id, role) {
      const safeId = requirePathIdentifier(id, 'session');
      await http.post(`/api/session/${safeId}/activity`, { client_type: role });
    },
  };
}

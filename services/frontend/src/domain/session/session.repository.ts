import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import type { ClientRole } from '@/core/roles';
import { activationToSession, toSession } from './session.mapper';
import type { ActivateSessionDto, SessionInfoDto } from './session.mapper';
import type { Session } from './session.types';

export interface SessionRepository {
  getSession(id: string, role: ClientRole): Promise<Session>;
  activate(id: string, languageCode: string): Promise<Session>;
}

const sessionPathForRole = (role: ClientRole, sessionId: string): string =>
  role === 'admin'
    ? `/api/admin/session/${sessionId}/status`
    : `/api/customer/session/${sessionId}`;

export function createSessionRepository(http: AxiosInstance): SessionRepository {
  return {
    async getSession(id, role) {
      const safeId = requirePathIdentifier(id, 'session');
      const response = await http.get<SessionInfoDto>(sessionPathForRole(role, safeId));
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
  };
}

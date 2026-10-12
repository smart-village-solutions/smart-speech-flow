import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import { randomGuestToken } from '@/core/ids';
import type { ClientRole } from '@/core/roles';
import type { GuestTokenStore } from '@/core/http/guest-token.port';
import { activationToSession, statusToSession } from './session.mapper';
import type { ActivateSessionDto, SessionStatusDto } from './session.mapper';
import type { Session } from './session.types';

export interface SessionRepository {
  getSession(id: string, role: ClientRole): Promise<Session>;
  activate(
    id: string,
    languageCode: string,
    dataRetentionConsent: boolean
  ): Promise<Session>;
  /** A one-time ticket for the guest's socket; the session must be active. */
  issueGuestTicket(id: string): Promise<string>;
}

const sessionPathForRole = (role: ClientRole, sessionId: string): string =>
  role === 'admin'
    ? `/api/admin/session/${sessionId}/status`
    : `/api/customer/session/${sessionId}`;

export function createSessionRepository(
  http: AxiosInstance,
  guestTokens: GuestTokenStore
): SessionRepository {
  return {
    async getSession(id, role) {
      const safeId = requirePathIdentifier(id, 'session');
      const response = await http.get<SessionStatusDto>(sessionPathForRole(role, safeId));
      return statusToSession(response.data);
    },

    async activate(id, languageCode, dataRetentionConsent) {
      const safeId = requirePathIdentifier(id, 'session');
      // Chosen and kept before asking: if the answer is lost, the retry carries
      // the same token and the gateway admits it.
      const token = guestTokens.read(safeId) ?? randomGuestToken();
      if (token) {
        guestTokens.save(safeId, token);
      }
      const response = await http.post<ActivateSessionDto>(
        '/api/customer/session/activate',
        {
          session_id: safeId,
          customer_language: languageCode,
          data_retention_consent: dataRetentionConsent,
        },
        { headers: token ? { 'X-Guest-Token': token } : {} }
      );
      const issued = response.data.guest_token;
      if (issued && issued !== token) {
        guestTokens.save(safeId, issued);
      }
      return activationToSession(response.data);
    },

    async issueGuestTicket(id) {
      const safeId = requirePathIdentifier(id, 'session');
      const response = await http.post<{ ticket: string }>(
        `/api/customer/session/${safeId}/realtime-ticket`
      );
      return response.data.ticket;
    },
  };
}

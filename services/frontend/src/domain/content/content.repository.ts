import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import {
  toGuestContent,
  toGuestLanguages,
  toPublicContent,
  toStaffContent,
} from './content.mapper';
import type { ContentSource } from './content.port';

/**
 * Guest routes take the session id as their key, like the other customer
 * routes; the HTTP client adds the staff token to /api/admin requests only.
 */
export function createContentRepository(http: AxiosInstance): ContentSource {
  const guestPath = (sessionId: string) =>
    `/api/customer/session/${requirePathIdentifier(sessionId, 'session')}`;

  return {
    async getPublic() {
      const response = await http.get<unknown>('/api/content/installation');
      return toPublicContent(response.data);
    },

    async getGuestLanguages(sessionId) {
      const response = await http.get<unknown>(`${guestPath(sessionId)}/languages`);
      return toGuestLanguages(response.data);
    },

    async getGuest(sessionId, language) {
      const safeLanguage = requirePathIdentifier(language, 'language');
      const response = await http.get<unknown>(`${guestPath(sessionId)}/content/${safeLanguage}`);
      return toGuestContent(response.data);
    },

    async getStaff() {
      const response = await http.get<unknown>('/api/admin/content');
      return toStaffContent(response.data);
    },
  };
}

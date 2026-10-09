import type { AxiosInstance } from 'axios';
import { requirePathIdentifier } from '@/utils/identifiers';
import {
  toGuestContent,
  toGuestLanguages,
  toPublicContent,
  toStaffContent,
} from './content.mapper';
import type { ContentReadOptions, ContentSource } from './content.port';

/**
 * The installation route allows 60 s of browser caching. A request carrying its
 * own Cache-Control bypasses the HTTP cache (Fetch spec); the gateway's CORS
 * policy allows the header.
 */
const readOptions = (options?: ContentReadOptions) =>
  options?.fresh ? { headers: { 'Cache-Control': 'no-cache' } } : undefined;

/**
 * Guest routes take the session id as their key, like the other customer
 * routes; the HTTP client adds the staff token to /api/admin requests only.
 */
export function createContentRepository(http: AxiosInstance): ContentSource {
  const guestPath = (sessionId: string) =>
    `/api/customer/session/${requirePathIdentifier(sessionId, 'session')}`;

  return {
    async getPublic(options) {
      const response = await http.get<unknown>('/api/content/installation', readOptions(options));
      return toPublicContent(response.data);
    },

    async getGuestLanguages(sessionId) {
      const response = await http.get<unknown>(`${guestPath(sessionId)}/languages`);
      return toGuestLanguages(response.data);
    },

    async getGuest(sessionId, language, options) {
      const safeLanguage = requirePathIdentifier(language, 'language');
      const response = await http.get<unknown>(
        `${guestPath(sessionId)}/content/${safeLanguage}`,
        readOptions(options)
      );
      return toGuestContent(response.data);
    },

    async getStaff(options) {
      const response = await http.get<unknown>('/api/admin/content', readOptions(options));
      return toStaffContent(response.data);
    },
  };
}

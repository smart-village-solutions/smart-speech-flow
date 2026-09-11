import axios, { type AxiosInstance } from 'axios';
import type { AppConfig } from '@/app/config/env';
import { randomId } from '@/core/ids';
import { toAppError } from './AppError';
import { getAdminAccessToken } from '@/app/auth/keycloak';

/**
 * No default Content-Type is set on purpose: axios infers application/json for
 * plain objects and generates the multipart boundary for FormData. Forcing a
 * default here would break multipart audio uploads.
 */
export function createHttpClient(config: AppConfig, getLocale: () => string): AxiosInstance {
  const client = axios.create({
    baseURL: config.apiBaseUrl,
    timeout: config.requestTimeoutMs,
  });

  client.interceptors.request.use(async (request) => {
    request.headers.set('X-Correlation-Id', randomId());
    request.headers.set('Accept-Language', getLocale());
    const requestUrl = request.url;
    const isRelativeAdmin = requestUrl?.startsWith('/api/admin/') === true;
    let isTrustedAbsoluteAdmin = false;
    if (requestUrl && config.apiBaseUrl) {
      try {
        const apiOrigin = new URL(config.apiBaseUrl).origin;
        const target = new URL(requestUrl, config.apiBaseUrl);
        isTrustedAbsoluteAdmin =
          target.origin === apiOrigin && target.pathname.startsWith('/api/admin/');
      } catch {
        isTrustedAbsoluteAdmin = false;
      }
    }
    if (isRelativeAdmin || isTrustedAbsoluteAdmin) {
      const token = await getAdminAccessToken();
      if (token !== null) {
        request.headers.set('Authorization', `Bearer ${token}`);
      }
    }
    return request;
  });

  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => Promise.reject(toAppError(error))
  );

  return client;
}

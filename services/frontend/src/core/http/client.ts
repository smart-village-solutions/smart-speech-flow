import axios, { type AxiosInstance } from 'axios';
import type { AppConfig } from '@/app/config/env';
import { randomId } from '@/core/ids';
import { toAppError } from './AppError';
import { getAdminAccessToken } from '@/app/auth/keycloak';
import type { GuestTokenStore } from './guest-token.port';

const NO_GUEST_TOKEN: GuestTokenStore = { read: () => null, save: () => undefined };

/** Whether a request goes to `prefix` on the gateway itself, never to another origin. */
function targetsApiPath(requestUrl: string | undefined, apiBaseUrl: string, prefix: string): boolean {
  if (requestUrl === undefined) return false;
  if (requestUrl.startsWith(prefix)) return true;
  if (!apiBaseUrl) return false;
  try {
    const target = new URL(requestUrl, apiBaseUrl);
    return target.origin === new URL(apiBaseUrl).origin && target.pathname.startsWith(prefix);
  } catch {
    return false;
  }
}

/**
 * No default Content-Type is set on purpose: axios infers application/json for
 * plain objects and generates the multipart boundary for FormData. Forcing a
 * default here would break multipart audio uploads.
 *
 * `guestTokens` is the guest's credential for its one session; clients that
 * never act as a guest leave it out.
 */
export function createHttpClient(
  config: AppConfig,
  getLocale: () => string,
  guestTokens: GuestTokenStore = NO_GUEST_TOKEN
): AxiosInstance {
  const client = axios.create({
    baseURL: config.apiBaseUrl,
    timeout: config.requestTimeoutMs,
  });

  client.interceptors.request.use(async (request) => {
    request.headers.set('X-Correlation-Id', randomId());
    request.headers.set('Accept-Language', getLocale());
    if (targetsApiPath(request.url, config.apiBaseUrl, '/api/admin/')) {
      const token = await getAdminAccessToken();
      if (token !== null) {
        request.headers.set('Authorization', `Bearer ${token}`);
      }
    }
    const guestToken = guestTokens.read();
    if (guestToken !== null && targetsApiPath(request.url, config.apiBaseUrl, '/api/customer/')) {
      request.headers.set('X-Guest-Token', guestToken);
    }
    return request;
  });

  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => Promise.reject(toAppError(error))
  );

  return client;
}

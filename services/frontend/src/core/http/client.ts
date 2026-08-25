import axios, { type AxiosInstance } from 'axios';
import type { AppConfig } from '@/app/config/env';
import { toAppError } from './AppError';

/**
 * No default Content-Type is set on purpose: axios infers application/json for
 * plain objects and generates the multipart boundary for FormData. Forcing a
 * default here would break audio uploads to POST /api/session/{id}/message.
 */
export function createHttpClient(config: AppConfig, getLocale: () => string): AxiosInstance {
  const client = axios.create({
    baseURL: config.apiBaseUrl,
    timeout: config.requestTimeoutMs,
  });

  client.interceptors.request.use((request) => {
    request.headers.set('X-Correlation-Id', crypto.randomUUID());
    request.headers.set('Accept-Language', getLocale());
    return request;
  });

  client.interceptors.response.use(
    (response) => response,
    (error: unknown) => Promise.reject(toAppError(error))
  );

  return client;
}

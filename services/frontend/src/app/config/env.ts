import { z } from 'zod';

export type BrandId = 'ssf' | 'kassel';

const envSchema = z.object({
  /** Empty in development: the Vite proxy forwards /api to the gateway. */
  VITE_API_BASE_URL: z.string().default(''),
  /** Empty means "derive from window.location". */
  VITE_WS_BASE_URL: z.string().default(''),
  VITE_BRAND: z.enum(['ssf', 'kassel']).default('ssf'),
  VITE_KEYCLOAK_URL: z.string().url().default('https://auth.kassel.smartspeechflow.de'),
  VITE_KEYCLOAK_REALM: z.string().min(1).default('ssf'),
  VITE_KEYCLOAK_CLIENT_ID: z.string().min(1).default('ssf-frontend'),
  VITE_APP_PASSWORD: z.string().default('ssf2025kassel'),
  /**
   * Temporary legacy `/admin` password. `z.string()` with a default, not a
   * required value: a build that forgets it must fall back rather than fail to
   * start.
   *
   * This is not a secret. Vite inlines it into the bundle at build time, so
   * anyone who opens the JavaScript can read it. It is a speed bump during the
   * Keycloak migration, not a security control.
   */
  VITE_REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().default(30_000),
  /** The message endpoint runs ASR, translation and TTS synchronously. */
  VITE_PIPELINE_TIMEOUT_MS: z.coerce.number().int().positive().default(120_000),
});

export interface AppConfig {
  apiBaseUrl: string;
  wsBaseUrl: string;
  brand: BrandId;
  keycloakUrl: string;
  keycloakRealm: string;
  keycloakClientId: string;
  adminPassword: string;
  requestTimeoutMs: number;
  pipelineTimeoutMs: number;
}

function defaultWsBaseUrl(): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${window.location.host}`;
}

export function readConfig(source: Record<string, unknown> = import.meta.env): AppConfig {
  const parsed = envSchema.safeParse(source);

  if (!parsed.success) {
    throw new Error(`Invalid environment configuration: ${parsed.error.message}`);
  }

  const env = parsed.data;

  return {
    apiBaseUrl: env.VITE_API_BASE_URL,
    wsBaseUrl: env.VITE_WS_BASE_URL || defaultWsBaseUrl(),
    brand: env.VITE_BRAND,
    keycloakUrl: env.VITE_KEYCLOAK_URL,
    keycloakRealm: env.VITE_KEYCLOAK_REALM,
    keycloakClientId: env.VITE_KEYCLOAK_CLIENT_ID,
    adminPassword: env.VITE_APP_PASSWORD,
    requestTimeoutMs: env.VITE_REQUEST_TIMEOUT_MS,
    pipelineTimeoutMs: env.VITE_PIPELINE_TIMEOUT_MS,
  };
}

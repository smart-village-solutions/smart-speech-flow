import { z } from 'zod';

export type BrandId = 'ssf' | 'kassel';

const envSchema = z.object({
  /** Empty in development: the Vite proxy forwards /api to the gateway. */
  VITE_API_BASE_URL: z.string().default(''),
  /** Empty means "derive from window.location". */
  VITE_WS_BASE_URL: z.string().default(''),
  VITE_BRAND: z.enum(['ssf', 'kassel']).default('ssf'),
  /**
   * The admin bypass. Only the literal 'true' enables it: a typo must leave the
   * bypass off rather than throw, so a malformed value can never take the app
   * down and can never accidentally open the door.
   */
  VITE_ADMIN_DEV_ENTRY: z
    .string()
    .default('false')
    .transform((value) => value === 'true'),
  /**
   * The interim admin password, shared with the legacy `/legacy` chooser so the
   * product has one rather than two. `z.string()` with a default, not a required
   * value: a build that forgets it must fall back rather than fail to start.
   *
   * This is not a secret. Vite inlines it into the bundle at build time, so
   * anyone who opens the JavaScript can read it, and `/api/admin/*` accepts
   * unauthenticated requests regardless. It is a speed bump until Keycloak.
   */
  VITE_APP_PASSWORD: z.string().default('ssf2025kassel'),
  VITE_REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().default(30_000),
  /** The message endpoint runs ASR, translation and TTS synchronously. */
  VITE_PIPELINE_TIMEOUT_MS: z.coerce.number().int().positive().default(120_000),
});

export interface AppConfig {
  apiBaseUrl: string;
  wsBaseUrl: string;
  brand: BrandId;
  adminDevEntry: boolean;
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
    adminDevEntry: env.VITE_ADMIN_DEV_ENTRY,
    adminPassword: env.VITE_APP_PASSWORD,
    requestTimeoutMs: env.VITE_REQUEST_TIMEOUT_MS,
    pipelineTimeoutMs: env.VITE_PIPELINE_TIMEOUT_MS,
  };
}

type PolicyMode = 'enforce' | 'report-only';

export class ReleaseConfigError extends Error {}

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

function isLocal(hostname: string): boolean {
  return LOCAL_HOSTS.has(hostname) || hostname.endsWith('.localhost');
}

function parse(raw: string): URL | undefined {
  try {
    return new URL(raw);
  } catch {
    return undefined;
  }
}

/** An image build refuses what would send a tablet anywhere but a real host. */
export function originOf(
  value: string | undefined,
  schemes: readonly string[],
  strict: boolean
): string | undefined {
  const raw = value?.trim() ?? '';
  const url = raw === '' ? undefined : parse(raw);
  if (!strict) return url && url.origin !== 'null' ? url.origin : undefined;
  if (!url) throw new ReleaseConfigError(`an image build needs a valid URL, not "${raw}"`);
  if (!schemes.includes(url.protocol)) {
    throw new ReleaseConfigError(`${raw} must use ${schemes.join(' or ')}`);
  }
  if (isLocal(url.hostname)) throw new ReleaseConfigError(`${raw} names a local host`);
  return url.origin;
}

export function contentSecurityPolicy({
  api,
  ws,
  keycloak,
}: {
  api?: string;
  ws?: string;
  keycloak?: string;
}): string {
  const connect = [...new Set([api, ws, keycloak].filter((origin) => origin !== undefined))];
  const directives = [
    ['default-src', "'none'"],
    ['script-src', "'self'", "'wasm-unsafe-eval'"],
    ['style-src', "'self'", "'unsafe-inline'"],
    ['img-src', "'self'", 'data:', 'blob:'],
    ['font-src', "'self'"],
    // blob: because the Web Audio player fetch()es the clip's object URL.
    ['connect-src', "'self'", 'blob:', ...connect],
    ['media-src', "'self'", 'blob:'],
    ['frame-src', keycloak ?? "'none'"],
    ['worker-src', "'none'"],
    ['manifest-src', "'self'"],
    ['form-action', "'self'"],
    ['frame-ancestors', "'none'"],
    ['base-uri', "'none'"],
    ['object-src', "'none'"],
  ];
  return directives.map((parts) => parts.join(' ')).join('; ');
}

export function parsePolicyMode(value: string | undefined): PolicyMode {
  if (value === undefined || value === '' || value === 'report-only') return 'report-only';
  if (value === 'enforce') return 'enforce';
  throw new ReleaseConfigError(`SSF_CSP_MODE must be enforce or report-only, not "${value}"`);
}

export function policyHeaderName(mode: PolicyMode): string {
  return mode === 'enforce' ? 'Content-Security-Policy' : 'Content-Security-Policy-Report-Only';
}

/** Included at server level and in every nginx location that sets its own add_header. */
export function nginxSecurityHeaders(policy: string, mode: PolicyMode): string {
  if (/["$\\\r\n]/.test(policy)) throw new ReleaseConfigError('the policy contains nginx syntax');
  return [
    `add_header ${policyHeaderName(mode)} "${policy}" always;`,
    'add_header X-Frame-Options "DENY" always;',
    'add_header X-Content-Type-Options "nosniff" always;',
    'add_header X-XSS-Protection "1; mode=block" always;',
    '',
  ].join('\n');
}

/** The policy for the build values in env: strict for an image, lenient for a local preview. */
export function securityHeaders(
  env: Readonly<Record<string, string | undefined>>,
  strict: boolean
): { name: string; policy: string; include: string } {
  const mode = parsePolicyMode(env.SSF_CSP_MODE);
  const policy = contentSecurityPolicy({
    api: originOf(env.VITE_API_BASE_URL, ['https:'], strict),
    ws: originOf(env.VITE_WS_BASE_URL, ['wss:'], strict),
    keycloak: originOf(env.VITE_KEYCLOAK_URL, ['https:'], strict),
  });
  return { name: policyHeaderName(mode), policy, include: nginxSecurityHeaders(policy, mode) };
}

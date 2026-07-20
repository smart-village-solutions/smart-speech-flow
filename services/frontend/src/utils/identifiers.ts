const SESSION_ID_PATTERN = /^[A-Z0-9]{8}$/;
const POLLING_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

export type PathIdentifierKind = 'session' | 'polling';

/** Validates identifiers before they become URL path segments. */
export function validatePathIdentifier(value: string, kind: PathIdentifierKind): boolean {
  const pattern = kind === 'session' ? SESSION_ID_PATTERN : POLLING_ID_PATTERN;
  return pattern.test(value);
}

export function requirePathIdentifier(value: string, kind: PathIdentifierKind): string {
  if (!validatePathIdentifier(value, kind)) {
    throw new Error(`Invalid ${kind} identifier`);
  }

  return encodeURIComponent(value);
}

export function sessionPath(sessionId: string): string {
  return `/api/session/${requirePathIdentifier(sessionId, 'session')}`;
}

export function buildWebSocketUrl(baseUrl: string, sessionId: string, clientType: 'admin' | 'customer'): string {
  const base = new URL(baseUrl);
  if (base.protocol !== 'ws:' && base.protocol !== 'wss:') {
    throw new Error('WebSocket base URL must use ws or wss');
  }

  const basePath = base.pathname.replace(/\/$/, '');
  base.pathname = `${basePath}/ws/${requirePathIdentifier(sessionId, 'session')}/${clientType}`;
  base.search = '';
  base.hash = '';
  return base.toString();
}

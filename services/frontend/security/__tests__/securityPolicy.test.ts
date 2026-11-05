import { describe, expect, it } from 'vitest';
import {
  ReleaseConfigError,
  contentSecurityPolicy,
  nginxSecurityHeaders,
  originOf,
  parsePolicyMode,
  policyHeaderName,
  securityHeaders,
} from '../securityPolicy.ts';

const plainHttp = (host: string) => `${'http'}://${host}`;

const PRODUCTION_POLICY =
  "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; font-src 'self'; " +
  "connect-src 'self' blob: https://api.dialog.kassel.de wss://api.dialog.kassel.de https://auth.dialog.kassel.de; " +
  "media-src 'self' blob:; frame-src https://auth.dialog.kassel.de; worker-src 'none'; manifest-src 'self'; " +
  "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'";

const PRODUCTION_ENV = {
  VITE_API_BASE_URL: 'https://api.dialog.kassel.de',
  VITE_WS_BASE_URL: 'wss://api.dialog.kassel.de',
  VITE_KEYCLOAK_URL: 'https://auth.dialog.kassel.de',
};

describe('originOf', () => {
  it('reduces a URL to its origin', () => {
    expect(originOf('https://auth.example.test/realms/x/', ['https:'], true)).toBe('https://auth.example.test');
    expect(originOf('wss://api.example.test/ws', ['wss:'], true)).toBe('wss://api.example.test');
  });

  it.each(['', '   ', undefined])('rejects a missing value in an image build (%s)', (value) => {
    expect(() => originOf(value, ['https:'], true)).toThrow(ReleaseConfigError);
  });

  it('rejects the wrong scheme in an image build', () => {
    expect(() => originOf(plainHttp('api.example.test'), ['https:'], true)).toThrow(ReleaseConfigError);
  });

  it.each(['https://localhost', 'https://127.0.0.1:8443', 'https://[::1]', 'https://auth.localhost'])(
    'rejects the local host %s in an image build',
    (value) => {
      expect(() => originOf(value, ['https:'], true)).toThrow(ReleaseConfigError);
    }
  );

  it('accepts or skips anything in a local preview', () => {
    expect(originOf('', ['https:'], false)).toBeUndefined();
    expect(originOf('not a url', ['https:'], false)).toBeUndefined();
    expect(originOf(plainHttp('localhost:8000'), ['https:'], false)).toBe(plainHttp('localhost:8000'));
  });
});

describe('contentSecurityPolicy', () => {
  it('is the policy of spec §4 for the production origins', () => {
    expect(
      contentSecurityPolicy({
        api: 'https://api.dialog.kassel.de',
        ws: 'wss://api.dialog.kassel.de',
        keycloak: 'https://auth.dialog.kassel.de',
      })
    ).toBe(PRODUCTION_POLICY);
  });

  it('allows only same-origin and object-URL connections and no frame without origins', () => {
    const policy = contentSecurityPolicy({});
    expect(policy).toContain("connect-src 'self' blob:;");
    expect(policy).toContain("frame-src 'none';");
  });
});

describe('policy mode', () => {
  it('reports only unless told to enforce, so no build enforces by accident', () => {
    expect(parsePolicyMode(undefined)).toBe('report-only');
    expect(parsePolicyMode('')).toBe('report-only');
    expect(parsePolicyMode('report-only')).toBe('report-only');
    expect(parsePolicyMode('enforce')).toBe('enforce');
    expect(() => parsePolicyMode('off')).toThrow(ReleaseConfigError);
  });

  it('names the header', () => {
    expect(policyHeaderName('enforce')).toBe('Content-Security-Policy');
    expect(policyHeaderName('report-only')).toBe('Content-Security-Policy-Report-Only');
  });
});

describe('nginxSecurityHeaders', () => {
  it('sends the policy and the framing, sniffing and XSS headers on every response', () => {
    expect(nginxSecurityHeaders("default-src 'none'", 'report-only')).toBe(
      [
        `add_header Content-Security-Policy-Report-Only "default-src 'none'" always;`,
        'add_header X-Frame-Options "DENY" always;',
        'add_header X-Content-Type-Options "nosniff" always;',
        'add_header X-XSS-Protection "1; mode=block" always;',
        '',
      ].join('\n')
    );
  });

  it('refuses a value nginx would read as syntax', () => {
    expect(() => nginxSecurityHeaders('default-src "x"', 'enforce')).toThrow(ReleaseConfigError);
    expect(() => nginxSecurityHeaders('default-src $x', 'enforce')).toThrow(ReleaseConfigError);
  });
});

describe('securityHeaders', () => {
  it('builds the production header from the build values', () => {
    const headers = securityHeaders({ ...PRODUCTION_ENV, SSF_CSP_MODE: 'report-only' }, true);

    expect(headers.name).toBe('Content-Security-Policy-Report-Only');
    expect(headers.policy).toBe(PRODUCTION_POLICY);
    expect(headers.include).toBe(nginxSecurityHeaders(PRODUCTION_POLICY, 'report-only'));
  });

  it('refuses an image without a Keycloak origin', () => {
    expect(() => securityHeaders({ ...PRODUCTION_ENV, VITE_KEYCLOAK_URL: '' }, true)).toThrow(ReleaseConfigError);
  });

  it('lets a local preview run with whatever is set', () => {
    expect(securityHeaders({}, false).policy).toContain("connect-src 'self' blob:;");
  });
});

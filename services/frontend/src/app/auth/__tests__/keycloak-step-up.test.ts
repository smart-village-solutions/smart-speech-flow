import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readConfig } from '@/app/config/env';

const { clients } = vi.hoisted(() => ({
  clients: [] as Array<{
    authenticated: boolean;
    tokenParsed?: Record<string, unknown>;
    login: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock('keycloak-js', () => ({
  default: class {
    authenticated = true;
    token = 'access-token';
    loginRequired = true;
    tokenParsed: Record<string, unknown> | undefined;
    init = vi.fn().mockResolvedValue(true);
    login = vi.fn().mockResolvedValue(undefined);
    clearToken = vi.fn();

    constructor() {
      clients.push(this);
    }
  },
}));

const config = readConfig({ VITE_KEYCLOAK_URL: 'https://auth.dialog.kassel.de' });
const kassel = { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' };
const NOW = 1_800_000_000;

describe('step-up login', () => {
  beforeEach(() => {
    vi.resetModules();
    clients.length = 0;
  });

  it.each([
    ['a fresh MFA login', { acr: 'mfa', auth_time: NOW - 60 }, true],
    ['an MFA login older than four minutes', { acr: 'mfa', auth_time: NOW - 241 }, false],
    ['a password-only login', { acr: '1', auth_time: NOW - 5 }, false],
    ['no auth_time', { acr: 'mfa' }, false],
  ])('treats %s accordingly', async (_reason, claims, fresh) => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    clients[0].tokenParsed = claims;
    expect(auth.hasFreshStepUp(NOW)).toBe(fresh);
  });

  it.each([
    ['a login 100 s ago', { acr: 'mfa', auth_time: NOW - 100 }, 200, true],
    ['a login 301 s ago', { acr: 'mfa', auth_time: NOW - 301 }, -1, false],
    ['a password-only login', { acr: '1', auth_time: NOW - 5 }, -Infinity, false],
  ])('counts what the gateway still accepts of %s', async (_reason, claims, left, accepted) => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    clients[0].tokenParsed = claims;
    expect(auth.stepUpSecondsLeft(NOW)).toBe(left);
    expect(auth.hasAcceptedStepUp(NOW)).toBe(accepted);
  });

  it('asks Keycloak for MFA with no reuse of the old login, returning to the tenant page', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    await auth.requestStepUp();
    expect(clients[0].login).toHaveBeenCalledWith({
      acrValues: 'mfa',
      maxAge: 0,
      redirectUri: `${globalThis.location.origin}/login/tenant-kassel`,
    });
  });

  it('names the key owner from the verified session', async () => {
    const auth = await import('../keycloak');
    expect(auth.getAdminIdentity()).toBeNull();
    await auth.requireKeycloakLogin(config, kassel);
    clients[0].tokenParsed = { sub: 'alice' };
    expect(auth.getAdminIdentity()).toEqual({ tenantId: 'tenant-kassel', userSub: 'alice' });
  });
});

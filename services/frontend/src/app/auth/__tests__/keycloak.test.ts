import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readConfig } from '@/app/config/env';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/setup';

const { construct, clients } = vi.hoisted(() => ({
  construct: vi.fn(),
  clients: [] as Array<{
    authenticated: boolean;
    token?: string;
    realmAccess?: { roles?: string[] };
    loginRequired: boolean;
    init: ReturnType<typeof vi.fn>;
    updateToken: ReturnType<typeof vi.fn>;
    clearToken: ReturnType<typeof vi.fn>;
    logout: ReturnType<typeof vi.fn>;
    createAccountUrl: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock('keycloak-js', () => ({
  default: class {
    authenticated = true;
    token: string | undefined = 'access-token';
    loginRequired = true;
    init = vi.fn().mockResolvedValue(true);
    updateToken = vi.fn().mockResolvedValue(true);
    clearToken = vi.fn(() => {
      this.authenticated = false;
      this.token = '';
    });
    logout = vi.fn().mockResolvedValue(undefined);
    createAccountUrl: ReturnType<typeof vi.fn>;

    constructor(options: { realm: string }) {
      construct(options);
      this.createAccountUrl = vi.fn(
        ({ redirectUri }: { redirectUri: string }) => `console:${options.realm}->${redirectUri}`
      );
      clients.push(this);
    }
  },
}));

const config = readConfig({ VITE_KEYCLOAK_URL: 'https://auth.dialog.kassel.de' });
const kassel = { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' };
const fulda = { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' };

describe('tenant Keycloak session', () => {
  beforeEach(() => {
    vi.resetModules();
    construct.mockClear();
    clients.length = 0;
  });

  it('uses the directory realm and exact tenant callback with PKCE S256', async () => {
    const auth = await import('../keycloak');
    expect(await auth.requireKeycloakLogin(config, kassel)).toBe(true);
    expect(construct).toHaveBeenCalledWith({
      url: 'https://auth.dialog.kassel.de',
      realm: 'kassel-ssf-2025',
      clientId: 'ssf-frontend',
    });
    expect(clients[0].init).toHaveBeenCalledWith({
      onLoad: 'login-required',
      pkceMethod: 'S256',
      redirectUri: `${globalThis.location.origin}/login/tenant-kassel`,
    });
  });

  it('returns the Studio URL only when the signed-in user is a system administrator', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, {
      ...kassel,
      studioUrl: 'https://smartcity.dialog.kassel.de/',
    });

    expect(auth.getStudioUrlForSystemAdmin()).toBeNull();
    clients[0].realmAccess = { roles: ['ssf-user', 'system_admin'] };
    expect(auth.getStudioUrlForSystemAdmin()).toBe('https://smartcity.dialog.kassel.de/');
  });

  it('offers no account console before a tenant session is authenticated', async () => {
    const auth = await import('../keycloak');
    expect(auth.getAccountConsoleUrl()).toBeNull();

    const pending = auth.requireKeycloakLogin(config, kassel);
    expect(auth.getAccountConsoleUrl()).toBeNull();
    await pending;
    clients[0].authenticated = false;
    expect(auth.getAccountConsoleUrl()).toBeNull();
  });

  it('asks the tenant client for its account console with a return to the callback', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, { ...kassel, id: 'tenant:kassel' });

    const callback = `${globalThis.location.origin}/login/tenant%3Akassel`;
    expect(auth.getAccountConsoleUrl()).toBe(`console:kassel-ssf-2025->${callback}`);
    expect(clients[0].createAccountUrl).toHaveBeenCalledWith({ redirectUri: callback });
  });

  it('follows the tenant when the session switches realms', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    await auth.requireKeycloakLogin(config, fulda);
    expect(auth.getAccountConsoleUrl()).toBe(
      `console:fulda-ssf-2025->${globalThis.location.origin}/login/tenant-fulda`
    );

    await auth.logoutFromKeycloak();
    expect(auth.getAccountConsoleUrl()).toBeNull();
  });

  it('shares initialization for repeated concurrent calls', async () => {
    const auth = await import('../keycloak');
    const first = auth.requireKeycloakLogin(config, kassel);
    clients[0].authenticated = false;
    const second = auth.requireKeycloakLogin(config, kassel);
    expect(await first).toBe(true);
    expect(await second).toBe(true);
    expect(construct).toHaveBeenCalledTimes(1);
    expect(clients[0].init).toHaveBeenCalledTimes(1);
  });

  it('clears the previous tenant without redirecting back to its realm', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    await auth.requireKeycloakLogin(config, fulda);
    expect(clients[0].loginRequired).toBe(false);
    expect(clients[0].clearToken).toHaveBeenCalledOnce();
    expect(construct).toHaveBeenLastCalledWith({
      url: 'https://auth.dialog.kassel.de',
      realm: 'fulda-ssf-2025',
      clientId: 'ssf-frontend',
    });
    clients[1].token = 'fulda-token';
    expect(await auth.getAdminAccessToken()).toBe('fulda-token');
  });

  it('replaces the client if the directory remaps the same tenant', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    await auth.requireKeycloakLogin(config, { ...kassel, realm: 'new-kassel' });
    expect(construct).toHaveBeenCalledTimes(2);
    expect(clients[0].clearToken).toHaveBeenCalledOnce();
  });

  it('encodes the tenant ID in the callback and never persists tokens', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, { ...kassel, id: 'tenant:kassel' });
    expect(clients[0].init).toHaveBeenCalledWith(
      expect.objectContaining({
        redirectUri: `${globalThis.location.origin}/login/tenant%3Akassel`,
      })
    );
    await auth.getAdminAccessToken();
    expect(storage).not.toHaveBeenCalled();
    storage.mockRestore();
  });

  it('refreshes before returning a token and clears failed refreshes', async () => {
    const auth = await import('../keycloak');
    const onExpired = vi.fn();
    const unsubscribe = auth.subscribeToKeycloakExpiration(onExpired);
    expect(await auth.getAdminAccessToken()).toBeNull();
    await auth.requireKeycloakLogin(config, kassel);
    clients[0].updateToken.mockImplementation(async () => {
      clients[0].token = 'fresh';
    });
    expect(await auth.getAdminAccessToken()).toBe('fresh');
    expect(clients[0].updateToken).toHaveBeenCalledWith(30);
    clients[0].updateToken.mockRejectedValue(new Error('expired'));
    await expect(auth.getAdminAccessToken()).rejects.toThrow('Keycloak session expired');
    expect(onExpired).toHaveBeenCalledOnce();
    unsubscribe();
    expect(clients[0].clearToken).toHaveBeenCalledOnce();
    expect(await auth.requireKeycloakLogin(config, kassel)).toBe(true);
    expect(construct).toHaveBeenCalledTimes(2);
    expect(await auth.getAdminAccessToken()).toBe('access-token');
  });

  it('never sends legacy credentials after a refresh failure', async () => {
    const auth = await import('../keycloak');
    const { createHttpClient } = await import('@/core/http/client');
    await auth.requireKeycloakLogin(config, kassel);
    clients[0].updateToken.mockRejectedValue(new Error('expired'));
    let requests = 0;
    server.use(
      http.get('*/api/admin/probe', () => {
        requests += 1;
        return HttpResponse.json({ ok: true });
      })
    );
    const client = createHttpClient(config, () => 'en');
    await expect(client.get('/api/admin/probe')).rejects.toThrow();
    await expect(client.get('/api/admin/probe')).rejects.toThrow();
    expect(requests).toBe(0);
  });

  it('never returns a token from a tenant replaced during refresh', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    let finish!: () => void;
    clients[0].updateToken.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        })
    );
    const pending = auth.getAdminAccessToken();
    await auth.requireKeycloakLogin(config, fulda);
    finish();
    await expect(pending).rejects.toThrow('Keycloak session changed');
  });

  it('logs out to the chooser and discards the in-memory token', async () => {
    const auth = await import('../keycloak');
    await auth.requireKeycloakLogin(config, kassel);
    await auth.logoutFromKeycloak();
    expect(clients[0].logout).toHaveBeenCalledWith({
      redirectUri: `${globalThis.location.origin}/login`,
    });
    expect(await auth.getAdminAccessToken()).toBeNull();
  });
});

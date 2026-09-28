import Keycloak from 'keycloak-js';
import type { AppConfig } from '@/app/config/env';
import type { LoginTenant } from '@/domain/login-tenant/loginTenant.types';

interface ActiveKeycloakSession {
  tenantId: string;
  realm: string;
  studioUrl?: string;
  client: Keycloak;
  initialized: boolean;
  initialization: Promise<boolean> | null;
}

let active: ActiveKeycloakSession | null = null;
let expired = false;
const expirationListeners = new Set<() => void>();
const authorizationListeners = new Set<() => void>();

export function subscribeToKeycloakAuthorization(listener: () => void): () => void {
  authorizationListeners.add(listener);
  return () => {
    authorizationListeners.delete(listener);
  };
}

function notifyAuthorizationChanged(): void {
  for (const listener of authorizationListeners) listener();
}

export function subscribeToKeycloakExpiration(listener: () => void): () => void {
  expirationListeners.add(listener);
  return () => {
    expirationListeners.delete(listener);
  };
}

function expireSession(session: ActiveKeycloakSession): void {
  clearSession(session);
  if (active === session) {
    active = null;
    expired = true;
    for (const listener of expirationListeners) listener();
  }
}

function clearSession(session: ActiveKeycloakSession): void {
  // clearToken otherwise starts another login when init used login-required.
  session.client.loginRequired = false;
  session.client.clearToken();
  notifyAuthorizationChanged();
}

function tenantCallback(tenantId: string): string {
  return `${window.location.origin}/login/${encodeURIComponent(tenantId)}`;
}

export async function requireKeycloakLogin(
  config: AppConfig,
  tenant: LoginTenant
): Promise<boolean> {
  if (active?.tenantId !== tenant.id || active?.realm !== tenant.realm) {
    if (active !== null) clearSession(active);
    active = {
      tenantId: tenant.id,
      realm: tenant.realm,
      studioUrl: tenant.studioUrl,
      client: new Keycloak({
        url: config.keycloakUrl,
        realm: tenant.realm,
        clientId: config.keycloakClientId,
      }),
      initialized: false,
      initialization: null,
    };
  } else {
    active.studioUrl = tenant.studioUrl;
  }
  const session = active;
  session.client.onAuthRefreshSuccess = () => {
    if (active === session) notifyAuthorizationChanged();
  };
  if (session.initialized) return session.client.authenticated === true;
  session.initialization ??= session.client.init({
    onLoad: 'login-required',
    pkceMethod: 'S256',
    redirectUri: tenantCallback(tenant.id),
  });
  try {
    const authenticated = await session.initialization;
    if (active !== session) {
      clearSession(session);
      return false;
    }
    session.initialized = true;
    expired = false;
    notifyAuthorizationChanged();
    return authenticated;
  } catch (error) {
    clearSession(session);
    if (active === session) active = null;
    throw error;
  }
}

function authenticatedSession(): ActiveKeycloakSession | null {
  if (active === null || !active.initialized || active.client.authenticated !== true) {
    return null;
  }
  return active;
}

/** Navigation hint only; Studio enforces its own authorization on arrival. */
export function getStudioAdministrationUrl(tenantId: string): string | null {
  const session = authenticatedSession();
  if (session === null || session.tenantId !== tenantId) return null;
  const claims = session.client.tokenParsed;
  const permissions: unknown = claims?.ssf_permissions;
  return claims?.studio_tenant_id === tenantId &&
    Array.isArray(permissions) &&
    permissions.every((permission: unknown) => typeof permission === 'string') &&
    permissions.includes('ssf.configuration.tenant.manage')
    ? (session.studioUrl ?? null)
    : null;
}

/**
 * Keycloak's own account console, where users change their email and password.
 * Its back link returns to the tenant callback, which the client already allows.
 */
export function getAccountConsoleUrl(): string | null {
  const session = authenticatedSession();
  if (session === null) return null;
  return session.client.createAccountUrl({ redirectUri: tenantCallback(session.tenantId) });
}

export async function getAdminAccessToken(): Promise<string | null> {
  const session = active;
  if (session === null) {
    if (expired) throw new Error('Keycloak session expired');
    return null;
  }
  if (!session.initialized) throw new Error('Keycloak session not ready');
  try {
    if (!session.client.authenticated) throw new Error('Keycloak session expired');
    await session.client.updateToken(30);
  } catch {
    expireSession(session);
    throw new Error('Keycloak session expired');
  }
  if (active !== session) throw new Error('Keycloak session changed');
  if (!session.client.token) {
    expireSession(session);
    throw new Error('Keycloak session expired');
  }
  return session.client.token;
}

export async function logoutFromKeycloak(): Promise<void> {
  const session = active;
  active = null;
  expired = false;
  notifyAuthorizationChanged();
  if (session !== null) {
    try {
      await session.client.logout({ redirectUri: `${window.location.origin}/login` });
    } finally {
      clearSession(session);
    }
  }
}

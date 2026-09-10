import Keycloak from 'keycloak-js';
import type { AppConfig } from '@/app/config/env';
import type { LoginTenant } from '@/domain/login-tenant/loginTenant.types';

interface ActiveKeycloakSession {
  tenantId: string;
  realm: string;
  client: Keycloak;
  initialized: boolean;
  initialization: Promise<boolean> | null;
}

let active: ActiveKeycloakSession | null = null;
let expired = false;
const expirationListeners = new Set<() => void>();

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
}

export async function requireKeycloakLogin(
  config: AppConfig,
  tenant: LoginTenant
): Promise<boolean> {
  if (active === null || active.tenantId !== tenant.id || active.realm !== tenant.realm) {
    if (active !== null) clearSession(active);
    active = {
      tenantId: tenant.id,
      realm: tenant.realm,
      client: new Keycloak({
        url: config.keycloakUrl,
        realm: tenant.realm,
        clientId: config.keycloakClientId,
      }),
      initialized: false,
      initialization: null,
    };
  }
  const session = active;
  if (session.initialized) return session.client.authenticated === true;
  session.initialization ??= session.client.init({
    onLoad: 'login-required',
    pkceMethod: 'S256',
    redirectUri: `${window.location.origin}/login/${encodeURIComponent(tenant.id)}`,
  });
  try {
    const authenticated = await session.initialization;
    if (active !== session) {
      clearSession(session);
      return false;
    }
    session.initialized = true;
    expired = false;
    return authenticated;
  } catch (error) {
    clearSession(session);
    if (active === session) active = null;
    throw error;
  }
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
  if (session !== null) {
    try {
      await session.client.logout({ redirectUri: `${window.location.origin}/login` });
    } finally {
      clearSession(session);
    }
  }
}

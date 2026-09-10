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
    return authenticated;
  } catch (error) {
    clearSession(session);
    if (active === session) active = null;
    throw error;
  }
}

export async function getAdminAccessToken(): Promise<string | null> {
  const session = active;
  if (session === null || !session.client.authenticated) return null;
  try {
    await session.client.updateToken(30);
    return active === session ? (session.client.token ?? null) : null;
  } catch {
    clearSession(session);
    return null;
  }
}

export async function logoutFromKeycloak(): Promise<void> {
  const session = active;
  active = null;
  if (session !== null) {
    try {
      await session.client.logout({ redirectUri: `${window.location.origin}/login` });
    } finally {
      clearSession(session);
    }
  }
}

import Keycloak from 'keycloak-js';
import type { AppConfig } from '@/app/config/env';

let client: Keycloak | null = null;
let initialized = false;

function configured(config: AppConfig): Keycloak {
  if (client === null) {
    client = new Keycloak({
      url: config.keycloakUrl,
      realm: config.keycloakRealm,
      clientId: config.keycloakClientId,
    });
  }
  return client;
}

export async function requireKeycloakLogin(config: AppConfig): Promise<boolean> {
  const keycloak = configured(config);
  if (!initialized) {
    initialized = true;
    return keycloak.init({
      onLoad: 'login-required',
      pkceMethod: 'S256',
      redirectUri: `${window.location.origin}/login`,
    });
  }
  return keycloak.authenticated === true;
}

export async function getAdminAccessToken(): Promise<string | null> {
  if (client === null || !client.authenticated) return null;
  try {
    await client.updateToken(30);
    return client.token ?? null;
  } catch {
    client.clearToken();
    return null;
  }
}

export async function logoutFromKeycloak(): Promise<void> {
  if (client !== null) {
    await client.logout({ redirectUri: window.location.origin });
  }
}

import { describe, expect, it } from 'vitest';
import { readConfig } from '@/app/config/env';

describe('Keycloak configuration', () => {
  it('uses a shared origin and client without a fixed realm', () => {
    const config = readConfig({
      VITE_KEYCLOAK_URL: 'https://auth.dialog.kassel.de/',
      VITE_KEYCLOAK_CLIENT_ID: 'ssf-frontend',
      VITE_KEYCLOAK_REALM: 'untrusted-fixed-realm',
    });
    expect(config.keycloakUrl).toBe('https://auth.dialog.kassel.de');
    expect(config.keycloakClientId).toBe('ssf-frontend');
    expect(config).not.toHaveProperty('keycloakRealm');
  });

  it.each([
    'ftp://auth.test',
    'https://user:pass@auth.test',
    'https://auth.test/realms/ssf',
    'https://auth.test?realm=ssf',
    'https://auth.test#ssf',
    'https://auth.test//',
    'https://auth.test?',
    'https://auth.test#',
    ' https://auth.test',
  ])('rejects a non-origin Keycloak URL: %s', (url) => {
    expect(() => readConfig({ VITE_KEYCLOAK_URL: url })).toThrow('Invalid environment');
  });

  it('allows an HTTP development origin with a port', () => {
    expect(readConfig({ VITE_KEYCLOAK_URL: 'http://localhost:8080/' }).keycloakUrl).toBe(
      'http://localhost:8080'
    );
  });

  it.each(['', '   '])('rejects an empty public client ID: %j', (clientId) => {
    expect(() => readConfig({ VITE_KEYCLOAK_CLIENT_ID: clientId })).toThrow('Invalid environment');
  });
});

describe('the interim admin password', () => {
  it('falls back to the legacy password when none is set', () => {
    expect(readConfig({}).adminPassword).toBe('ssf2025kassel');
  });

  it('takes the password the build supplies', () => {
    expect(readConfig({ VITE_APP_PASSWORD: 'letmein' }).adminPassword).toBe('letmein');
  });
});

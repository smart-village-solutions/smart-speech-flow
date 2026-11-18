import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { readConfig } from '@/app/config/env';
import { requireKeycloakLogin } from '@/app/auth/keycloak';
import { toBase64Url } from '@/core/crypto/bytes';
import { createKeyVault } from '@/core/crypto/key-vault';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';
import { KeysScreen } from '@/features/keys/KeysScreen';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';

const session = vi.hoisted(() => ({
  authenticated: true,
  token: 'valid-access-token',
  tokenParsed: { sub: 'alice' } as Record<string, unknown>,
  init: vi.fn(async () => true),
  updateToken: vi.fn(async () => true),
  login: vi.fn(),
}));
vi.mock('keycloak-js', () => ({
  default: class {
    constructor() {
      return session;
    }
  },
}));

const tenant = { id: 'tenant-kassel', realm: 'kassel', displayName: 'Kassel' };
const owner = { tenantId: tenant.id, userSub: 'alice' };
const phrase = (version: number) => 'local passphrase for version ' + version;

async function sealed(version: number) {
  const { unlocked, blob } = await createWebArchiveCrypto().createKeys(phrase(version), owner);
  const metadata = {
    version,
    state: version === 2 ? 'active' : 'superseded',
    fingerprint: toBase64Url(unlocked.fingerprint),
    encPub: toBase64Url(unlocked.encPub),
    sigPub: toBase64Url(unlocked.sigPub),
    createdAt: '2026-11-18T12:00:00Z',
  };
  return { metadata, blob };
}

describe('personal access keys within the authenticated session', { timeout: 30_000 }, () => {
  let versions: Awaited<ReturnType<typeof sealed>>[];
  beforeAll(async () => {
    versions = [await sealed(1), await sealed(2)];
    await requireKeycloakLogin(readConfig({}), tenant);
  });

  it.each([
    ['password-only', { acr: '1' }, 2],
    ['older MFA', { acr: 'mfa', auth_time: Math.floor(Date.now() / 1000) - 3600 }, 1],
    ['absent optional claims', {}, 1],
  ] as const)(
    'uses only the local passphrase after lock and tab reload with %s',
    async (_label, claims, version) => {
      session.tokenParsed = { sub: owner.userSub, ...claims };
      const routes: string[] = [];
      const list = '*/api/admin/recording/v2/keys/me';
      server.use(
        http.get(list, () =>
          HttpResponse.json({ activeVersion: 2, versions: versions.map((v) => v.metadata) })
        ),
        http.get(list + '/:version', ({ request, params }) => {
          const key = versions[Number(params.version) - 1];
          routes.push(
            request.method + ' ' + request.headers.get('Authorization') + ' ' + params.version
          );
          return HttpResponse.json({ ...key.metadata, blob: key.blob });
        })
      );
      function mount() {
        const keyVault = createKeyVault();
        const view = renderWithProviders(
          <KeysScreen onBack={vi.fn()} onSignOut={vi.fn()} requestedVersion={version} />,
          { locale: 'de', services: { keyVault } }
        );
        return { keyVault, view };
      }
      async function enter(passphrase: string) {
        const field = await screen.findByLabelText('Zugangsschlüssel (Passphrase)');
        await userEvent.clear(field);
        await userEvent.type(field, passphrase);
        await userEvent.click(screen.getByRole('button', { name: 'Entsperren' }));
      }
      const first = mount();
      await enter('incorrect');
      expect(
        await screen.findByText(
          'Diese Passphrase öffnet die Schlüssel nicht.',
          {},
          { timeout: 5000 }
        )
      ).toBeInTheDocument();
      expect(first.keyVault.version(owner, version)).toBeNull();
      await enter(phrase(version));
      await userEvent.click(
        await screen.findByRole('button', { name: 'Sperren' }, { timeout: 5000 })
      );
      expect(first.keyVault.version(owner, version)).toBeNull();
      await enter(phrase(version));
      await screen.findByRole('button', { name: 'Sperren' }, { timeout: 5000 });
      expect(first.keyVault.version(owner, version)?.sigPrivate.extractable).toBe(false);
      first.view.unmount();
      const second = mount();
      expect(second.keyVault.version(owner, version)).toBeNull();
      await enter(phrase(version));
      await screen.findByRole('button', { name: 'Sperren' }, { timeout: 5000 });
      expect(second.keyVault.version(owner, version)?.sigPrivate.extractable).toBe(false);
      expect(session.init).not.toHaveBeenCalled();
      expect(session.login).not.toHaveBeenCalled();
      expect(routes).toEqual(Array(2).fill('GET Bearer valid-access-token ' + version));
    }
  );
});

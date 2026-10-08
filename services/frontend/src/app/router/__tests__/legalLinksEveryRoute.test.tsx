import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { recordRequests } from '@/test/recordRequests';
import { installationBody } from '@/test/contentFixtures';
import { AppRoutes } from '@/app/router/AppRoutes';
import type { Services } from '@/app/providers/services';
import {
  getAccountConsoleUrl,
  getStudioAdministrationUrl,
  requireKeycloakLogin,
} from '@/app/auth/keycloak';

vi.mock('@/app/auth/keycloak', () => ({
  requireKeycloakLogin: vi.fn(),
  logoutFromKeycloak: vi.fn(),
  getStudioAdministrationUrl: vi.fn(),
  getAccountConsoleUrl: vi.fn(),
  getAdminAccessToken: vi.fn().mockResolvedValue('tenant-token'),
  subscribeToKeycloakAuthorization: () => () => undefined,
  subscribeToKeycloakExpiration: () => () => undefined,
}));

const STUDIO_LINKS = [
  installationBody.legal.imprintUrl,
  installationBody.legal.privacyPolicyUrl,
  installationBody.legal.accessibilityStatementUrl,
];

/** Each screen states its own language, so the landmark is named in German or English. */
function legalHrefs(): (string | null)[] {
  const nav = screen.getByRole('navigation', { name: /^(Rechtliches|Legal information)$/ });
  return within(nav)
    .getAllByRole('link')
    .map((link) => link.getAttribute('href'));
}

const failingDirectory: Partial<Services> = {
  loginTenant: { list: () => Promise.reject(new Error('directory down')) },
};

const ROUTES: {
  name: string;
  route: string;
  arrive: () => Promise<unknown>;
  services?: Partial<Services>;
  pendingLogin?: boolean;
}[] = [
  {
    name: 'start page',
    route: '/',
    arrive: () => screen.findByRole('heading', { name: 'Code eingeben' }),
  },
  {
    name: 'login chooser',
    route: '/login',
    arrive: () => screen.findByRole('link', { name: 'Stadt Kassel' }),
  },
  {
    name: 'guest language',
    route: '/s/A1B2C3D4/language',
    arrive: () => screen.findByRole('heading', { name: 'Choose your language' }),
  },
  { name: 'consent', route: '/s/A1B2C3D4/info/en', arrive: () => screen.findByRole('checkbox') },
  {
    name: 'guest conversation',
    route: '/s/A1B2C3D4/live',
    arrive: () => screen.findByRole('button', { name: 'Record' }),
  },
  {
    name: 'admin dashboard',
    route: '/login/tenant-kassel',
    arrive: () => screen.findByRole('button', { name: 'Neues Gespräch starten' }),
  },
  {
    name: 'admin conversation',
    route: '/login/tenant-kassel',
    arrive: async () => {
      await userEvent.click(
        await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
      );
      return screen.findByRole('status');
    },
  },
  { name: 'not found', route: '/nowhere', arrive: () => screen.findByText(/404/) },
  { name: 'unknown tenant', route: '/login/unknown', arrive: () => screen.findByText(/404/) },
  {
    name: 'admin loading',
    route: '/login/tenant-kassel',
    pendingLogin: true,
    arrive: () => waitFor(() => expect(requireKeycloakLogin).toHaveBeenCalled()),
  },
  {
    name: 'admin error',
    route: '/login/tenant-kassel',
    services: failingDirectory,
    arrive: () => screen.findByRole('alert'),
  },
];

describe('legal links on every route', () => {
  beforeEach(() => {
    vi.mocked(requireKeycloakLogin).mockReset().mockResolvedValue(true);
    vi.mocked(getStudioAdministrationUrl).mockReset().mockReturnValue(null);
    vi.mocked(getAccountConsoleUrl).mockReset().mockReturnValue(null);
  });

  it.each(ROUTES)(
    'links the legal pages on the $name',
    async ({ route, arrive, services, pendingLogin }) => {
      if (pendingLogin)
        vi.mocked(requireKeycloakLogin).mockImplementation(() => new Promise(() => {}));
      // The neutral brand bundles no links, so only Studio's can satisfy this.
      renderWithProviders(<AppRoutes />, { route, brand: 'ssf', services });

      await arrive();

      expect(legalHrefs()).toEqual(STUDIO_LINKS);
    }
  );

  it('serves the admin screens the installation content the app already holds', async () => {
    const requests = recordRequests((request) => request.url.endsWith('/api/content/installation'));
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });

    expect(legalHrefs()).toEqual(STUDIO_LINKS);
    expect(requests).toEqual([]);
  });
});

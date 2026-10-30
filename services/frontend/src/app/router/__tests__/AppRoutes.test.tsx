import { http, HttpResponse } from 'msw';
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Link, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AppRoutes } from '@/app/router/AppRoutes';
import {
  getAccountConsoleUrl,
  getAdminIdentity,
  getStudioAdministrationUrl,
  hasPermission,
  requireKeycloakLogin,
  logoutFromKeycloak,
} from '@/app/auth/keycloak';
import type { AdminSession } from '@/domain/admin/admin.types';
import { toBase64Url } from '@/core/crypto/bytes';
import { publicPoint } from '@/core/crypto/curve';
import { KASSEL_REVISION } from '@/test/contentFixtures';
import { feedbackHandler } from '@/test/handlers';
import { recordRequests } from '@/test/recordRequests';
import { server } from '@/test/setup';

const { expirationListeners, authorizationListeners } = vi.hoisted(() => ({
  expirationListeners: new Set<() => void>(),
  authorizationListeners: new Set<() => void>(),
}));

vi.mock('@/app/auth/keycloak', () => ({
  requireKeycloakLogin: vi.fn(),
  logoutFromKeycloak: vi.fn(),
  getStudioAdministrationUrl: vi.fn(),
  hasPermission: vi.fn(),
  getAdminIdentity: vi.fn(),
  hasFreshStepUp: () => false,
  requestStepUp: vi.fn(),
  getAccountConsoleUrl: vi.fn(),
  getAdminAccessToken: vi.fn().mockResolvedValue('tenant-token'),
  subscribeToKeycloakAuthorization: (listener: () => void) => {
    authorizationListeners.add(listener);
    return () => authorizationListeners.delete(listener);
  },
  subscribeToKeycloakExpiration: (listener: () => void) => {
    expirationListeners.add(listener);
    return () => expirationListeners.delete(listener);
  },
}));

const kassel = {
  id: 'tenant-kassel',
  displayName: 'Stadt Kassel',
  realm: 'kassel-ssf-2025',
  studioUrl: 'https://smartcity.dialog.kassel.de/',
};
/** The Authorization header of every request to `path`, until the test ends. */
function recordAuthorization(path: string): (string | null)[] {
  const seen: (string | null)[] = [];
  const listener = ({ request }: { request: Request }) => {
    if (new URL(request.url).pathname === path) seen.push(request.headers.get('Authorization'));
  };
  server.events.on('request:start', listener);
  onTestFinished(() => server.events.removeListener('request:start', listener));
  return seen;
}

function Location() {
  return <output aria-label="Location">{useLocation().pathname}</output>;
}

describe('tenant login routes', () => {
  beforeEach(() => {
    vi.mocked(requireKeycloakLogin).mockReset().mockResolvedValue(true);
    vi.mocked(logoutFromKeycloak).mockReset().mockResolvedValue(undefined);
    vi.mocked(getStudioAdministrationUrl).mockReset().mockReturnValue(null);
    vi.mocked(getAccountConsoleUrl).mockReset().mockReturnValue(null);
    vi.mocked(hasPermission).mockReset().mockReturnValue(false);
    vi.mocked(getAdminIdentity).mockReset().mockReturnValue(null);
    sessionStorage.clear();
  });

  it('shows the chooser without initializing Keycloak', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login' });
    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toHaveAttribute(
      'href',
      '/login/tenant-kassel'
    );
    expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });

  it('resolves the full directory entry and shows the dashboard on the tenant callback', async () => {
    renderWithProviders(
      <>
        <AppRoutes />
        <Location />
      </>,
      { route: '/login/tenant-kassel?realm=evil' }
    );
    expect(
      await screen.findByRole('button', { name: 'Neues Gespräch starten' })
    ).toBeInTheDocument();
    expect(requireKeycloakLogin).toHaveBeenCalledWith(expect.any(Object), kassel);
    expect(screen.getByLabelText('Location')).toHaveTextContent('/login/tenant-kassel');
  });

  it('shows the selected tenant Studio link when the tenant manage permission is available', async () => {
    vi.mocked(getStudioAdministrationUrl).mockReturnValue('https://smartcity.dialog.kassel.de/');
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    expect(screen.getByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })).toHaveAttribute(
      'href',
      'https://smartcity.dialog.kassel.de/'
    );
  });

  it('removes the Studio link when refreshed permissions no longer allow it', async () => {
    vi.mocked(getStudioAdministrationUrl).mockReturnValue('https://smartcity.dialog.kassel.de/');
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    expect(screen.getByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })).toBeInTheDocument();
    vi.mocked(getStudioAdministrationUrl).mockReturnValue(null);
    act(() => { for (const listener of authorizationListeners) listener(); });
    expect(screen.queryByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })).not.toBeInTheDocument();
    expect(getStudioAdministrationUrl).toHaveBeenCalledWith('tenant-kassel');
  });

  it('keeps the Studio link hidden during unresolved authentication', async () => {
    vi.mocked(getStudioAdministrationUrl).mockReturnValue('https://smartcity.dialog.kassel.de/');
    vi.mocked(requireKeycloakLogin).mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });
    await waitFor(() => expect(requireKeycloakLogin).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Benutzerkonto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Organisation verwalten (öffnet in neuem Tab)' })).not.toBeInTheDocument();
  });

  it('links the signed-in tenant user to their Keycloak account console', async () => {
    const accountUrl =
      'https://auth.dialog.kassel.de/realms/kassel-ssf-2025/account?referrer=ssf-frontend';
    vi.mocked(getAccountConsoleUrl).mockReturnValue(accountUrl);
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    expect(screen.getByRole('link', { name: 'Kontoeinstellungen (öffnet in neuem Tab)' })).toHaveAttribute(
      'href',
      accountUrl
    );
  });

  it('keeps the account console link inside a live conversation', async () => {
    const accountUrl =
      'https://auth.dialog.kassel.de/realms/kassel-ssf-2025/account?referrer=ssf-frontend';
    vi.mocked(getAccountConsoleUrl).mockReturnValue(accountUrl);
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await userEvent.click(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    );
    expect(await screen.findByRole('status')).toHaveTextContent('AR000001');
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    expect(screen.getByRole('link', { name: 'Kontoeinstellungen (öffnet in neuem Tab)' })).toHaveAttribute(
      'href',
      accountUrl
    );
  });

  it('brings a custodian back to the ceremony after they open their archive keys from it', async () => {
    vi.mocked(hasPermission).mockReturnValue(true);
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'anna' });
    const point = toBase64Url(publicPoint(2n));
    server.use(
      http.get('*/api/admin/recording/ceremony', () =>
        HttpResponse.json({
          recovery_key: null,
          ceremony: {
            ceremony_id: '0d6c2b1a-9e8f-4d7c-b6a5-4f3e2d1c0b9a',
            k: 1,
            status: 'dealing',
            started_by: 'olga',
            started_at: '2026-10-26T09:00:00+00:00',
            expires_at: '2026-10-27T09:00:00+00:00',
            gateway_keys: [],
            participants: [
              { holder_index: 1, holder_ref: 'anna', kind: 'custodian', display_name: 'Anna', enc_pub: point, sig_pub: point, fingerprint: toBase64Url(new Uint8Array(32)) },
            ],
            dealings: [],
            confirmed: [],
            paper_confirmed: false,
            transcript_hash: null,
          },
        })
      ),
      http.get('*/api/admin/recording/keys/me', () =>
        HttpResponse.json({ detail: { error_code: 'KEY_NOT_ENROLLED', message: 'x' } }, { status: 404 })
      )
    );
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Wiederherstellungsschlüssel' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Archivschlüssel öffnen' }));
    expect(await screen.findByRole('heading', { name: 'Archivschlüssel' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(await screen.findByRole('heading', { name: 'Wiederherstellungsschlüssel' })).toBeInTheDocument();
  });

  it('opens the recording archive for a recording permission, and its unlock comes back to it', async () => {
    vi.mocked(hasPermission).mockImplementation(
      (permission) => permission === 'ssf.recording.request'
    );
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    server.use(
      http.get('*/api/admin/recording/keys/me', () =>
        HttpResponse.json(
          { detail: { error_code: 'KEY_NOT_ENROLLED', message: 'x' } },
          { status: 404 }
        )
      )
    );
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Meine Aufzeichnungen' }));
    expect(
      await screen.findByRole('heading', { name: 'Meine Aufzeichnungen' })
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Schlüssel entsperren' }));
    expect(await screen.findByRole('heading', { name: 'Archivschlüssel' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(
      await screen.findByRole('heading', { name: 'Meine Aufzeichnungen' })
    ).toBeInTheDocument();
  });

  it('opens recovery approvals for a custodian only, and its back returns to the dashboard', async () => {
    vi.mocked(hasPermission).mockImplementation(
      (permission) => permission === 'ssf.recording.recovery.custodian'
    );
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'carol' });
    server.use(
      http.get('*/api/admin/recording/recovery/approvals', () =>
        HttpResponse.json({ requests: [], share_stale: false })
      )
    );
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    expect(screen.queryByRole('button', { name: 'Wiederherstellungsanträge' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Wiederherstellungsfreigaben' }));
    expect(
      await screen.findByRole('heading', { name: 'Wiederherstellungsfreigaben' })
    ).toBeInTheDocument();
    expect(await screen.findByText('Es warten keine Anträge auf Sie.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(await screen.findByRole('button', { name: 'Neues Gespräch starten' })).toBeInTheDocument();
  });

  it('opens key recovery for a recording permission from the menu', async () => {
    vi.mocked(hasPermission).mockImplementation((permission) => permission === 'ssf.recording.request');
    vi.mocked(getAdminIdentity).mockReturnValue({ tenantId: 'tenant-kassel', userSub: 'alice' });
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });

    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Meine Schlüsselwiederherstellung' }));
    expect(await screen.findByRole('heading', { name: 'Meine Schlüsselwiederherstellung' })).toBeInTheDocument();
  });

  it('offers no recording archive without a recording permission', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel', locale: 'de' });
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    expect(screen.queryByRole('button', { name: 'Meine Aufzeichnungen' })).not.toBeInTheDocument();
  });

  it('does not render the dashboard while Keycloak redirects', async () => {
    vi.mocked(requireKeycloakLogin).mockResolvedValue(false);
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });
    await waitFor(() => expect(requireKeycloakLogin).toHaveBeenCalled());
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
  });

  it('rejects unknown IDs without interpreting them as realms', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login/kassel-ssf-2025' });
    expect(await screen.findByText(/404/)).toBeInTheDocument();
    expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });

  it('uses the router-decoded ID exactly once', async () => {
    const tenant = { ...kassel, id: 'tenant:kassel' };
    renderWithProviders(<AppRoutes />, {
      route: '/login/tenant%3Akassel',
      services: { loginTenant: { list: async () => [tenant] } },
    });
    await waitFor(() =>
      expect(requireKeycloakLogin).toHaveBeenCalledWith(expect.any(Object), tenant)
    );
  });

  it.each(['directory', 'authentication'])('fails neutrally on %s errors', async (source) => {
    if (source === 'authentication')
      vi.mocked(requireKeycloakLogin).mockRejectedValue(new Error('private details'));
    renderWithProviders(<AppRoutes />, {
      route: '/login/tenant-kassel',
      services: {
        loginTenant: {
          list: async () => {
            if (source === 'directory') throw new Error('private details');
            return [kassel];
          },
        },
      },
    });
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByText('private details')).not.toBeInTheDocument();
    if (source === 'directory') expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });

  it('returns to the chooser on logout', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('button', { name: 'Benutzerkonto' }));
    await userEvent.click(screen.getByRole('button', { name: 'Abmelden' }));
    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toBeInTheDocument();
    expect(logoutFromKeycloak).toHaveBeenCalledOnce();
  });

  it("sends dashboard feedback on the tenant's Studio staff form, with the tenant token", async () => {
    const sent: Record<string, unknown>[] = [];
    const staffContentReads = recordRequests((request) =>
      request.url.endsWith('/api/admin/content')
    );
    server.use(
      feedbackHandler('admin', (body) => {
        sent.push(body);
        return HttpResponse.json({ feedback_id: 'f1' }, { status: 201 });
      })
    );
    const authorizations = recordAuthorization('/api/admin/feedback');
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });

    await userEvent.click(screen.getByRole('button', { name: 'Feedback' }));
    const dialog = await screen.findByRole('dialog', { name: 'Feedback geben' });
    expect(
      within(dialog).getByPlaceholderText('Ihre Ideen oder Beschwerden sind willkommen.')
    ).toBeInTheDocument();
    for (const label of ['Übersetzungsqualität', 'Geschwindigkeit', 'Bedienung']) {
      const group = within(dialog).getByRole('group', { name: label });
      await userEvent.click(within(group).getByRole('button', { name: '5 Sterne' }));
    }
    await userEvent.click(within(dialog).getByRole('button', { name: 'Wert 9' }));
    await userEvent.click(within(dialog).getByRole('button', { name: /Feedback senden/ }));

    expect(await screen.findByText('Vielen Dank!')).toBeInTheDocument();
    expect(sent).toEqual([
      {
        audience: 'staff',
        locale: 'de-DE',
        form_source: 'studio',
        configuration_revision: KASSEL_REVISION,
        answers: { translationQuality: 5, performance: 5, usability: 5, recommendation: 9 },
      },
    ]);
    expect(authorizations).toEqual(['Bearer tenant-token']);
    // The sheet reads the dashboard's own query in the tenant's client.
    expect(staffContentReads).toHaveLength(1);
  });

  it('returns to the chooser when the authenticated session expires', async () => {
    renderWithProviders(<AppRoutes />, { route: '/login/tenant-kassel' });
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    act(() => {
      for (const listener of expirationListeners) listener();
    });
    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
  });

  it.each(['cached', 'pending'])('isolates %s tenant A history from tenant B', async (state) => {
    const row = (id: string): AdminSession => ({
      id,
      status: 'open',
      customerLanguage: null,
      createdAt: '2026-09-10T10:00:00Z',
      terminatedAt: null,
    });
    let finishA!: (rows: AdminSession[]) => void;
    let finishB!: (rows: AdminSession[]) => void;
    const listSessions = vi
      .fn()
      .mockImplementationOnce(() =>
        state === 'cached'
          ? Promise.resolve([row('TENANTA1')])
          : new Promise<AdminSession[]>((resolve) => {
              finishA = resolve;
            })
      )
      .mockImplementationOnce(
        () =>
          new Promise<AdminSession[]>((resolve) => {
            finishB = resolve;
          })
      );
    renderWithProviders(
      <>
        <AppRoutes />
        <Link to="/login/tenant-fulda">Switch tenant</Link>
      </>,
      {
        route: '/login/tenant-kassel',
        services: {
          admin: {
            listSessions,
            createSession: vi.fn(),
            terminateSession: vi.fn(),
          },
        },
      }
    );
    await waitFor(() => expect(listSessions).toHaveBeenCalledTimes(1));
    if (state === 'cached')
      await screen.findByRole('button', { name: 'Gespräch TENANTA1 fortsetzen' });
    await userEvent.click(screen.getByRole('link', { name: 'Switch tenant' }));
    await waitFor(() =>
      expect(requireKeycloakLogin).toHaveBeenLastCalledWith(expect.any(Object), {
        id: 'tenant-fulda',
        displayName: 'Amt Fulda',
        realm: 'fulda-ssf-2025',
        studioUrl: 'https://fulda.dialog.kassel.de/',
      })
    );
    if (state === 'pending') await act(async () => finishA([row('TENANTA1')]));
    expect(
      screen.queryByRole('button', { name: 'Gespräch TENANTA1 fortsetzen' })
    ).not.toBeInTheDocument();
    await waitFor(() => expect(listSessions).toHaveBeenCalledTimes(2));
    await act(async () => finishB([row('TENANTB1')]));
    expect(
      await screen.findByRole('button', { name: 'Gespräch TENANTB1 fortsetzen' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Gespräch TENANTA1 fortsetzen' })
    ).not.toBeInTheDocument();
  });

  it('cannot expose a previous dashboard after navigating to an unknown tenant', async () => {
    renderWithProviders(
      <>
        <AppRoutes />
        <Link to="/login/unknown">Unknown tenant</Link>
      </>,
      { route: '/login/tenant-kassel' }
    );
    await screen.findByRole('button', { name: 'Neues Gespräch starten' });
    await userEvent.click(screen.getByRole('link', { name: 'Unknown tenant' }));
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('ignores authentication completion after leaving the tenant route', async () => {
    let finish!: (value: boolean) => void;
    vi.mocked(requireKeycloakLogin).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    renderWithProviders(
      <>
        <AppRoutes />
        <Link to="/login/unknown">Unknown tenant</Link>
      </>,
      { route: '/login/tenant-kassel' }
    );
    await waitFor(() => expect(requireKeycloakLogin).toHaveBeenCalled());
    await userEvent.click(screen.getByRole('link', { name: 'Unknown tenant' }));
    await act(async () => finish(true));
    expect(
      screen.queryByRole('button', { name: 'Neues Gespräch starten' })
    ).not.toBeInTheDocument();
  });

  it('serves the not-found page at the retired /admin password entry', async () => {
    renderWithProviders(<AppRoutes />, { route: '/admin' });
    expect(await screen.findByText(/404/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Passwort')).not.toBeInTheDocument();
    expect(requireKeycloakLogin).not.toHaveBeenCalled();
  });
});

describe('AppRoutes', () => {
  afterEach(() => {
    sessionStorage.clear();
  });

  it('serves the access-code screen at the root', async () => {
    renderWithProviders(<AppRoutes />, { route: '/' });

    expect(await screen.findByRole('heading', { name: 'Code eingeben' })).toBeInTheDocument();
  });

  it('renders the not-found page for the removed legacy landing route', async () => {
    renderWithProviders(<AppRoutes />, { route: '/legacy' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('renders the not-found page for the removed legacy admin route', async () => {
    renderWithProviders(<AppRoutes />, { route: '/legacy/admin' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('renders the not-found page for the removed customer page', async () => {
    sessionStorage.setItem('authenticated', 'true');
    renderWithProviders(<AppRoutes />, { route: '/customer' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('renders the not-found page for an unknown path', async () => {
    renderWithProviders(<AppRoutes />, { route: '/nowhere' });

    expect(await screen.findByText(/404/)).toBeInTheDocument();
  });

  it('sends a QR deep link straight to the language picker', async () => {
    renderWithProviders(<AppRoutes />, { route: '/join/A1B2C3D4' });

    expect(
      await screen.findByRole('heading', { name: 'Choose your language' })
    ).toBeInTheDocument();
  });
});

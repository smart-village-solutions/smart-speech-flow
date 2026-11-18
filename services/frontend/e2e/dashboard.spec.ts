import { expect, test } from '@playwright/test';
import { installationBody, staffContentBody } from '../src/test/contentFixtures';
import { conversationRow } from '../src/test/dashboardFixtures';

const auth = `
export const subscribeToKeycloakAuthorization = () => () => {};
export const subscribeToKeycloakExpiration = () => () => {};
export const requireKeycloakLogin = async () => true;
export const getAdminIdentity = () => ({tenantId:'tenant-kassel',userSub:'employee'});
export const hasPermission = p => p==='ssf.recording.review';
export const getAdminAccessToken = async () => 'test-user';
export const getAccountConsoleUrl = () => 'https://account.invalid/';
export const getStudioAdministrationUrl = () => null;
export const logoutFromKeycloak = async () => {};
`;

for (const width of [390, 1200]) {
  test(`task filters, account navigation and result-only access at ${width}px`, async ({
    page,
  }) => {
    const accessed: string[] = [];
    let connections = 0;
    let disconnections = 0;
    await page.routeWebSocket('**/ws/admin/AR000001*', (socket) => {
      connections++;
      socket.onClose(() => {
        disconnections++;
      });
    });
    const when = '2026-11-18T09:00:00Z';
    const assignment = '91960b41-2766-4033-840b-31940a312493';
    await page.setViewportSize({ width, height: 850 });
    await page.route('**/src/app/auth/keycloak.ts*', (route) =>
      route.fulfill({ contentType: 'application/javascript', body: auth })
    );
    await page.route('**/api/**', (route) => {
      const url = new URL(route.request().url());
      accessed.push(url.pathname);
      const totals = { total_seconds: 600, by_language: { ar: 600 } };
      const data: Record<string, unknown> = {
        '/api/content/installation': installationBody,
        '/api/admin/content': staffContentBody,
        '/api/login/tenants': {
          tenants: [{ id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel' }],
        },
        '/api/admin/usage': {
          window_start: when,
          window_end: when,
          coverage_start: when,
          complete: true,
          personal: totals,
          organisation: totals,
          server: totals,
        },
        '/api/health/summary': {
          status: 'success',
          overall_healthy: true,
          summary: {
            service_mode: 'full',
            circuit_states: {},
            gpu: { critical_devices: 0, warning_devices: 0, recommended_action: 'steady' },
          },
        },
        '/api/admin/dashboard/conversations': {
          items: url.searchParams.has('cursor')
            ? [conversationRow('NEW', false)]
            : [
                conversationRow('AR000001'),
                {
                  ...conversationRow('PRIVATE', false),
                  recording_status: 'available',
                  recording_access: 'available',
                  language_visibility: 'encrypted',
                  customer_language: null,
                  actions: ['open_recording'],
                  recording_id: '8afce877-c57c-44f8-8416-1bad0f8a4fe6',
                },
              ],
          next_cursor: url.searchParams.has('cursor') ? null : 'page2',
        },
        '/api/admin/recording/reviews': {
          reviews: [
            {
              verification_id: assignment,
              status: 'approved',
              requested_at: when,
              requested_by: 'employee',
              started_at: when,
              ended_at: when,
              messages: 2,
              openable: false,
              requested_by_name: 'Alice',
            },
          ],
        },
        [`/api/admin/recording/verifications/${assignment}/result`]: {
          verification_id: assignment,
          status: 'approved',
          outcome: 'approved',
          requested_at: when,
          decided_at: when,
          requested_by_name: 'Alice',
        },
        '/api/admin/session/AR000001/status': {
          id: 'AR000001',
          customer_language: 'ar',
          admin_language: 'de',
          status: 'active',
          created_at: when,
          message_count: 0,
          admin_connected: true,
          customer_connected: true,
        },
        '/api/admin/session/AR000001/realtime-ticket': { ticket: 'local-fixture' },
        '/api/admin/session/AR000001/messages': { session_id: 'AR000001', messages: [] },
        '/api/admin/recording/key-policy': { passphrase_file_enabled: false },
        '/api/admin/recording/v2/keys/me': { activeVersion: null, versions: [] },
      };
      return Object.hasOwn(data, url.pathname)
        ? route.fulfill({ json: data[url.pathname] })
        : route.fulfill({ status: 404, json: {} });
    });
    await page.goto('/login/tenant-kassel');
    const language = page.getByRole('combobox', { name: 'Sprache' });
    const status = page.getByRole('combobox', { name: 'Status' });
    await language.selectOption('ar');
    await status.selectOption('ended');
    await expect(
      page.getByText('Keine passenden Einträge unter den geladenen Einträgen.')
    ).toBeVisible();
    await expect(page.getByText(/Einträge mit unbekannter oder gesperrter Sprache/)).toBeVisible();
    await page.getByRole('button', { name: 'Weitere laden' }).click();
    await expect(page.getByText(/0 von 3 geladenen/)).toBeVisible();
    const reviews = page.getByRole('button', { name: 'Meine Prüfungen' });
    await reviews.focus();
    await page.keyboard.press('Enter');
    await expect(language).toHaveValue('');
    await status.selectOption('approved');
    await page.getByRole('button', { name: 'Ergebnis ansehen' }).click();
    await expect(page.getByText(assignment)).toBeVisible();
    expect(
      accessed.filter((path) => path.includes('/archive') || path.includes('/gateway-signers'))
    ).toEqual([]);
    await page.getByRole('button', { name: 'Zurück' }).click();
    await expect(status).toHaveValue('approved');
    await page.getByRole('button', { name: 'Benutzerkonto' }).click();
    await page.getByRole('button', { name: 'Mein Konto' }).click();
    await expect(page.getByRole('link', { name: 'Kontoeinstellungen' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Schlüssel erzeugen' })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('account.png') });
    await page.getByRole('button', { name: 'Zurück' }).click();
    await page.getByRole('button', { name: 'Meine Gespräche' }).click();
    await expect(language).toHaveValue('ar');
    await expect(status).toHaveValue('ended');
    await page.getByRole('button', { name: 'Filter zurücksetzen' }).click();
    await expect(page.getByRole('button', { name: 'Aufzeichnung öffnen' })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    ).toBe(true);
    await page.getByRole('region', { name: 'Meine Gespräche' }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath('dashboard.png') });
    await page.getByRole('button', { name: 'Gespräch AR000001 fortsetzen' }).click();
    await page.getByRole('button', { name: 'Tastatur öffnen' }).click();
    await page.getByRole('textbox').fill('Entwurf');
    await expect.poll(() => connections).toBe(1);
    await page.getByRole('button', { name: 'Benutzerkonto' }).click();
    await page.getByRole('button', { name: 'Mein Konto' }).click();
    await expect(page.getByRole('heading', { name: 'Mein Konto' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Gespräch beenden' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Zurück' }).click();
    if (!(await page.getByRole('textbox').isVisible()))
      await page.getByRole('button', { name: 'Tastatur öffnen' }).click();
    await expect(page.getByRole('textbox')).toHaveValue('Entwurf');
    expect(connections).toBe(1);
    expect(disconnections).toBe(0);
  });
}

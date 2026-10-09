import { describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { installFakeClipboard } from '@/test/fakeClipboard';
import { StaffContentSettled } from '@/test/ContentSettled';
import { STUDIO_STAFF, staffContentBodyWith } from '@/test/contentFixtures';
import { staffContentHandler, staffContentUnavailable } from '@/test/handlers';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import type { SystemLoadLevel } from '@/domain/health/health.types';

const noop = () => undefined;

/** Renders the dashboard and waits until its staff content has arrived or failed. */
async function renderDashboard(options: Parameters<typeof renderWithProviders>[1] = {}) {
  const result = renderWithProviders(
    <>
      <AdminDashboardScreen onEnterSession={noop} onSignOut={noop} />
      <StaffContentSettled />
    </>,
    options
  );
  await screen.findByTestId('staff-content-settled');
  return result;
}

const BUNDLED_INTRO = /stellt einen virtuellen Echtzeit-Dolmetscher bereit/;

const noOwnLiveSession = () =>
  server.use(
    http.get('*/api/admin/session/current', () =>
      HttpResponse.json({ detail: 'Keine aktive Admin-Session gefunden' }, { status: 404 })
    )
  );

describe('AdminDashboardScreen', () => {
  it('positions the dashboard below the header with the shared content offset', async () => {
    await renderDashboard();

    expect((await screen.findByText('Willkommen bei KasselDIALOG')).closest('div[class*="pt-"]'))
      .toHaveClass('pt-content-top');
  });

  it('keeps the legal links at the foot of the page however short the list is', async () => {
    await renderDashboard();

    expect(
      await screen.findByRole('navigation', { name: 'Rechtliches' })
    ).toHaveClass('mt-auto');
  });

  it('welcomes the SSF tenant', async () => {
    await renderDashboard({
      brand: 'ssf',
    });
    expect(await screen.findByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
  });

  it('welcomes the Kassel tenant', async () => {
    await renderDashboard({
      brand: 'kassel',
    });
    expect(await screen.findByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
  });

  it('lists the sessions the gateway returned, live one first', async () => {
    await renderDashboard({
      locale: 'de',
    });

    expect(await screen.findByText('Vergangene Gespräche')).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' })
    ).toBeInTheDocument();
  });

  it('warns before a new conversation ends the live one', async () => {
    await renderDashboard({
      locale: 'de',
    });

    await userEvent.click(await screen.findByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/AR000001/)).toBeInTheDocument();
  });

  // The history lists every admin of the tenant; only the admin's own session ends.
  it("names the admin's own conversation, not a colleague's newer one", async () => {
    server.use(
      http.get('*/api/admin/session/current', () =>
        HttpResponse.json({ session_id: 'DE000001', status: 'active' })
      )
    );
    await renderDashboard({
      locale: 'de',
    });
    await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' });

    await userEvent.click(screen.getByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByRole('dialog')).toHaveTextContent('DE000001');
    expect(screen.getByRole('dialog')).not.toHaveTextContent('AR000001');
  });

  it("does not warn when only a colleague's conversation is live", async () => {
    installFakeClipboard();
    server.use(
      http.get('*/api/admin/session/current', () =>
        HttpResponse.json({ detail: 'Keine aktive Admin-Session gefunden' }, { status: 404 })
      )
    );
    await renderDashboard({
      locale: 'de',
    });
    await screen.findByRole('button', { name: 'Gespräch AR000001 fortsetzen' });

    await userEvent.click(screen.getByRole('button', { name: 'Neues Gespräch starten' }));

    expect(await screen.findByText('Neues Gespräch')).toBeInTheDocument();
    expect(screen.queryByText(/Laufendes Gespräch beenden/)).not.toBeInTheDocument();
  });

  it('shows the system load from the gateway', async () => {
    await renderDashboard();
    expect(await screen.findByText('Ausreichend Kapazitäten verfügbar')).toBeInTheDocument();
  });

  it('carries the admin header', async () => {
    await renderDashboard();
    expect(await screen.findByRole('button', { name: 'Benutzerkonto' })).toBeInTheDocument();
  });

  describe('with Studio staff texts', () => {
    it('shows Studio texts instead of the bundled ones', async () => {
      server.use(staffContentHandler(staffContentBodyWith({ marked: true })));
      await renderDashboard();

      expect(screen.getByText(STUDIO_STAFF.headline)).toBeInTheDocument();
      expect(screen.getByText(STUDIO_STAFF.intro)).toBeInTheDocument();
      expect(screen.getByText(STUDIO_STAFF.secondParagraph)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: STUDIO_STAFF.callToAction })).toBeInTheDocument();
      expect(screen.getByText(STUDIO_STAFF.loadHeadline)).toBeInTheDocument();
      expect(screen.queryByText(BUNDLED_INTRO)).not.toBeInTheDocument();
    });

    it.each([
      ['ok', STUDIO_STAFF.green],
      ['delayed', STUDIO_STAFF.yellow],
      ['unavailable', STUDIO_STAFF.red],
      ['unknown', 'Systemauslastung nicht abrufbar'],
    ] as const)('labels the %s load with %s', async (level: SystemLoadLevel, label) => {
      server.use(staffContentHandler(staffContentBodyWith({ marked: true })));
      await renderDashboard({
        services: { health: { getSystemLoad: () => Promise.resolve({ level }) } },
      });

      expect(await screen.findByText(label)).toBeInTheDocument();
    });

    it('renders Studio paragraphs in a block container, never a paragraph in a paragraph', async () => {
      server.use(staffContentHandler(staffContentBodyWith({ marked: true })));
      const { container } = await renderDashboard();

      const intro = screen.getByText(STUDIO_STAFF.intro);
      expect(intro.tagName).toBe('P');
      expect(intro.parentElement?.tagName).toBe('DIV');
      expect(container.querySelectorAll('p p')).toHaveLength(0);
    });

    it('titles the invite with Studio texts', async () => {
      installFakeClipboard();
      noOwnLiveSession();
      server.use(staffContentHandler(staffContentBodyWith({ marked: true })));
      await renderDashboard();

      await userEvent.click(screen.getByRole('button', { name: STUDIO_STAFF.callToAction }));

      const dialog = await screen.findByRole('dialog');
      expect(dialog).toHaveTextContent(STUDIO_STAFF.inviteHeadline);
      expect(screen.getByText(STUDIO_STAFF.inviteDescription).parentElement?.tagName).toBe('DIV');
      expect(document.querySelectorAll('p p')).toHaveLength(0);
    });

    it('falls back to the bundled texts when the staff route answers 503', async () => {
      server.use(staffContentUnavailable());
      await renderDashboard({
        services: { health: { getSystemLoad: () => Promise.resolve({ level: 'ok' }) } },
      });

      expect(screen.getByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
      expect(screen.getByText(BUNDLED_INTRO)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Neues Gespräch starten' })).toBeInTheDocument();
      expect(await screen.findByText('Ausreichend Kapazitäten verfügbar')).toBeInTheDocument();
      expect(screen.queryByText(/^Studio/)).not.toBeInTheDocument();
    });

    it('falls back to the bundled texts when Studio writes in another language', async () => {
      server.use(staffContentHandler(staffContentBodyWith({ marked: true, locale: 'en-US' })));
      await renderDashboard();

      expect(screen.getByText('Willkommen bei KasselDIALOG')).toBeInTheDocument();
      expect(screen.getByText(BUNDLED_INTRO)).toBeInTheDocument();
      expect(screen.queryByText(/^Studio/)).not.toBeInTheDocument();
    });

    it('never shows the tenant display name, even when a body carries it', async () => {
      server.use(
        staffContentHandler({
          ...staffContentBodyWith({ marked: true }),
          tenant: { id: 'tenant-kassel', displayName: 'Smart City Kassel' },
          displayName: 'Smart City Kassel',
        })
      );
      await renderDashboard();

      expect(screen.getByText(STUDIO_STAFF.headline)).toBeInTheDocument();
      expect(document.body).not.toHaveTextContent('Smart City Kassel');
    });
  });
});

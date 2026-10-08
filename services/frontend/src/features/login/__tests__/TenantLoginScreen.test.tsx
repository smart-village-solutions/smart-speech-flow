import { http, HttpResponse } from 'msw';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import { server } from '@/test/setup';
import { installationBody } from '@/test/contentFixtures';
import { ContentSettled } from '@/test/ContentSettled';
import type { LoginTenant } from '@/domain/login-tenant/loginTenant.types';
import { TenantLoginScreen } from '@/features/login/TenantLoginScreen';

function renderScreen(list: () => Promise<LoginTenant[]>) {
  return renderWithProviders(
    <>
      <TenantLoginScreen />
      <ContentSettled />
    </>,
    {
      locale: 'de',
      brand: 'kassel',
      services: { loginTenant: { list } },
    }
  );
}

function serveLogin(locale: string, login: { headline: string; descriptionHtml: string }) {
  server.use(
    http.get('*/api/content/installation', () =>
      HttpResponse.json({ ...installationBody, locale, login })
    )
  );
}

describe('TenantLoginScreen', () => {
  it('shows loading feedback while the tenant directory is pending', async () => {
    renderScreen(() => new Promise<LoginTenant[]>(() => undefined));
    await screen.findByTestId('public-content-settled');

    expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
    expect(screen.getByText('Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('explains when no organisation is available without offering a tenant', async () => {
    renderScreen(async () => []);

    expect(await screen.findByText('Derzeit sind keine Organisationen verfügbar.')).toBeInTheDocument();
    // The footer's legal links are not organisations.
    expect(within(screen.getByRole('main')).queryAllByRole('link')).toHaveLength(0);
  });

  it('offers a retry after the directory request fails', async () => {
    const list = vi
      .fn<() => Promise<LoginTenant[]>>()
      .mockRejectedValueOnce(new Error('directory unavailable'))
      .mockResolvedValueOnce([
        { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' },
      ]);

    renderScreen(list);

    expect(
      await screen.findByText('Die Liste der Organisationen ist derzeit nicht verfügbar.')
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));

    expect(await screen.findByRole('link', { name: 'Stadt Kassel' })).toHaveAttribute(
      'href',
      '/login/tenant-kassel'
    );
    expect(list).toHaveBeenCalledTimes(2);
  });

  it('orders accessible tenant links in German without displaying internal identifiers', async () => {
    renderScreen(async () => [
      { id: 'tenant:kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' },
      { id: 'tenant-amter-b', displayName: 'Ämter', realm: 'amter-b-ssf-2025' },
      { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' },
      { id: 'tenant-amter-a', displayName: 'Ämter', realm: 'amter-a-ssf-2025' },
    ]);

    expect(
      await screen.findAllByRole('link', { name: 'Ämter' })
    ).toHaveLength(2);

    const links = within(screen.getByRole('main')).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual([
      'Amt Fulda',
      'Ämter',
      'Ämter',
      'Stadt Kassel',
    ]);
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/login/tenant-fulda',
      '/login/tenant-amter-a',
      '/login/tenant-amter-b',
      '/login/tenant%3Akassel',
    ]);
    expect(screen.queryByText('tenant:kassel')).not.toBeInTheDocument();
    expect(screen.queryByText('kassel-ssf-2025')).not.toBeInTheDocument();
  });

  it('retains the shared header and branded funding footer', async () => {
    renderScreen(async () => []);

    expect(screen.getByRole('banner')).toHaveClass('bg-white');
    expect(screen.getByRole('img', { name: 'KasselDIALOG' })).toHaveAttribute(
      'src',
      '/assets/Logo.png'
    );

    await screen.findByText('Derzeit sind keine Organisationen verfügbar.');
    const funding = screen.getByRole('img', { name: 'Fördermittelgeber' });
    const city = screen.getByRole('img', { name: 'Stadt Kassel' });
    expect(funding.closest('footer')).toContainElement(city);
  });

  describe('installation texts', () => {
    const DIRECTORY_NAME = 'Stadt Kassel';
    const BUNDLED_INSTRUCTION = 'Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.';

    async function renderSettled() {
      renderWithProviders(
        <>
          <TenantLoginScreen />
          <ContentSettled />
        </>,
        {
          locale: 'de',
          brand: 'kassel',
          publicContent: 'fetched',
          services: {
            loginTenant: {
              list: () =>
                Promise.resolve([
                  { id: 'tenant-kassel', displayName: DIRECTORY_NAME, realm: 'kassel-ssf-2025' },
                ]),
            },
          },
        }
      );
      await screen.findByTestId('public-content-settled');
    }

    it('shows the Studio headline and description, without the empty paragraph', async () => {
      serveLogin('de-DE', {
        headline: 'Anmeldung',
        descriptionHtml: '<p>Wählen Sie <strong>Ihre</strong> Organisation.</p><p></p>',
      });

      await renderSettled();

      expect(screen.getByRole('heading', { name: 'Anmeldung' })).toBeInTheDocument();
      const paragraph = screen.getByText('Ihre').closest('p');
      expect(paragraph).toHaveTextContent('Wählen Sie Ihre Organisation.');
      expect(paragraph?.parentElement?.querySelectorAll('p')).toHaveLength(1);
      expect(screen.queryByText(BUNDLED_INSTRUCTION)).not.toBeInTheDocument();
    });

    it('keeps a description without paragraphs on one line', async () => {
      serveLogin('de-DE', {
        headline: 'Login',
        descriptionHtml: 'Wählen Sie <strong>Ihre</strong> Organisation.',
      });

      await renderSettled();

      const paragraph = screen.getByText('Ihre').closest('p');
      expect(paragraph).toHaveTextContent('Wählen Sie Ihre Organisation.');
      expect(paragraph?.parentElement?.childNodes).toHaveLength(1);
    });

    it('shows the live description as one paragraph', async () => {
      await renderSettled();

      const paragraph = screen.getByText(BUNDLED_INSTRUCTION);
      expect(paragraph.tagName).toBe('P');
      expect(paragraph.parentElement?.querySelectorAll('p')).toHaveLength(1);
    });

    it('keeps bundled texts while installation content is unavailable (503)', async () => {
      server.use(
        http.get('*/api/content/installation', () =>
          HttpResponse.json({ detail: 'Studio content is temporarily unavailable' }, { status: 503 })
        )
      );

      await renderSettled();

      expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
      expect(screen.getByText(BUNDLED_INSTRUCTION).tagName).toBe('P');
    });

    it('keeps bundled texts when the content is in another language', async () => {
      serveLogin('en-GB', {
        headline: 'Sign in',
        descriptionHtml: '<p>Choose your organisation.</p>',
      });

      await renderSettled();

      expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
      expect(screen.getByText(BUNDLED_INSTRUCTION)).toBeInTheDocument();
      expect(screen.queryByText('Choose your organisation.')).not.toBeInTheDocument();
    });

    it('lists organisations by their login directory names', async () => {
      await renderSettled();

      expect(await screen.findByRole('link', { name: DIRECTORY_NAME })).toHaveAttribute(
        'href',
        '/login/tenant-kassel'
      );
    });
  });
});

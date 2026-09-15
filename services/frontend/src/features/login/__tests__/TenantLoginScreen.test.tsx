import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { LoginTenant } from '@/domain/login-tenant/loginTenant.types';
import { TenantLoginScreen } from '@/features/login/TenantLoginScreen';

function renderScreen(list: () => Promise<LoginTenant[]>) {
  return renderWithProviders(<TenantLoginScreen />, {
    locale: 'de',
    services: { loginTenant: { list } },
  });
}

describe('TenantLoginScreen', () => {
  it('shows loading feedback while the tenant directory is pending', () => {
    renderScreen(() => new Promise<LoginTenant[]>(() => undefined));

    expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
    expect(screen.getByText('Bitte wählen Sie Ihre Abteilung oder Organisation aus der Liste aus.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('explains when no organisation is available without offering a tenant', async () => {
    renderScreen(async () => []);

    expect(await screen.findByText('Derzeit sind keine Organisationen verfügbar.')).toBeInTheDocument();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
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

    const links = screen.getAllByRole('link');
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
    expect(screen.getByRole('img', { name: 'Smart Speech Flow' })).toHaveAttribute(
      'src',
      '/assets/Logo.png'
    );

    await screen.findByText('Derzeit sind keine Organisationen verfügbar.');
    const funding = screen.getByRole('img', { name: 'Fördermittelgeber' });
    const city = screen.getByRole('img', { name: 'Stadt Kassel' });
    expect(funding.closest('footer')).toContainElement(city);
  });
});

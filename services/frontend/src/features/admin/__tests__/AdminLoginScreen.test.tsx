import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AdminLoginScreen } from '@/features/admin/AdminLoginScreen';

const accepts = (password: string) => password === 'ssf2025kassel';

const renderLogin = (onSignIn = vi.fn(accepts)) => {
  renderWithProviders(<AdminLoginScreen onSignIn={onSignIn} onBack={vi.fn()} />, { locale: 'de' });
  return onSignIn;
};

const fill = async (email: string, password: string) => {
  await userEvent.type(await screen.findByLabelText('E-Mail-Adresse'), email);
  await userEvent.type(screen.getByLabelText('Passwort'), password);
};

describe('AdminLoginScreen', () => {
  it('imitates the Keycloak page it stands in for', async () => {
    renderLogin();
    expect(await screen.findByText('Keycloak \u2014 Smart Speech Flow')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Anmelden' })).toBeInTheDocument();
  });

  it('keeps the submit disabled until both fields are filled', async () => {
    renderLogin();

    const submit = await screen.findByRole('button', { name: 'Anmelden' });
    expect(submit).toBeDisabled();

    await fill('admin@example.com', 'ssf2025kassel');
    expect(submit).toBeEnabled();
  });

  it('refuses a malformed address without asking the gate', async () => {
    const onSignIn = renderLogin();

    await fill('not-an-address', 'ssf2025kassel');
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));

    expect(
      await screen.findByText('Bitte eine gültige E-Mail-Adresse eingeben.')
    ).toBeInTheDocument();
    expect(onSignIn).not.toHaveBeenCalled();
  });

  // The message never says which half was wrong.
  it('reports a rejected password as invalid credentials', async () => {
    const onSignIn = renderLogin();

    await fill('admin@example.com', 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Ungültige Anmeldedaten.');
    expect(onSignIn).toHaveBeenCalledWith('wrong');
  });

  it('clears the error as soon as either field is edited', async () => {
    renderLogin();

    await fill('admin@example.com', 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));
    await screen.findByRole('alert');

    await userEvent.type(screen.getByLabelText('Passwort'), 'x');

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('accepts the configured password', async () => {
    const onSignIn = renderLogin();

    await fill('admin@example.com', 'ssf2025kassel');
    await userEvent.click(screen.getByRole('button', { name: 'Anmelden' }));

    expect(onSignIn).toHaveBeenCalledWith('ssf2025kassel');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  // The card is a hardcoded white imitation of the identity provider, but
  // `TextField` reads the app's colour tokens. Without the `kc-page` scope
  // pinning them, dark mode paints white ink on that white card and the fields
  // cannot be read. No stylesheet is loaded in jsdom, so the scope's presence is
  // what is assertable here; `scripts/check-tokens.sh` covers what it contains.
  it('scopes its colours so the fields stay readable in the dark theme', () => {
    const { container } = renderWithProviders(
      <AdminLoginScreen onSignIn={vi.fn(accepts)} onBack={vi.fn()} />,
      { locale: 'de', theme: 'dark' }
    );

    expect(container.querySelector('.kc-page')).not.toBeNull();
  });
});

import { beforeEach, describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { readConfig } from '@/app/config/env';
import { useAdminAuth } from '@/features/admin/useAdminAuth';

function Probe() {
  const { signedIn, signIn, signOut } = useAdminAuth();
  return (
    <>
      <p>{signedIn ? 'in' : 'out'}</p>
      <button type="button" onClick={() => signIn('ssf2025kassel')}>
        right
      </button>
      <button type="button" onClick={() => signIn('nope')}>
        wrong
      </button>
      <button type="button" onClick={signOut}>
        leave
      </button>
    </>
  );
}

const withPassword = { config: { ...readConfig({}), adminPassword: 'ssf2025kassel' } };

describe('useAdminAuth', () => {
  beforeEach(() => sessionStorage.clear());

  it('starts signed out', () => {
    renderWithProviders(<Probe />, { services: withPassword });
    expect(screen.getByText('out')).toBeInTheDocument();
  });

  it('accepts the configured password', async () => {
    renderWithProviders(<Probe />, { services: withPassword });

    await userEvent.click(screen.getByRole('button', { name: 'right' }));

    expect(screen.getByText('in')).toBeInTheDocument();
  });

  it('refuses anything else', async () => {
    renderWithProviders(<Probe />, { services: withPassword });

    await userEvent.click(screen.getByRole('button', { name: 'wrong' }));

    expect(screen.getByText('out')).toBeInTheDocument();
  });

  // A refresh mid-conversation must not drop the admin back to a login while a
  // customer is waiting, which is why this survives a remount.
  it('survives a reload', async () => {
    const { unmount } = renderWithProviders(<Probe />, { services: withPassword });
    await userEvent.click(screen.getByRole('button', { name: 'right' }));
    unmount();

    renderWithProviders(<Probe />, { services: withPassword });

    expect(screen.getByText('in')).toBeInTheDocument();
  });

  it('forgets on sign-out', async () => {
    renderWithProviders(<Probe />, { services: withPassword });
    await userEvent.click(screen.getByRole('button', { name: 'right' }));

    await userEvent.click(screen.getByRole('button', { name: 'leave' }));

    expect(screen.getByText('out')).toBeInTheDocument();
    expect(sessionStorage.getItem('authenticated')).toBeNull();
  });
});

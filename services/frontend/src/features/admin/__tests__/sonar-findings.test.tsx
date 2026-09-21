import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AdminLoginScreen } from '@/features/admin/AdminLoginScreen';
import { SessionStatusOverlay } from '@/features/admin/SessionStatusOverlay';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('admin frontend regressions', () => {
  it('rejects a long malformed email without super-linear backtracking', () => {
    const onSignIn = vi.fn(() => true);
    renderWithProviders(<AdminLoginScreen onSignIn={onSignIn} onBack={vi.fn()} />, {
      locale: 'de',
    });
    fireEvent.change(screen.getByLabelText('E-Mail-Adresse'), {
      target: { value: `admin@${'.'.repeat(100_000)}@` },
    });
    fireEvent.change(screen.getByLabelText('Passwort'), { target: { value: 'password' } });

    const startedAt = performance.now();
    fireEvent.click(screen.getByRole('button', { name: 'Anmelden' }));
    const elapsedMilliseconds = performance.now() - startedAt;

    expect(screen.getByText('Bitte eine gültige E-Mail-Adresse eingeben.')).toBeInTheDocument();
    expect(onSignIn).not.toHaveBeenCalled();
    expect(elapsedMilliseconds).toBeLessThan(2_000);
  });

  it('exposes changing session status through an output element', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connected" language={null} />,
      { locale: 'de' }
    );

    expect(screen.getByRole('status')).toHaveProperty('tagName', 'OUTPUT');
  });
});

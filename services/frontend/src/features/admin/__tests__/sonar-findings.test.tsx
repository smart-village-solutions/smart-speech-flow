import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SessionStatusOverlay } from '@/features/admin/SessionStatusOverlay';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('admin frontend regressions', () => {
  it('exposes changing session status through an output element', () => {
    renderWithProviders(
      <SessionStatusOverlay sessionId="A1B2C3D4" connection="connected" language={null} />,
      { locale: 'de' }
    );

    expect(screen.getByRole('status')).toHaveProperty('tagName', 'OUTPUT');
  });
});

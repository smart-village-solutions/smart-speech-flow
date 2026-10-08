import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { LoginTenant } from '@/domain/login-tenant/loginTenant.types';
import { TenantLoginScreen } from '@/features/login/TenantLoginScreen';
import { renderWithProviders } from '@/test/renderWithProviders';
import { ContentSettled } from '@/test/ContentSettled';

describe('tenant login frontend regressions', () => {
  it('exposes loading status through an output element', async () => {
    renderWithProviders(
      <>
        <TenantLoginScreen />
        <ContentSettled />
      </>,
      {
        locale: 'de',
        services: {
          loginTenant: {
            list: () => new Promise<LoginTenant[]>(() => undefined),
          },
        },
      }
    );
    await screen.findByTestId('public-content-settled');

    expect(screen.getByRole('status')).toHaveProperty('tagName', 'OUTPUT');
  });
});

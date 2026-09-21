import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { LoginTenant } from '@/domain/login-tenant/loginTenant.types';
import { TenantLoginScreen } from '@/features/login/TenantLoginScreen';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('tenant login frontend regressions', () => {
  it('exposes loading status through an output element', () => {
    renderWithProviders(<TenantLoginScreen />, {
      locale: 'de',
      services: {
        loginTenant: {
          list: () => new Promise<LoginTenant[]>(() => undefined),
        },
      },
    });

    expect(screen.getByRole('status')).toHaveProperty('tagName', 'OUTPUT');
  });
});

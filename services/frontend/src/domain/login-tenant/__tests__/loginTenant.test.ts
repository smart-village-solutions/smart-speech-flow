import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { readConfig } from '@/app/config/env';
import { createHttpClient } from '@/core/http/client';
import { toLoginTenants } from '@/domain/login-tenant/loginTenant.mapper';
import { createLoginTenantRepository } from '@/domain/login-tenant/loginTenant.repository';
import { server } from '@/test/setup';

const validDirectory = {
  tenants: [
    { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' },
    { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' },
  ],
};

describe('toLoginTenants', () => {
  it('maps valid entries without changing the Studio directory order', () => {
    expect(toLoginTenants(validDirectory)).toEqual([
      { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' },
      { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' },
    ]);
  });

  it('keeps domain entries limited to their public fields', () => {
    expect(
      toLoginTenants({
        tenants: [
          {
            id: 'tenant-fulda',
            displayName: 'Amt Fulda',
            realm: 'fulda-ssf-2025',
            futureStudioField: 'ignored',
          },
        ],
      })
    ).toEqual([{ id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' }]);
  });

  it.each([
    ['a blank tenant ID', { tenants: [{ id: ' ', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' }] }],
    [
      'duplicate tenant IDs',
      {
        tenants: [
          { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' },
          { id: 'tenant-fulda', displayName: 'Stadt Kassel', realm: 'kassel-ssf-2025' },
        ],
      },
    ],
    ['a blank realm', { tenants: [{ id: 'tenant-fulda', displayName: 'Amt Fulda', realm: ' ' }] }],
    [
      'duplicate realms',
      {
        tenants: [
          { id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda-ssf-2025' },
          { id: 'tenant-kassel', displayName: 'Stadt Kassel', realm: 'fulda-ssf-2025' },
        ],
      },
    ],
    [
      'a blank display name',
      { tenants: [{ id: 'tenant-fulda', displayName: ' ', realm: 'fulda-ssf-2025' }] },
    ],
    [
      'invalid realm characters',
      { tenants: [{ id: 'tenant-fulda', displayName: 'Amt Fulda', realm: 'fulda/ssf' }] },
    ],
    ['a non-array tenants field', { tenants: {} }],
    ['a non-object tenant entry', { tenants: ['tenant-fulda'] }],
  ])('rejects %s', (_description, directory) => {
    expect(() => toLoginTenants(directory)).toThrow('Invalid login tenant directory response');
  });
});

describe('login tenant repository', () => {
  it('gets the anonymous tenant directory without an Authorization header', async () => {
    let authorization: string | null = 'not requested';
    server.use(
      http.get('http://api.test/api/login/tenants', ({ request }) => {
        authorization = request.headers.get('Authorization');
        return HttpResponse.json(validDirectory);
      })
    );
    const httpClient = createHttpClient(readConfig({ VITE_API_BASE_URL: 'http://api.test' }), () => 'de');
    const repository = createLoginTenantRepository(httpClient);

    await expect(repository.list()).resolves.toEqual(validDirectory.tenants);
    expect(authorization).toBeNull();
  });
});

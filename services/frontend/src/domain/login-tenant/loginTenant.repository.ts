import type { AxiosInstance } from 'axios';
import { toLoginTenants } from './loginTenant.mapper';
import type { LoginTenantDirectoryDto } from './loginTenant.mapper';
import type { LoginTenant } from './loginTenant.types';

export interface LoginTenantRepository {
  list(): Promise<LoginTenant[]>;
}

export function createLoginTenantRepository(http: AxiosInstance): LoginTenantRepository {
  return {
    async list() {
      const response = await http.get<LoginTenantDirectoryDto>('/api/login/tenants');
      return toLoginTenants(response.data);
    },
  };
}

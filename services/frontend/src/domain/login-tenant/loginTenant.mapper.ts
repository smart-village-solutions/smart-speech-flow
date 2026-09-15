import type { LoginTenant } from './loginTenant.types';

export interface LoginTenantDirectoryDto {
  tenants?: unknown;
}

const REALM_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const INVALID_DIRECTORY_ERROR = 'Invalid login tenant directory response';

function isNonBlankString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isLoginTenantDirectoryDto(value: unknown): value is LoginTenantDirectoryDto {
  return isRecord(value);
}

function isLoginTenant(value: unknown): value is LoginTenant {
  if (!isRecord(value)) {
    return false;
  }

  const { id, displayName, realm } = value;
  return (
    isNonBlankString(id) &&
    isNonBlankString(displayName) &&
    isNonBlankString(realm) &&
    REALM_PATTERN.test(realm)
  );
}

export function toLoginTenants(dto: unknown): LoginTenant[] {
  if (!isLoginTenantDirectoryDto(dto)) {
    throw new Error(INVALID_DIRECTORY_ERROR);
  }

  const { tenants } = dto;
  if (!Array.isArray(tenants) || !tenants.every(isLoginTenant)) {
    throw new Error(INVALID_DIRECTORY_ERROR);
  }

  const ids = new Set<string>();
  const realms = new Set<string>();
  for (const tenant of tenants) {
    if (ids.has(tenant.id) || realms.has(tenant.realm)) {
      throw new Error(INVALID_DIRECTORY_ERROR);
    }
    ids.add(tenant.id);
    realms.add(tenant.realm);
  }

  return tenants.map(({ id, displayName, realm }) => ({ id, displayName, realm }));
}

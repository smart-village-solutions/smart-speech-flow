import { describe, expect, it } from 'vitest';
import { readConfig } from '@/app/config/env';

describe('the interim admin password', () => {
  it('falls back to the legacy password when none is set', () => {
    expect(readConfig({}).adminPassword).toBe('ssf2025kassel');
  });

  it('takes the password the build supplies', () => {
    expect(readConfig({ VITE_APP_PASSWORD: 'letmein' }).adminPassword).toBe('letmein');
  });
});

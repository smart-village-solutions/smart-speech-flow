import { describe, expect, it } from 'vitest';
import { readConfig } from '@/app/config/env';

describe('admin dev entry configuration', () => {
  it('is off when unset, so a production build carries no bypass', () => {
    expect(readConfig({}).adminDevEntry).toBe(false);
  });

  it('is on only for the literal "true"', () => {
    expect(readConfig({ VITE_ADMIN_DEV_ENTRY: 'true' }).adminDevEntry).toBe(true);
  });

  it.each(['false', '1', 'yes', 'TRUE', ''])(
    'stays off for %o rather than throwing or guessing',
    (value) => {
      expect(readConfig({ VITE_ADMIN_DEV_ENTRY: value }).adminDevEntry).toBe(false);
    }
  );
});

describe('the interim admin password', () => {
  it('falls back to the legacy password when none is set', () => {
    expect(readConfig({}).adminPassword).toBe('ssf2025kassel');
  });

  it('takes the password the build supplies', () => {
    expect(readConfig({ VITE_APP_PASSWORD: 'letmein' }).adminPassword).toBe('letmein');
  });
});

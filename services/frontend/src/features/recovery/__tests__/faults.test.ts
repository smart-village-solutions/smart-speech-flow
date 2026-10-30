import { describe, expect, it } from 'vitest';
import { faultKey } from '@/features/recovery/faults';
import de from '@/i18n/locales/de.json';

describe('faultKey', () => {
  it.each(['PERMISSION_REQUIRED', 'SHARE_STALE', 'KEY_CHANGED'])(
    'names the refusal %s with its own message',
    (code) => {
      const key = faultKey(`refused.${code}`);
      expect(key).toBe(`admin.recovery.error.${code}`);
      expect(de.admin.recovery.error).toHaveProperty(code);
    }
  );

  it('says "unavailable" for anything it does not know', () => {
    expect(faultKey('refused.SOMETHING_ELSE')).toBe('admin.recovery.fault.unavailable');
  });
});

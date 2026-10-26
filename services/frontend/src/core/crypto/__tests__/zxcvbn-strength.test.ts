import { describe, expect, it } from 'vitest';
import { createZxcvbnStrength } from '@/core/crypto/zxcvbn-strength';

describe('passphrase strength', () => {
  it('scores common and personal passphrases low and long unrelated words high', async () => {
    const strength = createZxcvbnStrength();
    expect(await strength.score('Passwort12345', [])).toBeLessThan(4);
    expect(await strength.score('alice-tenant-kassel', ['alice', 'tenant-kassel'])).toBeLessThan(4);
    expect(await strength.score('kanne wolke ferne tisch blau', [])).toBe(4);
  });
});
